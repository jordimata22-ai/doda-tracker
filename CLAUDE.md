# DODA Tracker — Claude Code Context

## What this app does

Tracks cross-border customs clearance for shipping orders. Operators upload DODA PDFs through a browser dashboard; the app extracts QR code links embedded in each PDF and polls the SAT (Mexico customs) portal on a schedule to detect when a shipment has cleared. All orders and their latest status are displayed on the dashboard.

## Tech stack

- Python 3.12 (required — numpy/opencv wheels not yet available for 3.14+)
- Flask==3.0.3
- gunicorn==22.0.0
- SQLite via stdlib `sqlite3` (no ORM)
- PyMuPDF==1.24.14 — PDF rendering
- opencv-python-headless==4.9.0.80 — QR detection
- pyzbar==0.1.9 — fallback QR decoder (requires `libzbar0` on Linux)
- numpy<2
- beautifulsoup4==4.12.3 — SAT page scraping
- requests==2.32.3 + urllib3==2.2.3
- watchdog==4.0.1 — local inbox folder watcher
- tzdata==2025.3

## File map

| File | Responsibility |
|------|---------------|
| `app.py` | Entry point: loads config, inits DB, starts watchdog + background checker thread, exposes WSGI `app` object for gunicorn |
| `web.py` | All Flask routes: login/logout, dashboard (`/`), PDF upload (`/upload`), notes/LS save, star toggle, delete, manual refresh |
| `db.py` | SQLite schema and all queries: `orders`, `links`, `checks` tables; migrations; `list_orders`, `record_check`, `update_ls`, etc. |
| `doda_check.py` | Fetches a SAT portal URL, scrapes visible text, matches against `status_map.json`, extracts event timestamps; contains `_LegacyTLSAdapter` for old TLS |
| `checks_runner.py` | Single-pass check loop: reads all links from DB, calls `fetch_status`, writes results back |
| `qr_extract.py` | Extracts QR code URLs from PDF pages using PyMuPDF → OpenCV (cv2) → pyzbar fallback, at zoom 3× then 4× |
| `trailer_extract.py` | Best-effort trailer/plate text extraction from PDF (disabled in production — manual entry only) |
| `delete_utils.py` | Moves a file or folder to a timestamped path under `storage/_TRASH/` |
| `prompt.py` | Headless stubs for interactive dialogs (`prompt_order_number`, `notify`, `confirm`) — all are no-ops/log-only on the server |
| `run_checks_once.py` | CLI dev utility: runs one check pass and prints results to stdout |
| `debug_query.py` | One-off dev script: raw SQLite query against `data/doda.db` for debugging |
| `gunicorn.conf.py` | Gunicorn config: 1 worker; `post_fork` hook starts the background checker inside the worker process |
| `config.json` | Runtime config: `inboxDir`, `intervalMinutes`, `dashboard.host/port` |
| `status_map.json` | Maps SAT Spanish phrases → normalized status codes, labels, severity, and `cleared` flag |
| `templates/index.html` | Dashboard UI: order cards, LS filter toggles, star, notes, dark/light theme |
| `templates/login.html` | Password login page |

## Running locally

```powershell
# From the project root
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Default dashboard: **http://127.0.0.1:8787**

`config.json` is created automatically on first run if missing (inbox defaults to `~/Documents/DODA-Inbox`).

## Deploying to Railway

- **Live service URL:** `web-production-d48fc.up.railway.app`
- **Start command (railway.toml):** `gunicorn app:app --bind 0.0.0.0:$PORT --config gunicorn.conf.py`
- **Procfile fallback:** `web: gunicorn app:app`
- **Branch strategy:** `main` → production; `staging` → testing
- `railway.toml` declares `libzbar0` as an apt package (required for pyzbar on Linux/nixpacks)
- `restartPolicyType = "on_failure"` — Railway auto-restarts on crash

## Known gotchas

- **pyzbar / libzbar0:** On Railway (Linux), `libzbar0` is installed via `railway.toml` `aptPackages`. On Windows it bundles the DLL automatically — no extra step needed.
- **SQLite is ephemeral on Railway:** There are no persistent volumes configured. The `data/doda.db` and `storage/` folder are wiped on every deploy. This is a known limitation.
- **Use `opencv-python-headless`**, not `opencv-python`. The Railway server has no display; the non-headless build will fail to import on a headless Linux box.
- **Active Railway service is `web-production-d48fc`**, not `doda-tracker-production`. Always push/check that service.
- **SAT portal uses legacy TLS** (small DH params that modern OpenSSL rejects). `doda_check.py` mounts `_LegacyTLSAdapter` on the session and sets `SECLEVEL=1` to work around this. `verify=False` is intentional — the portal has no secrets to protect.
- **Background thread / gunicorn pre-fork:** Threads started at import time don't survive into gunicorn worker processes. The `post_fork` hook in `gunicorn.conf.py` re-starts the background checker inside each worker. Do not move checker startup out of `post_fork` without understanding this.
- **Python 3.12 required locally:** numpy and opencv don't have wheels for 3.14+ yet. Use `py -3.12`.

## Conventions I follow

- Ship independent fixes as **separate commits** so each is individually revertable.
- Always stage explicitly (`git add <file>`), never `git add -A`.
- Before running anything new, verify the dependency install step wasn't skipped.
- `showFlash` JS helper in `index.html` must be defined globally before any code that calls it runs.
- `prompt.py` functions are headless stubs — the folder-watcher path cannot prompt in server mode. The `/upload` form in the UI is the primary way orders are added on the server.
- `trailer_extract.py` is disabled in production (all call sites are commented out). Manual entry via the upload form is used instead.

## Related docs (do not duplicate their content here)

- `DEPLOY_LOCAL.md` — teammate Windows `.exe` install instructions
- `DODA_Tracker_ProjectKnowledge.txt` — business context, IP notes, history
- `CLEANUP.md` — folder cleanup analysis (what's safe to delete vs. keep)
- *(DEV_OPS.md does not exist yet — create it if local server restart + Railway push procedures need documentation)*

## Keeping this file current

**IMPORTANT:** Whenever you (Claude Code) make changes that affect any of the following, update `CLAUDE.md` in the **same commit** as the code change:

- A new dependency added to `requirements.txt` → update **Tech stack**
- A new Python module added, removed, or fundamentally repurposed → update **File map**
- A change to `railway.toml`, `Procfile`, or `gunicorn.conf.py` → update **Deploying to Railway** or **Known gotchas**
- A new environmental requirement or platform-specific gotcha discovered → update **Known gotchas**
- A new convention or workflow rule established → update **Conventions I follow**

If unsure whether a change qualifies, **ask the user before committing**. Do not update `CLAUDE.md` for minor bug fixes, UI tweaks, or changes contained within a single function's internal logic.
