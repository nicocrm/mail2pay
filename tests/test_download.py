"""Tests for mail2pay.download."""

from unittest.mock import MagicMock, patch

import pytest

from mail2pay.download import (
    PDFTooLargeError,
    _MAX_PDF_BYTES,
    _download,
    get_pdf_attachment,
    pick_pdf_attachment,
)
from mail2pay.models import WebhookAttachment


# ---------------------------------------------------------------------------
# pick_pdf_attachment
# ---------------------------------------------------------------------------

def test_pick_pdf_by_content_type():
    attachments = [
        WebhookAttachment(id="1", filename="report.txt", content_type="text/plain"),
        WebhookAttachment(id="2", filename="invoice.pdf", content_type="application/pdf"),
    ]
    result = pick_pdf_attachment(attachments)
    assert result is not None
    assert result.id == "2"


def test_pick_pdf_by_filename_extension():
    """Falls back to .pdf filename when content_type is missing."""
    attachments = [
        WebhookAttachment(id="1", filename="invoice.PDF"),
    ]
    result = pick_pdf_attachment(attachments)
    assert result is not None
    assert result.id == "1"


def test_pick_pdf_returns_none_when_no_pdf():
    attachments = [
        WebhookAttachment(id="1", filename="image.png", content_type="image/png"),
    ]
    assert pick_pdf_attachment(attachments) is None


def test_pick_pdf_returns_none_for_empty_list():
    assert pick_pdf_attachment([]) is None


def test_pick_pdf_returns_first_pdf():
    """When multiple PDFs are present, the first one is returned."""
    attachments = [
        WebhookAttachment(id="1", content_type="application/pdf"),
        WebhookAttachment(id="2", content_type="application/pdf"),
    ]
    result = pick_pdf_attachment(attachments)
    assert result is not None
    assert result.id == "1"


# ---------------------------------------------------------------------------
# get_pdf_attachment
# ---------------------------------------------------------------------------

def test_get_pdf_attachment_returns_none_when_no_pdf():
    attachments = [
        WebhookAttachment(id="1", filename="photo.jpg", content_type="image/jpeg"),
    ]
    result = get_pdf_attachment("email_123", attachments)
    assert result is None


def test_get_pdf_attachment_calls_resend_api_and_returns_bytes():
    """Calls Attachments.get with correct args and returns downloaded bytes."""
    att = WebhookAttachment(id="att_42", filename="bill.pdf", content_type="application/pdf")
    expected_bytes = b"%PDF fake content"

    attachments_get_mock = MagicMock(
        return_value={"download_url": "https://signed.example.com/bill.pdf", "expires_at": "2099-01-01T00:00:00Z"}
    )

    with patch("resend.Emails.Receiving.Attachments.get", attachments_get_mock), \
         patch("mail2pay.download._download", return_value=expected_bytes) as dl_mock:
        result = get_pdf_attachment("email_123", [att])

    attachments_get_mock.assert_called_once_with("email_123", "att_42")
    dl_mock.assert_called_once_with("https://signed.example.com/bill.pdf")
    assert result == expected_bytes


def test_get_pdf_attachment_propagates_api_error():
    """API errors bubble up so the caller can return 500."""
    att = WebhookAttachment(id="att_1", content_type="application/pdf")

    with patch("resend.Emails.Receiving.Attachments.get", side_effect=RuntimeError("API down")):
        with pytest.raises(RuntimeError, match="API down"):
            get_pdf_attachment("email_123", [att])


# ---------------------------------------------------------------------------
# _download (size cap)
# ---------------------------------------------------------------------------

def test_download_raises_on_size_overflow():
    """_download raises ValueError when response exceeds _MAX_PDF_BYTES."""
    # Create a mock streaming response that yields too much data
    big_chunk = b"x" * (_MAX_PDF_BYTES + 1)

    class FakeResponse:
        def raise_for_status(self):
            pass
        def iter_bytes(self):
            yield big_chunk
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    with patch("httpx.stream", return_value=FakeResponse()):
        with pytest.raises(PDFTooLargeError, match="size cap"):
            _download("https://example.com/huge.pdf")
