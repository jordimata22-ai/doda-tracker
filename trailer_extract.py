import re
from pathlib import Path

import fitz  # PyMuPDF


def _norm(s: str) -> str:
    # lowercase + strip accents
    import unicodedata
    s = (s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def _candidate_token(s: str) -> str | None:
    s = (s or "").strip().upper()
    if not s:
        return None

    # 1) Digits-only trailer numbers are common (ex: 524682, 5313)
    # Allow 4–8 digits (your trailers can be 4 digits too).
    m = re.search(r"\b\d{4,8}\b", s)
    if m:
        return m.group(0)

    # 2) Alnum trailers: 1–3 letters + 4–6 digits (ex: FG53705)
    m = re.search(r"\b[A-Z]{1,3}\d{4,6}\b", s)
    if m:
        return m.group(0)

    # 3) Fallback: find tight alnum tokens but REQUIRE at least one digit
    for tok in re.findall(r"\b[A-Z0-9]{5,9}\b", s):
        if any(ch.isdigit() for ch in tok):
            return tok

    return None


def extract_trailer_or_plate_from_pdf(pdf_path: Path) -> str | None:
    """Best-effort extraction of trailer/plate number from DODA PDF.

    Strategy:
    1) Use text extraction on page 1.
    2) Look for anchors like 'DEL VEHICULO' and use the next non-empty line.
    3) Fallback: look for the token in the long 'CADENA ORIGINAL' line.
    """
    pdf_path = Path(pdf_path)

    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count <= 0:
                return None
            page = doc.load_page(0)
            text = page.get_text("text") or ""
    except Exception:
        return None

    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None

    norm_lines = [_norm(ln) for ln in lines]

    # Anchor search (prefer the specific "DEL VEHICULO" block)
    # Since the document format is consistent, we should ONLY trust tokens found immediately after this anchor.
    anchors_primary = ["del vehiculo", "del vehículo"]
    for i, nln in enumerate(norm_lines):
        if any(a in nln for a in anchors_primary):
            for j in range(i + 1, min(i + 6, len(lines))):
                tok = _candidate_token(lines[j])
                if tok:
                    return tok
            # If we saw the anchor but didn't find a token right after it, do NOT fallback to other parts
            # of the document (CADENA ORIGINAL contains other numbers like RFC, etc.)
            return None

    # Secondary anchors (less reliable): keep as a fallback ONLY if primary anchor isn't present.
    anchors_secondary = ["contenedores/equipo", "contenedores/equipo de"]
    for i, nln in enumerate(norm_lines):
        if any(a in nln for a in anchors_secondary):
            for j in range(i + 1, min(i + 6, len(lines))):
                tok = _candidate_token(lines[j])
                if tok:
                    return tok
            return None

    # Fallback: scan for likely tokens, but bias toward tokens that appear multiple times
    # (often repeated in CADENA ORIGINAL)
    candidates = []
    for ln in lines:
        tok = _candidate_token(ln)
        if tok:
            candidates.append(tok)

    if not candidates:
        return None

    # pick the most frequent; tie -> first seen
    from collections import Counter

    c = Counter(candidates)
    best, _ = c.most_common(1)[0]
    return best
