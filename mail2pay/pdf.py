import logging
from io import BytesIO

import pypdf

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf: bytes) -> str:
    """Parse raw PDF bytes and return all page text concatenated."""
    reader = pypdf.PdfReader(BytesIO(pdf))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)
