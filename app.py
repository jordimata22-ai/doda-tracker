import json
import os
import sys
import threading
import time
import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from web import create_app
from db import init_db, upsert_order_with_pdf, add_links
from prompt import prompt_order_number, notify, confirm
from qr_extract import extract_qr_links_from_pdf
from trailer_extract import extract_trailer_or_plate_from_pdf
from checks_runner import run_checks_once


def app_root() -> Path:
    """Return the runtime root folder.

    - In dev: folder containing this file.
    - In PyInstaller build: folder containing the executable.

    This ensures config/data/storage live next to the portable EXE.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()

# File logging (portable, next to EXE / app root)
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "doda-tracker.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


def load_config():
    cfg_path = ROOT / "config.json"

    # If config.json is missing (or inboxDir unset), create a safe default.
    default_inbox = (Path.home() / "Documents" / "DODA-Inbox").resolve()

    if not cfg_path.exists():
        cfg = {
            "inboxDir": default_inbox.as_posix(),
            "intervalMinutes": 15,
            "dashboard": {"host": "0.0.0.0", "port": 8787},
        }
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    else:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    inbox_raw = str(cfg.get("inboxDir") or "").strip()
    if not inbox_raw:
        cfg["inboxDir"] = default_inbox.as_posix()
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    inbox = Path(cfg["inboxDir"]).expanduser()
    inbox.mkdir(parents=True, exist_ok=True)

    # Keep DB + storage portable (next to the EXE)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "storage").mkdir(exist_ok=True)

    return cfg


class InboxHandler(FileSystemEventHandler):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() != ".pdf":
            return

        # Give the OS a moment to finish writing the file
        time.sleep(0.5)

        try:
            # 1) Extract QR links first (so we don't bother prompting for an order number if there's no QR)
            links = extract_qr_links_from_pdf(p)
            if not links:
                # Move PDFs with no QR into a quarantine folder and DO NOT add to dashboard
                no_qr_dir = ROOT / "storage" / "_NO_QR"
                no_qr_dir.mkdir(parents=True, exist_ok=True)
                dest = no_qr_dir / p.name

                try:
                    p.replace(dest)
                except Exception:
                    dest.write_bytes(p.read_bytes())
                    p.unlink(missing_ok=True)

                notify(
                    title="No QR code found",
                    message=(
                        f"This PDF does not contain a readable QR code:\n{p.name}\n\n"
                        f"Moved to:\n{dest}\n\n"
                        "Tip: make sure the QR is clear and not too small."
                    ),
                )
                return

            # 2) We have links → extract trailer/plate from the PDF and auto-confirm
            trailer = extract_trailer_or_plate_from_pdf(p)
            if trailer:
                ok = confirm(
                    title="Confirm trailer/plates",
                    message=f"Is this the trailer/plates number?\n\n{trailer}",
                )
                if not ok:
                    notify(
                        title="Request Correction",
                        message=(
                            "Request Correction.\n\n"
                            f"Trailer/plates shown on DODA: {trailer}\n\n"
                            "(We do not edit the trailer number here.)"
                        ),
                    )
            else:
                notify(
                    title="Request Correction",
                    message=(
                        "Trailer/plates number could not be detected automatically.\n\n"
                        "Request Correction."
                    ),
                )
                trailer = None

            # 3) Prompt for order number, then store + track
            order_no = prompt_order_number(
                title="Assign Order Number",
                message=f"PDF detected with QR link(s):\n{p.name}\n\nEnter Order Number:",
            )
            if not order_no:
                return

            storage_dir = ROOT / "storage" / order_no
            storage_dir.mkdir(parents=True, exist_ok=True)
            dest = storage_dir / p.name

            # Move into storage
            try:
                p.replace(dest)
            except Exception:
                # fallback copy+delete
                dest.write_bytes(p.read_bytes())
                p.unlink(missing_ok=True)

            order_id = upsert_order_with_pdf(order_no=order_no, pdf_path=str(dest), trailer_no=trailer)
            add_links(order_id, links)

        except Exception as e:
            logging.error("Inbox handler error: %s", e)


def checker_loop(cfg):
    interval = max(1, int(cfg.get("intervalMinutes", 15))) * 60
    while True:
        try:
            run_checks_once()
        except Exception as e:
            logging.error("Checker error: %s", e)

        time.sleep(interval)


def _start_background(cfg):
    """Start checker thread and watchdog observer. Safe to call at module import."""
    # Checker thread
    t = threading.Thread(target=checker_loop, args=(cfg,), daemon=True)
    t.start()

    # Watchdog (best-effort — not critical in cloud/headless mode)
    try:
        inbox_dir = Path(cfg["inboxDir"])
        handler = InboxHandler(cfg)
        observer = Observer()
        observer.schedule(handler, str(inbox_dir), recursive=False)
        observer.daemon = True
        observer.start()
        return observer
    except Exception as e:
        logging.warning("Watchdog could not start (non-fatal in cloud mode): %s", e)
        return None


# ---------------------------------------------------------------------------
# Module-level initialisation — runs once when gunicorn (or python) imports
# this module.
# ---------------------------------------------------------------------------
_cfg = load_config()
init_db()
from db import normalize_urls
normalize_urls()
_observer = _start_background(_cfg)

# WSGI application object used by gunicorn:  `gunicorn app:app`
app = create_app()


def main():
    """Entry point for local `python app.py` usage."""
    host = os.environ.get("HOST", _cfg["dashboard"].get("host", "0.0.0.0"))
    port = int(os.environ.get("PORT", _cfg["dashboard"].get("port", 8787)))
    print(f"Dashboard: http://{host}:{port}")
    print(f"Inbox folder: {_cfg['inboxDir']}")
    try:
        app.run(host=host, port=port, debug=False)
    finally:
        if _observer:
            _observer.stop()
            _observer.join()


if __name__ == "__main__":
    main()
