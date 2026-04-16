import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
DB_PATH = ROOT / "data" / "doda.db"


CST = ZoneInfo("America/Chicago")

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def to_cst(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CST).strftime('%Y-%m-%d %H:%M:%S %Z')
    except Exception:
        return iso


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with connect() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_no TEXT UNIQUE NOT NULL,
          pdf_path TEXT NOT NULL,
          created_at TEXT NOT NULL,
          trailer_no TEXT,
          starred INTEGER DEFAULT 0,
          notes TEXT DEFAULT '',
          inspection_start TEXT,
          inspection_end TEXT
        )
        """)

        # Lightweight migration for existing DBs (SQLite doesn't support IF NOT EXISTS on columns)
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(orders)").fetchall()]
            if "trailer_no" not in cols:
                con.execute("ALTER TABLE orders ADD COLUMN trailer_no TEXT")
            if "starred" not in cols:
                con.execute("ALTER TABLE orders ADD COLUMN starred INTEGER DEFAULT 0")
            if "notes" not in cols:
                con.execute("ALTER TABLE orders ADD COLUMN notes TEXT DEFAULT ''")
            if "inspection_start" not in cols:
                con.execute("ALTER TABLE orders ADD COLUMN inspection_start TEXT")
            if "inspection_end" not in cols:
                con.execute("ALTER TABLE orders ADD COLUMN inspection_end TEXT")
            if "ls_id" not in cols:
                con.execute("ALTER TABLE orders ADD COLUMN ls_id TEXT")
        except Exception:
            pass

        con.execute("""
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id INTEGER NOT NULL,
          url TEXT NOT NULL,
          first_seen TEXT NOT NULL,
          last_checked TEXT,
          last_status TEXT,
          last_is_clear INTEGER DEFAULT 0,
          last_event_ts TEXT,
          UNIQUE(order_id, url),
          FOREIGN KEY(order_id) REFERENCES orders(id)
        )
        """)

        # Migration: add last_event_ts
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(links)").fetchall()]
            if "last_event_ts" not in cols:
                con.execute("ALTER TABLE links ADD COLUMN last_event_ts TEXT")
        except Exception:
            pass

        con.execute("""
        CREATE TABLE IF NOT EXISTS checks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          link_id INTEGER NOT NULL,
          checked_at TEXT NOT NULL,
          status TEXT,
          is_clear INTEGER NOT NULL,
          http_status INTEGER,
          error TEXT,
          FOREIGN KEY(link_id) REFERENCES links(id)
        )
        """)


def upsert_order_with_pdf(order_no: str, pdf_path: str, trailer_no: str | None = None, ls_id: str | None = None) -> int:
    logger.info("DEBUG upsert_order_with_pdf: order_no=%s ls_id=%s", order_no, ls_id)
    with connect() as con:
        cur = con.execute("SELECT id FROM orders WHERE order_no=?", (order_no,))
        row = cur.fetchone()
        if row:
            oid = int(row[0])
            con.execute("UPDATE orders SET pdf_path=?, trailer_no=?, ls_id=? WHERE id=?", (pdf_path, trailer_no, ls_id, oid))
            return oid

        cur = con.execute(
            "INSERT INTO orders(order_no, pdf_path, created_at, trailer_no, ls_id) VALUES(?,?,?,?,?)",
            (order_no, pdf_path, utc_now(), trailer_no, ls_id)
        )
        return int(cur.lastrowid)


def add_links(order_id: int, urls: list[str]):
    if not urls:
        return
    with connect() as con:
        for url in urls:
            url = (url or "").strip()
            if not url:
                continue
            con.execute(
                "INSERT OR IGNORE INTO links(order_id, url, first_seen) VALUES(?,?,?)",
                (order_id, url, utc_now())
            )


def list_links_to_check() -> list[dict]:
    with connect() as con:
        cur = con.execute("SELECT id, url FROM links")
        out = []
        for link_id, url in cur.fetchall():
            url2 = (url or "").strip()
            out.append({"id": link_id, "url": url2})
        return out


def normalize_urls():
    """Trim whitespace/newlines from stored URLs."""
    with connect() as con:
        cur = con.execute("SELECT id, url FROM links")
        for link_id, url in cur.fetchall():
            url2 = (url or "").strip()
            if url2 != (url or ""):
                con.execute("UPDATE links SET url=? WHERE id=?", (url2, link_id))


def record_check(link_id: int, url: str, status: dict):
    with connect() as con:
        now = utc_now()
        compact = None
        code = status.get("status") or ""
        label = status.get("label") or ""
        crossed_at = status.get("crossed_at")
        event_ts_iso = status.get("event_ts_iso")

        if code or label:
            compact = f"{code} | {label}".strip(" |")
            if crossed_at:
                compact = f"{compact} | {crossed_at}".strip(" |")

        con.execute(
            "INSERT INTO checks(link_id, checked_at, status, is_clear, http_status, error) VALUES(?,?,?,?,?,?)",
            (link_id, now, compact or status.get("excerpt"), 1 if status.get("is_clear") else 0, status.get("http_status"), status.get("error")),
        )
        con.execute(
            "UPDATE links SET last_checked=?, last_status=?, last_is_clear=?, last_event_ts=? WHERE id=?",
            (now, compact or status.get("excerpt"), 1 if status.get("is_clear") else 0, event_ts_iso, link_id),
        )

        # Update inspection timestamps on the orders table
        if event_ts_iso and code in ("MEX_RED", "MEX_RED_DONE"):
            order_row = con.execute(
                "SELECT o.id, o.inspection_start FROM orders o "
                "JOIN links l ON l.order_id = o.id WHERE l.id = ?",
                (link_id,)
            ).fetchone()
            if order_row:
                order_id, insp_start = order_row
                if code == "MEX_RED" and not insp_start:
                    con.execute(
                        "UPDATE orders SET inspection_start=? WHERE id=?",
                        (event_ts_iso, order_id)
                    )
                elif code == "MEX_RED_DONE":
                    con.execute(
                        "UPDATE orders SET inspection_end=? WHERE id=?",
                        (event_ts_iso, order_id)
                    )


def toggle_star(order_no: str) -> int:
    with connect() as con:
        cur = con.execute("SELECT starred FROM orders WHERE order_no=?", (order_no,))
        row = cur.fetchone()
        if not row:
            return 0
        cur_val = int(row[0] or 0)
        new_val = 0 if cur_val else 1
        con.execute("UPDATE orders SET starred=? WHERE order_no=?", (new_val, order_no))
        return new_val


def update_notes(order_no: str, notes: str) -> bool:
    with connect() as con:
        cur = con.execute("UPDATE orders SET notes=? WHERE order_no=?", (notes, order_no))
        return cur.rowcount > 0


def delete_order(order_no: str) -> dict:
    with connect() as con:
        cur = con.execute("SELECT id, pdf_path FROM orders WHERE order_no=?", (order_no,))
        row = cur.fetchone()
        if not row:
            return {"pdf_path": None}
        oid, pdf_path = int(row[0]), row[1]
        con.execute("DELETE FROM checks WHERE link_id IN (SELECT id FROM links WHERE order_id=?)", (oid,))
        con.execute("DELETE FROM links WHERE order_id=?", (oid,))
        con.execute("DELETE FROM orders WHERE id=?", (oid,))
        return {"pdf_path": pdf_path}


def _parse_sat_ts(ts: str | None):
    """Parse a SAT ISO timestamp string (no timezone) into a datetime, or None."""
    if not ts:
        return None
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(ts)
    except Exception:
        return None


def _fmt_sat_ts(ts: str | None) -> str | None:
    """Format a SAT ISO timestamp for display: '01/25 10:10am'."""
    dt = _parse_sat_ts(ts)
    if not dt:
        return None
    try:
        h = dt.hour
        ampm = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"{dt.month:02d}/{dt.day:02d} {h12}:{dt.minute:02d}{ampm}"
    except Exception:
        return ts


def get_order_summary(order_no: str) -> dict | None:
    with connect() as con:
        cur = con.execute(
            """
            SELECT o.order_no, o.trailer_no, o.created_at, l.last_status
            FROM orders o
            LEFT JOIN links l ON l.order_id = o.id
            WHERE o.order_no = ?
            ORDER BY l.last_checked DESC
            LIMIT 1
            """,
            (order_no,)
        )
        row = cur.fetchone()
        if not row:
            return None
        order_no2, trailer_no, created_at, last_status = row
        return {
            "order_no": order_no2,
            "trailer_no": trailer_no,
            "created_at": to_cst(created_at) or created_at,
            "last_status": last_status or "PENDING",
        }


def list_orders() -> list[dict]:
    with connect() as con:
        cur = con.execute(
            """
            SELECT o.order_no, o.pdf_path, o.created_at, o.trailer_no, o.starred, o.notes,
                   o.inspection_start, o.inspection_end, o.ls_id,
                   l.url, l.last_checked, l.last_is_clear, l.last_status, l.last_event_ts
            FROM orders o
            LEFT JOIN links l ON l.order_id = o.id
            ORDER BY o.created_at DESC
            """
        )
        rows = cur.fetchall()

        # Detect orders that previously had a MEX_RED (ROJO) check
        rojo_cur = con.execute(
            """
            SELECT DISTINCT o.order_no
            FROM orders o
            JOIN links l ON l.order_id = o.id
            JOIN checks c ON c.link_id = l.id
            WHERE c.is_clear = 0
              AND c.status IS NOT NULL
              AND (c.status = 'MEX_RED' OR c.status LIKE 'MEX_RED |%')
            """
        )
        had_rojo_set = {row[0] for row in rojo_cur.fetchall()}

    # group by order
    by = {}
    for order_no, pdf_path, created_at, trailer_no, starred, notes, inspection_start, inspection_end, ls_id, url, last_checked, last_is_clear, last_status, last_event_ts in rows:
        o = by.setdefault(order_no, {
            "order_no": order_no,
            "pdf_path": pdf_path,
            "created_at": to_cst(created_at) or created_at,
            "created_at_raw": created_at,
            "trailer_no": trailer_no,
            "starred": int(starred or 0),
            "notes": notes or "",
            "had_rojo": order_no in had_rojo_set,
            "inspection_start": inspection_start,
            "inspection_end": inspection_end,
            "ls_id": ls_id,
            "links": [],
        })
        if url:
            url = str(url).strip()
            o["links"].append({
                "url": url,
                "last_checked": to_cst(last_checked) or last_checked,
                "is_clear": bool(last_is_clear),
                "last_status": last_status,
                "last_event_ts": last_event_ts,
            })

    def key(l):
        lc = (l.get("last_checked") or "").strip()
        return (bool(l.get("last_checked")), lc)

    for o in by.values():
        o["links"].sort(key=key, reverse=True)

        # Compute inspection duration / since for display
        start_dt = _parse_sat_ts(o.get("inspection_start"))
        end_dt   = _parse_sat_ts(o.get("inspection_end"))
        if start_dt and end_dt:
            secs = max(0, int((end_dt - start_dt).total_seconds()))
            hrs  = secs // 3600
            mins = (secs % 3600) // 60
            o["inspection_duration"] = f"{hrs}h {mins}min" if hrs else f"{mins}min"
            o["inspection_since"]    = None
        elif start_dt:
            o["inspection_duration"] = None
            o["inspection_since"]    = _fmt_sat_ts(o.get("inspection_start"))
        else:
            o["inspection_duration"] = None
            o["inspection_since"]    = None

    return [o for o in by.values() if o.get("links")]


def update_ls(order_no: str, ls_id: str) -> bool:
    with connect() as con:
        cur = con.execute("UPDATE orders SET ls_id=? WHERE order_no=?", (ls_id, order_no))
        return cur.rowcount > 0
