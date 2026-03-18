import re
import ssl
import warnings
import requests
from bs4 import BeautifulSoup

import json
from pathlib import Path

TARGET_PHRASE_DEFAULT = "DESADUANAMIENTO LIBRE"

ROOT = Path(__file__).resolve().parent
STATUS_MAP_PATH = ROOT / "status_map.json"

# --- TLS compatibility (SAT sometimes uses small DH params) ---
# Python/OpenSSL can reject these with DH_KEY_TOO_SMALL. We lower OpenSSL security
# level for THIS specific client so we can read public status pages.
class _LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except Exception:
            pass
        pool_kwargs["ssl_context"] = ctx
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

_session = requests.Session()
_session.mount("https://", _LegacyTLSAdapter())
# We are not sending secrets; suppress noisy warnings when verify=False.
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


def _norm(s: str) -> str:
    # Lowercase + remove accents/diacritics + collapse whitespace + handle mojibake.
    import unicodedata
    s = (s or "")
    s = s.replace("\uFFFD", "")  # replacement char
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _load_status_map():
    try:
        data = json.loads(STATUS_MAP_PATH.read_text(encoding="utf-8"))
        phrases = data.get("phrases", [])
        # Sort by longest phrase first to avoid partial-match confusion.
        phrases = sorted(phrases, key=lambda x: len(x.get("phrase", "")), reverse=True)
        return phrases
    except Exception:
        return [{"phrase": TARGET_PHRASE_DEFAULT, "status": "CLEARED", "label": "Trailer crossed", "cleared": True, "severity": "ok"}]


def _match_status(visible_text: str):
    hay = _norm(visible_text)
    phrases = _load_status_map()

    matches = []
    for entry in phrases:
        phrase = str(entry.get("phrase", "")).strip()
        if not phrase:
            continue
        if _norm(phrase) in hay:
            matches.append(entry)

    if not matches:
        return {
            "matchedPhrase": None,
            "status": "UNKNOWN",
            "label": "Unknown",
            "cleared": False,
            "severity": "unknown",
        }

    # If multiple phrases appear, choose by priority list first, then longest phrase.
    try:
        raw = json.loads(STATUS_MAP_PATH.read_text(encoding="utf-8"))
        prio = raw.get("priorities", [])
    except Exception:
        prio = []

    def rank(entry):
        st = entry.get("status")
        pr = prio.index(st) if st in prio else 999
        return (pr, -len(entry.get("phrase", "")))

    best = sorted(matches, key=rank)[0]
    phrase = str(best.get("phrase", "")).strip()
    return {
        "matchedPhrase": phrase,
        "status": best.get("status"),
        "label": best.get("label"),
        "cleared": bool(best.get("cleared")),
        "severity": best.get("severity"),
    }


def _extract_event_ts(visible_text: str) -> tuple[str, str] | None:
    """Extract the event timestamp shown on SAT status pages.

    Works for:
    - CLEARED (DESADUANAMIENTO LIBRE)
    - MEX_RED (RECONOCIMIENTO ADUANERO)
    - MEX_RED_DONE (RECONOCIMIENTO ADUANERO CONCLUIDO)

    Example snippet:
      "Activación del Mecanismo...\n25-01-2026 10:10:38 OPER:...\n***DESADUANAMIENTO LIBRE***"

    Returns:
      (display, iso_utc_like)

    display: "01/25 10:10am" (12-hour)
    iso: "2026-01-25T10:10:38" (no timezone; SAT time is treated as local wall time)
    """
    m = re.search(r"\b(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\b", visible_text)
    if not m:
        return None
    dd, mm, yyyy, HH, MM, SS = m.groups()
    try:
        h = int(HH)
        minute = int(MM)
        ampm = "am" if h < 12 else "pm"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        display = f"{mm}/{dd} {h12}:{minute:02d}{ampm}"
        iso = f"{yyyy}-{mm}-{dd}T{HH}:{MM}:{SS}"
        return (display, iso)
    except Exception:
        return None


def fetch_status(url: str) -> dict:
    """Fetch URL and determine status based on status_map.json.

    Returns:
      { ok, http_status, is_clear, matchedPhrase, status, label, severity, error, excerpt, crossed_at }
    """
    try:
        # SAT site sometimes uses legacy TLS params that can fail on strict clients.
        # Use the legacy TLS session and disable verification (read-only, no secrets).
        resp = _session.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"}, verify=False)
        http_status = resp.status_code
        text = resp.text or ""

        # Use bytes to avoid charset weirdness.
        raw = resp.content or b""
        try:
            text = raw.decode("utf-8")
        except Exception:
            text = raw.decode("latin-1", errors="ignore")

        soup = BeautifulSoup(text, 'html.parser')
        visible = soup.get_text("\n", strip=True)
        visible2 = re.sub(r"\s+", " ", visible)

        matched = _match_status(visible2)

        crossed_at = None
        event_ts_iso = None
        # Add timestamp for CLEARED + MEX_RED + MEX_RED_DONE
        if matched.get("status") in {"CLEARED", "MEX_RED", "MEX_RED_DONE"}:
            ts = _extract_event_ts(visible2)
            if ts:
                crossed_at, event_ts_iso = ts

        excerpt = visible2[:500]

        return {
            "ok": True,
            "http_status": http_status,
            "is_clear": bool(matched.get("cleared")),
            "matchedPhrase": matched.get("matchedPhrase"),
            "status": matched.get("status"),
            "label": matched.get("label"),
            "severity": matched.get("severity"),
            "crossed_at": crossed_at,
            "event_ts_iso": event_ts_iso,
            "error": None,
            "excerpt": excerpt,
        }

    except Exception as e:
        return {
            "ok": False,
            "http_status": None,
            "is_clear": False,
            "matchedPhrase": None,
            "status": "ERROR",
            "label": "Error",
            "severity": "error",
            "error": str(e),
            "excerpt": None,
        }
