"""Download PDF attachments from the Resend Received Email Attachments API."""

from __future__ import annotations

import logging

import httpx
import resend

from mail2pay.models import WebhookAttachment

logger = logging.getLogger(__name__)

_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


class PDFTooLargeError(Exception):
    """Raised when a PDF attachment exceeds the size cap.

    This is non-retryable: the payload will not shrink on retry.
    """



def pick_pdf_attachment(
    attachments: list[WebhookAttachment],
) -> WebhookAttachment | None:
    """Return the first attachment that looks like a PDF, or None."""
    for att in attachments:
        content_type = att.content_type or ""
        filename = att.filename or ""
        if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            return att
    return None


def _download(url: str) -> bytes:
    """Download *url* with a 30-second timeout and a 10 MB size cap.

    Raises ``httpx.HTTPError`` on non-2xx responses.
    Raises ``ValueError`` when the response body exceeds ``_MAX_PDF_BYTES``.
    """
    with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
        resp.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > _MAX_PDF_BYTES:
                raise PDFTooLargeError(
                    f"PDF download exceeded size cap of {_MAX_PDF_BYTES} bytes"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def get_pdf_attachment(
    email_id: str,
    attachments: list[WebhookAttachment],
) -> bytes | None:
    """Pick the first PDF attachment, fetch its signed URL, download and return bytes.

    Returns ``None`` when no PDF attachment is present.
    Raises on transport / API errors so the caller can return an appropriate
    HTTP status (retryable failures should surface as non-200 so Resend retries).
    """
    att = pick_pdf_attachment(attachments)
    if att is None:
        return None

    logger.info(
        "Fetching attachment id=%s filename=%s for email_id=%s",
        att.id,
        att.filename,
        email_id,
    )
    result = resend.Emails.Receiving.Attachments.get(email_id, att.id)
    download_url = result.get("download_url")
    if not download_url:
        raise RuntimeError(
            f"Resend attachment response missing 'download_url' for attachment id={att.id}"
        )

    pdf_bytes = _download(download_url)
    logger.info(
        "Downloaded %d bytes for attachment id=%s", len(pdf_bytes), att.id
    )
    return pdf_bytes
