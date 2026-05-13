import base64
import logging
from io import BytesIO
from typing import Optional

import pypdf

logger = logging.getLogger(__name__)

_MAX_PDF_B64_BYTES = 10 * 1024 * 1024  # 10 MB base64 ≈ ~7.5 MB decoded


def extract_pdf_text(base64_pdf: str) -> str:
    """Decode a base64-encoded PDF and return all page text concatenated."""
    if len(base64_pdf) > _MAX_PDF_B64_BYTES:
        raise ValueError(
            f"PDF attachment too large ({len(base64_pdf)} base64 bytes; "
            f"max {_MAX_PDF_B64_BYTES})"
        )
    raw = base64.b64decode(base64_pdf)
    reader = pypdf.PdfReader(BytesIO(raw))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def pick_pdf_attachment(attachments: list[dict]) -> Optional[dict]:
    """Return the first attachment that looks like a PDF, or None."""
    for att in attachments:
        content_type = (
            att.get("ContentType")
            or att.get("content_type")
            or att.get("contentType")
            or ""
        )
        filename = (
            att.get("Filename")
            or att.get("filename")
            or att.get("Name")
            or att.get("name")
            or ""
        )
        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            return att
    return None
