import logging
from pathlib import Path

import fitz  # PyMuPDF
import cv2
import numpy as np
from pyzbar.pyzbar import decode as _pyzbar_decode


def render_page_to_bgr(page: fitz.Page, zoom: float = 3.0) -> np.ndarray:
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8)
    img = img.reshape((pix.height, pix.width, 3))
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def decode_qr_from_image(bgr: np.ndarray) -> list[str]:
    detector = cv2.QRCodeDetector()
    ok, decoded_info, points, _ = detector.detectAndDecodeMulti(bgr)
    if not ok or not decoded_info:
        return []
    return [s for s in decoded_info if s]


def _decode_qr_pyzbar(bgr: np.ndarray) -> list[str]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return [r.data.decode("utf-8") for r in _pyzbar_decode(gray) if r.type == "QRCODE"]


def _decode_page(page: fitz.Page, page_num: int, logger: logging.Logger) -> list[str]:
    bgr3 = render_page_to_bgr(page, zoom=3.0)

    payloads = decode_qr_from_image(bgr3)
    if payloads:
        logger.info("cv2@3.0 decoded %d QR(s) on page %d", len(payloads), page_num)
        return payloads

    bgr4 = render_page_to_bgr(page, zoom=4.0)
    payloads = decode_qr_from_image(bgr4)
    if payloads:
        logger.info("cv2@4.0 decoded %d QR(s) on page %d", len(payloads), page_num)
        return payloads

    payloads = _decode_qr_pyzbar(bgr3)
    if payloads:
        logger.info("pyzbar@3.0 decoded %d QR(s) on page %d", len(payloads), page_num)
        return payloads

    payloads = _decode_qr_pyzbar(bgr4)
    if payloads:
        logger.info("pyzbar@4.0 decoded %d QR(s) on page %d", len(payloads), page_num)
        return payloads

    logger.warning("No QR found on page %d after cv2+pyzbar at zoom 3.0 and 4.0", page_num)
    return []


def extract_qr_links_from_pdf(pdf_path: Path) -> list[str]:
    logger = logging.getLogger(__name__)
    results = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            results.extend(_decode_page(doc.load_page(i), i, logger))

    out, seen = [], set()
    for r in results:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out
