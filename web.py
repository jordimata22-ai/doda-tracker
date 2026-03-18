import io
import logging
import sys
import time
from pathlib import Path

from flask import Flask, render_template_string, redirect, url_for, request, flash

import time

from db import list_orders, delete_order, toggle_star, upsert_order_with_pdf, add_links
from delete_utils import move_to_trash
from checks_runner import run_checks_once

ROOT = Path(__file__).resolve().parent
TRASH_ROOT = ROOT / "storage" / "_TRASH"

# Rate-limit manual refreshes (in-memory; per running instance)
_REFRESH_COOLDOWN_SECONDS = 5 * 60
_last_manual_refresh = 0.0

logger = logging.getLogger(__name__)

TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DODA Dashboard</title>
  <style>
    :root{
      --bg:#f6f7fb;
      --card:#ffffff;
      --text:#0f172a;
      --muted:#64748b;
      --line:#e2e8f0;
      --link:#2563eb;
      --shadow:0 10px 30px rgba(2,6,23,.08);

      --okBg:rgba(34,197,94,.12);
      --okFg:#166534;
      --okBd:rgba(34,197,94,.28);

      --warnBg:rgba(239,68,68,.12);
      --warnFg:#991b1b;
      --warnBd:rgba(239,68,68,.28);

      --unkBg:rgba(148,163,184,.14);
      --unkFg:#334155;
      --unkBd:rgba(148,163,184,.30);
    }

    [data-theme="dark"]{
      --bg:#0b1220;
      --card:#0f1b33;
      --text:#e5e7eb;
      --muted:#9ca3af;
      --line:#22304e;
      --link:#60a5fa;
      --shadow:0 10px 30px rgba(0,0,0,.35);

      --okBg:rgba(34,197,94,.18);
      --okFg:#86efac;
      --okBd:rgba(34,197,94,.28);

      --warnBg:rgba(239,68,68,.18);
      --warnFg:#fca5a5;
      --warnBd:rgba(239,68,68,.28);

      --unkBg:rgba(148,163,184,.14);
      --unkFg:#cbd5e1;
      --unkBd:rgba(148,163,184,.25);
    }

    *{box-sizing:border-box}
    body{margin:0;font-family:ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; background:var(--bg); color:var(--text);}
    .wrap{max-width:1100px;margin:0 auto;padding:22px;}
    h1{font-size:18px;margin:0 0 6px;font-weight:800;letter-spacing:-.01em;}
    .muted{color:var(--muted)}
    .small{font-size:12px;color:var(--muted)}
    .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:0;box-shadow:var(--shadow);overflow:hidden;}

    .toolbar{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:12px 14px;border-bottom:1px solid var(--line)}
    .toolbarLeft{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .toolbarRight{display:flex;gap:10px;align-items:center;flex-wrap:wrap}

    .select{border:1px solid var(--line);background:transparent;color:var(--text);padding:8px 10px;border-radius:12px;outline:none}

    .search{border:1px solid var(--line);background:transparent;color:var(--text);padding:8px 10px;border-radius:12px;min-width:220px;outline:none}
    .search::placeholder{color:var(--muted)}

    table{width:100%;border-collapse:separate;border-spacing:0;}
    th,td{padding:12px 12px;border-bottom:1px solid var(--line);vertical-align:middle;}
    thead th{position:sticky;top:0;background:var(--card);z-index:2}
    th{font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;text-align:left;font-weight:700;}
    tr:last-child td{border-bottom:none;}

    .order{font-weight:800;font-size:14px;}

    .badge{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-weight:800;font-size:11px;border:1px solid transparent;white-space:nowrap}
    .b-ok{background:var(--okBg); color:var(--okFg); border-color:var(--okBd)}
    .b-warn{background:var(--warnBg); color:var(--warnFg); border-color:var(--warnBd)}
    .b-unk{background:var(--unkBg); color:var(--unkFg); border-color:var(--unkBd)}

    .statusText{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.3}

    .topbar{display:flex;justify-content:space-between;gap:12px;align-items:flex-end;margin-bottom:12px;flex-wrap:wrap;}

    .iconBtn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:36px;
      height:36px;
      border-radius:12px;
      border:1px solid var(--line);
      background:transparent;
      box-shadow:none;
      cursor:pointer;
      color:var(--muted);
    }
    .iconBtn:hover{border-color:rgba(37,99,235,.35)}
    .icon{width:18px;height:18px;fill:var(--link)}
    .iconDanger .icon{fill:#ef4444}

    form{margin:0}

    .toast{padding:8px 10px;border-radius:12px;border:1px solid var(--line);color:var(--muted);font-size:12px}

    /* Upload panel */
    .uploadPanel{
      background:var(--card);
      border:1px solid var(--line);
      border-radius:16px;
      padding:16px 18px;
      box-shadow:var(--shadow);
      margin-bottom:14px;
      display:flex;
      gap:12px;
      align-items:flex-end;
      flex-wrap:wrap;
    }
    .uploadPanel label{font-size:12px;color:var(--muted);display:block;margin-bottom:4px;font-weight:600}
    .uploadPanel input[type=text]{
      border:1px solid var(--line);
      background:transparent;
      color:var(--text);
      padding:8px 10px;
      border-radius:12px;
      outline:none;
      min-width:160px;
    }
    .uploadPanel input[type=file]{
      border:1px solid var(--line);
      background:transparent;
      color:var(--text);
      padding:7px 10px;
      border-radius:12px;
      font-size:12px;
    }
    .uploadBtn{
      padding:8px 18px;
      border-radius:12px;
      border:none;
      background:var(--link);
      color:#fff;
      font-size:13px;
      font-weight:700;
      cursor:pointer;
      white-space:nowrap;
    }
    .uploadBtn:hover{opacity:.88}
    .flashOk{background:var(--okBg);color:var(--okFg);border:1px solid var(--okBd);border-radius:12px;padding:8px 14px;font-size:13px;margin-bottom:12px}
    .flashErr{background:var(--warnBg);color:var(--warnFg);border:1px solid var(--warnBd);border-radius:12px;padding:8px 14px;font-size:13px;margin-bottom:12px}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>DODA Dashboard</h1>
        <div class="muted">Auto-checks every 15 minutes · Manual refresh limited to every 5 minutes</div>
      </div>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="{{ 'flashOk' if cat == 'success' else 'flashErr' }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}

    <!-- Upload panel -->
    <div class="uploadPanel">
      <div>
        <label for="order_no">Order Number</label>
        <input type="text" id="order_no" name="order_no" form="uploadForm" placeholder="e.g. ORD-12345" required />
      </div>
      <div>
        <label for="pdf_file">DODA PDF</label>
        <input type="file" id="pdf_file" name="pdf_file" form="uploadForm" accept=".pdf" required />
      </div>
      <form id="uploadForm" method="post" action="{{ url_for('upload_pdf') }}" enctype="multipart/form-data">
        <button class="uploadBtn" type="submit">Upload PDF</button>
      </form>
    </div>

    <div class="card">
      <div class="toolbar">
        <div class="toolbarLeft">
          <form method="post" action="{{ url_for('refresh_now') }}">
            <button class="iconBtn" type="submit" title="Refresh now" aria-label="Refresh now">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M17.65 6.35A7.95 7.95 0 0012 4V1L7 6l5 5V7a5 5 0 11-4.9 6h-2.02A7 7 0 1017.65 6.35z"></path>
              </svg>
            </button>
          </form>

          <label class="small" for="sort" style="margin-left:6px">Sort</label>
          <select id="sort" class="select">
            <option value="PRIORITY" selected>Priority (Star + Pending)</option>
            <option value="EVENT_DESC">Event time (latest)</option>
            <option value="ADDED_DESC">Date added (latest)</option>
            <option value="ORDER_ASC">Order (A→Z)</option>
            <option value="TRAILER_ASC">Trailer (A→Z)</option>
          </select>
        </div>
        <div class="toolbarRight">
          <input id="q" class="search" placeholder="Search order or trailer…" />
          <div id="refreshMeta" class="toast"></div>
          <button id="themeBtn" class="iconBtn" title="Toggle dark mode" aria-label="Toggle dark mode">
            <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M21.64 13a1 1 0 00-1.05-.14A8 8 0 1111.14 3.41a1 1 0 00-.14-1.05 1 1 0 00-1.11-.41A10 10 0 1022.05 14.1a1 1 0 00-.41-1.1z"></path>
            </svg>
          </button>
        </div>
      </div>

      <table id="t">
        <thead>
          <tr>
            <th style="width:170px">Order</th>
            <th style="width:140px">Trailer</th>
            <th style="width:280px">Status</th>
            <th style="width:100px"></th>
          </tr>
        </thead>
        <tbody id="tbody">
          {% for o in orders %}
            {% set last_checked = 'never' %}
            {% set any_clear = false %}
            {% set last_status = '' %}
            {% set last_label = '' %}
            {% if o.links|length > 0 %}
              {% set last_checked = (o.links[0].last_checked or 'never') %}
              {% set last_status = (o.links[0].last_status or '') %}
              {% set parts = last_status.split('|') if '|' in last_status else [last_status] %}
              {% set last_code = (parts[0].strip() if parts|length > 0 else '') %}
              {% set last_label = (parts[1].strip() if parts|length > 1 else last_status) %}
              {% set last_crossed = (parts[2].strip() if parts|length > 2 else '') %}
              {% for l in o.links %}
                {% if l.is_clear %}{% set any_clear = true %}{% endif %}
              {% endfor %}
            {% endif %}

            {% set status_key = last_code if last_code else 'PENDING' %}
            {% set event_ts = (o.links[0].last_event_ts if o.links|length > 0 else '') %}
            <tr class="row" data-status="{{status_key}}" data-order="{{o.order_no}}" data-trailer="{{o.trailer_no or ''}}" data-event="{{event_ts or ''}}" data-added="{{o.created_at_raw or ''}}" data-star="{{o.starred or 0}}">
              <td>
                <div style="display:flex; align-items:center; gap:8px">
                  <form method="post" action="{{ url_for('toggle_star_route', order_no=o.order_no) }}">
                    <button class="iconBtn" type="submit" title="Star" aria-label="Star" style="width:30px;height:30px;border-radius:10px;">
                      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" style="fill:{{ '#f59e0b' if o.starred else 'var(--line)' }}">
                        <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"></path>
                      </svg>
                    </button>
                  </form>
                  <div class="order">{{o.order_no}}</div>
                </div>
              </td>
              <td><div class="order" style="font-weight:700">{{o.trailer_no or '—'}}</div></td>
              <td>
                {% if status_key == 'CLEARED' or any_clear %}
                  <span class="badge b-ok">CROSSED MX CUSTOMS</span>
                {% elif status_key == 'MEX_RED' %}
                  <span class="badge b-warn">ROJO MEXICANO</span>
                {% elif status_key == 'MEX_RED_DONE' %}
                  <span class="badge b-ok">ROJO / LIBERADO</span>
                {% else %}
                  <span class="badge b-unk">PENDING</span>
                {% endif %}

                {% if last_label %}
                  <div class="statusText">
                    {{last_label}}{% if last_crossed %} · {{last_crossed}}{% endif %}
                  </div>
                {% endif %}
              </td>
              <td style="text-align:right">
                {% set url = (o.links[0].url if o.links|length > 0 else '') %}
                {% if url %}
                  <a class="iconBtn" href="{{url}}" target="_blank" title="Open link" aria-label="Open link">
                    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M14 3h7v7h-2V6.41l-9.29 9.3-1.42-1.42 9.3-9.29H14V3z"></path>
                      <path d="M5 5h6v2H7v10h10v-4h2v6H5V5z"></path>
                    </svg>
                  </a>
                {% endif %}
                <form style="display:inline" method="post" action="{{ url_for('delete_order_route', order_no=o.order_no) }}" onsubmit="return confirm('Delete order ' + {{o.order_no|tojson}} + '? This will remove it from the dashboard.');">
                  <button class="iconBtn iconDanger" type="submit" title="Delete" aria-label="Delete order">
                    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M9 3h6l1 2h5v2H3V5h5l1-2zm1 6h2v10h-2V9zm4 0h2v10h-2V9zM7 9h2v10H7V9z"></path>
                    </svg>
                  </button>
                </form>
              </td>
            </tr>
          {% endfor %}

          {% if orders|length == 0 %}
            <tr><td colspan="4" class="muted" style="padding:18px 12px;">No orders yet. Upload a DODA PDF above to get started.</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
  </div>
  <script>
    // --- Theme ---
    const root = document.documentElement;
    const savedTheme = localStorage.getItem('dodaTheme');
    if (savedTheme) root.setAttribute('data-theme', savedTheme);

    document.getElementById('themeBtn')?.addEventListener('click', () => {
      const cur = root.getAttribute('data-theme') || 'light';
      const next = cur === 'dark' ? 'light' : 'dark';
      if (next === 'light') root.removeAttribute('data-theme');
      else root.setAttribute('data-theme', 'dark');
      localStorage.setItem('dodaTheme', next);
    });

    // --- Refresh meta ---
    const remaining = {{ remaining|default(0) }};
    const lastManual = {{ last_manual_refresh|default(0) }};
    const justRefreshed = {{ 'true' if just_refreshed else 'false' }};

    function fmtTime(sec){
      const d = new Date(sec*1000);
      return d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
    }

    function tick(){
      const el = document.getElementById('refreshMeta');
      if (!el) return;
      const now = Math.floor(Date.now()/1000);
      const cooldown = 300;
      const rem = lastManual ? Math.max(0, cooldown - (now - lastManual)) : 0;
      if (!lastManual) {
        el.textContent = 'Ready to refresh';
      } else if (rem > 0) {
        const m = Math.floor(rem/60);
        const s = rem%60;
        el.textContent = `Last refresh ${fmtTime(lastManual)} · Next in ${m}:${String(s).padStart(2,'0')}`;
      } else {
        el.textContent = `Last refresh ${fmtTime(lastManual)} · Ready`;
      }
    }
    tick();
    setInterval(tick, 1000);

    // --- Client-side search + sort ---
    const tbody = document.getElementById('tbody');
    const rows = Array.from(document.querySelectorAll('tr.row'));

    let activeSort = 'PRIORITY';
    let query = '';

    function eventEpoch(row){
      const iso = row.dataset.event || '';
      if (!iso) return 0;
      const d = new Date(iso);
      const t = d.getTime();
      return isNaN(t) ? 0 : Math.floor(t/1000);
    }

    function addedEpoch(row){
      const iso = row.dataset.added || '';
      if (!iso) return 0;
      const d = new Date(iso);
      const t = d.getTime();
      return isNaN(t) ? 0 : Math.floor(t/1000);
    }

    function isPending(row){
      const st = row.dataset.status || '';
      return (st === 'PENDING' || st === 'UNKNOWN' || st === 'NOT_PRESENTED' || !st);
    }

    function isStar(row){
      return String(row.dataset.star || '0') === '1';
    }

    function apply(){
      const q = query.trim().toLowerCase();
      let filtered = rows.filter(r => {
        if (q) {
          const hay = ((r.dataset.order||'') + ' ' + (r.dataset.trailer||'')).toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      filtered.sort((a,b) => {
        if (activeSort === 'PRIORITY') {
          const s = (isStar(b) - isStar(a));
          if (s !== 0) return s;
          const p = (isPending(a) - isPending(b));
          if (p !== 0) return p;
          return eventEpoch(b) - eventEpoch(a);
        }
        if (activeSort === 'EVENT_DESC') return eventEpoch(b) - eventEpoch(a);
        if (activeSort === 'ADDED_DESC') return addedEpoch(b) - addedEpoch(a);
        if (activeSort === 'ORDER_ASC') return String(a.dataset.order||'').localeCompare(String(b.dataset.order||''));
        if (activeSort === 'TRAILER_ASC') return String(a.dataset.trailer||'').localeCompare(String(b.dataset.trailer||''));
        return 0;
      });

      if (!tbody) return;
      tbody.innerHTML = '';
      for (const r of filtered) tbody.appendChild(r);
    }

    const sortEl = document.getElementById('sort');
    sortEl?.addEventListener('change', (e) => {
      activeSort = e.target.value || 'PRIORITY';
      apply();
    });

    const qEl = document.getElementById('q');
    qEl?.addEventListener('input', (e) => {
      query = e.target.value || '';
      apply();
    });

    apply();
  </script>
</body>
</html>
"""


def create_app():
    app = Flask(__name__)
    app.secret_key = "doda-tracker-secret"   # needed for flash messages

    @app.get("/")
    def index():
        orders = list_orders()
        now = time.time()
        remaining = max(0, int(_REFRESH_COOLDOWN_SECONDS - (now - _last_manual_refresh))) if _last_manual_refresh else 0
        return render_template_string(
            TEMPLATE,
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
        """Accept a PDF upload + order number via web form and add it to the tracker."""
        from qr_extract import extract_qr_links_from_pdf
        from trailer_extract import extract_trailer_or_plate_from_pdf
        import tempfile, os

        order_no = (request.form.get("order_no") or "").strip()
        if not order_no:
            flash("Order number is required.", "error")
            return redirect(url_for("index"))

        uploaded_file = request.files.get("pdf_file")
        if not uploaded_file or uploaded_file.filename == "":
            flash("Please select a PDF file to upload.", "error")
            return redirect(url_for("index"))

        filename = uploaded_file.filename
        if not filename.lower().endswith(".pdf"):
            flash("Only PDF files are accepted.", "error")
            return redirect(url_for("index"))

        # Save to a temp file so extraction functions can read it from disk
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
                uploaded_file.save(tmp_path)

            tmp_path = Path(tmp_path)

            # Extract QR links
            links = extract_qr_links_from_pdf(tmp_path)
            if not links:
                no_qr_dir = ROOT / "storage" / "_NO_QR"
                no_qr_dir.mkdir(parents=True, exist_ok=True)
                dest = no_qr_dir / filename
                tmp_path.replace(dest)
                flash(
                    f"No QR code found in '{filename}'. File moved to _NO_QR for review.",
                    "error",
                )
                return redirect(url_for("index"))

            # Extract trailer/plate number automatically (no confirmation dialog)
            trailer = extract_trailer_or_plate_from_pdf(tmp_path)

            # Move PDF into permanent storage
            storage_dir = ROOT / "storage" / order_no
            storage_dir.mkdir(parents=True, exist_ok=True)
            dest = storage_dir / filename
            try:
                tmp_path.replace(dest)
            except Exception:
                dest.write_bytes(tmp_path.read_bytes())
                tmp_path.unlink(missing_ok=True)

            # Write to DB
            order_id = upsert_order_with_pdf(
                order_no=order_no,
                pdf_path=str(dest),
                trailer_no=trailer,
            )
            add_links(order_id, links)

            trailer_msg = f" (trailer: {trailer})" if trailer else ""
            flash(
                f"Order {order_no} added with {len(links)} QR link(s){trailer_msg}.",
                "success",
            )

        except Exception as e:
            logger.exception("Upload error for order %s: %s", order_no, e)
            flash(f"Upload failed: {e}", "error")
            # Clean up temp file if still around
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        return redirect(url_for("index"))

    @app.post("/star/<order_no>")
    def toggle_star_route(order_no: str):
        try:
            toggle_star(order_no)
        except Exception:
            pass
        return redirect(url_for("index"))

    @app.post("/delete/<order_no>")
    def delete_order_route(order_no: str):
        # 1) Delete from DB
        info = delete_order(order_no)

        # 2) Move files to local trash (recoverable)
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
