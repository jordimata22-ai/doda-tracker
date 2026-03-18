from pathlib import Path

import fitz  # PyMuPDF
import cv2
import numpy as np


def render_page_to_bgr(page: fitz.Page, zoom: float = 2.0) -> np.ndarray:
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8)
    img = img.reshape((pix.height, pix.width, 3))
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def decode_qr_from_image(bgr: np.ndarray):
    detector = cv2.QRCodeDetector()
    ok, decoded_info, points, _ = detector.detectAndDecodeMulti(bgr)
    if not ok or not decoded_info:
        return []
    return [s for s in decoded_info if s]


def extract_qr_links_from_pdf(pdf_path: Path) -> list[str]:
    results = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            bgr = render_page_to_bgr(page)
            payloads = decode_qr_from_image(bgr)
            for payload in payloads:
                if payload.startswith('http://') or payload.startswith('https://'):
                    results.append(payload)
                else:
                    # still store non-http payloads; might be useful
                    results.append(payload)

    # dedupe preserve order
    out = []
    seen = set()
    for r in results:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out
