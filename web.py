# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify

from db import list_orders, delete_order, toggle_star, upsert_order_with_pdf, add_links, update_notes
from delete_utils import move_to_trash
from checks_runner import run_checks_once

ROOT = Path(__file__).resolve().parent
TRASH_ROOT = ROOT / "storage" / "_TRASH"

_REFRESH_COOLDOWN_SECONDS = 5 * 60
_last_manual_refresh = 0.0

logger = logging.getLogger(__name__)



def create_app():
    app = Flask(__name__)
    app.secret_key = "doda-tracker-secret"

    @app.get("/")
    def index():
        orders = list_orders()
        now = time.time()
        remaining = max(0, int(_REFRESH_COOLDOWN_SECONDS - (now - _last_manual_refresh))) if _last_manual_refresh else 0
        return render_template(
            'index.html',
            orders=orders,
            remaining=remaining,
            last_manual_refresh=int(_last_manual_refresh) if _last_manual_refresh else 0,
            just_refreshed=(request.args.get('refreshed') == '1'),
        )

    @app.post("/refresh")
    def refresh_now():
        global _last_manual_refresh
        now = time.time()
        if _last_manual_refresh and (now - _last_manual_refresh) < _REFRESH_COOLDOWN_SECONDS:
            return redirect(url_for("index"))
        _last_manual_refresh = now
        try:
            run_checks_once()
        except Exception:
            pass
        return redirect(url_for("index", refreshed=1))

    @app.post("/upload")
    def upload_pdf():
        from qr_extract import extract_qr_links_from_pdf
        from trailer_extract import extract_trailer_or_plate_from_pdf
        import tempfile

        order_no = (request.form.get("order_no") or "").strip()
        if not order_no:
            flash("Número de orden requerido.", "error")
            return redirect(url_for("index"))
        if not order_no.isdigit() or len(order_no) != 6:
            flash("El número de orden debe ser exactamente 6 dígitos.", "error")
            return redirect(url_for("index"))

        uploaded_file = request.files.get("pdf_file")
        if not uploaded_file or uploaded_file.filename == "":
            flash("Por favor selecciona un archivo PDF.", "error")
            return redirect(url_for("index"))
        filename = uploaded_file.filename
        if not filename.lower().endswith(".pdf"):
            flash("Solo se aceptan archivos PDF.", "error")
            return redirect(url_for("index"))

        identifier_type  = (request.form.get("identifier_type")  or "trailer").strip()
        identifier_value = (request.form.get("identifier_value") or "").strip()

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
                uploaded_file.save(tmp_path)
            tmp_path = Path(tmp_path)

            links = extract_qr_links_from_pdf(tmp_path)
            if not links:
                no_qr_dir = ROOT / "storage" / "_NO_QR"
                no_qr_dir.mkdir(parents=True, exist_ok=True)
                tmp_path.replace(no_qr_dir / filename)
                flash(f"No se encontró código QR en '{filename}'. Archivo movido a _NO_QR.", "error")
                return redirect(url_for("index"))

            trailer = identifier_value if identifier_value else extract_trailer_or_plate_from_pdf(tmp_path)

            storage_dir = ROOT / "storage" / order_no
            storage_dir.mkdir(parents=True, exist_ok=True)
            dest = storage_dir / filename
            try:
                tmp_path.replace(dest)
            except Exception:
                dest.write_bytes(tmp_path.read_bytes())
                tmp_path.unlink(missing_ok=True)

            order_id = upsert_order_with_pdf(order_no=order_no, pdf_path=str(dest), trailer_no=trailer)
            add_links(order_id, links)

            id_msg = f" ({identifier_type}: {trailer})" if trailer else ""
            flash(f"Orden {order_no} agregada con {len(links)} enlace(s) QR{id_msg}.", "success")

        except Exception as e:
            logger.exception("Upload error for order %s: %s", order_no, e)
            flash(f"Error al subir: {e}", "error")
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        return redirect(url_for("index"))

    @app.post("/notes/<order_no>")
    def save_notes(order_no: str):
        data  = request.get_json(silent=True) or {}
        notes = str(data.get("notes", "")).strip()
        ok    = update_notes(order_no, notes)
        return jsonify({"ok": ok})

    @app.post("/star/<order_no>")
    def toggle_star_route(order_no: str):
        try:
            toggle_star(order_no)
        except Exception:
            pass
        return redirect(url_for("index"))

    @app.post("/delete/<order_no>")
    def delete_order_route(order_no: str):
        info     = delete_order(order_no)
        pdf_path = info.get("pdf_path")
        try:
            if pdf_path:
                p = Path(pdf_path)
                if p.exists() and p.parent.exists() and p.parent.is_dir():
                    if p.parent.name == str(order_no):
                        move_to_trash(p.parent, TRASH_ROOT)
                    else:
                        move_to_trash(p, TRASH_ROOT)
        except Exception:
            pass
        return redirect(url_for("index"))

    return app
