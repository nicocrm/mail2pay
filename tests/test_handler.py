import base64
import io
import json
from unittest.mock import MagicMock, patch

import pytest

from mail2pay.models import PaymentDetails


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf_bytes() -> bytes:
    """Create a minimal valid PDF and return raw bytes."""
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _make_event(from_addr: str = "sender@example.com") -> dict:
    body = {
        "type": "email.received",
        "data": {
            "email_id": "evt_1",
            "from": from_addr,
            "attachments": [
                {
                    "id": "att_1",
                    "filename": "invoice.pdf",
                    "content_type": "application/pdf",
                }
            ],
        },
    }
    return {"body": json.dumps(body)}


def _stub_extractor_class(payment: PaymentDetails):
    """Return a class whose instances always return `payment` from extract()."""
    class StubExtractor:
        def __init__(self, cfg, client=None):
            pass
        def extract(self, raw_text: str) -> PaymentDetails:
            return payment

    return StubExtractor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_handler_globals():
    """Reset module-level cache between tests."""
    import handler
    handler._cfg = None
    handler._extractor = None
    handler._mailer = None
    yield
    handler._cfg = None
    handler._extractor = None
    handler._mailer = None


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _run_handler(monkeypatch, payment: PaymentDetails, env: dict | None = None):
    """Run handle() with Resend and download mocked, webhook verification bypassed."""
    env = env or {}
    base_env = {
        "RESEND_API_KEY": "test-resend",
        "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "noreply@test.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }
    for k, v in {**base_env, **env}.items():
        monkeypatch.setenv(k, v)

    import os
    live_key = os.environ.get("MISTRAL_API_KEY")
    use_live = live_key and not live_key.startswith("test-")

    if not use_live:
        import mail2pay.llm as llm_mod
        monkeypatch.setattr(llm_mod, "Extractor", _stub_extractor_class(payment))

    resend_send_mock = MagicMock()
    attachments_get_mock = MagicMock(
        return_value={"download_url": "https://signed.example.com/invoice.pdf", "expires_at": "2099-01-01T00:00:00Z"}
    )

    with patch("resend.Emails.send", resend_send_mock), \
         patch("resend.Emails.Receiving.Attachments.get", attachments_get_mock), \
         patch("mail2pay.download._download", return_value=_make_pdf_bytes()), \
         patch("handler.verify_webhook", return_value=True):
        import handler
        result = handler.handle(_make_event(), context=None)

    return result, resend_send_mock


# ---------------------------------------------------------------------------
# Tests – happy path
# ---------------------------------------------------------------------------

def test_handler_returns_200(monkeypatch):
    payment = PaymentDetails(beneficiary_name="Acme BV", amount="99.00", iban="BE68539007547034", communication="TEST")
    result, _ = _run_handler(monkeypatch, payment)
    assert result["statusCode"] == 200


def test_handler_calls_resend_once(monkeypatch):
    payment = PaymentDetails(beneficiary_name="Acme BV", amount="99.00", iban="BE68539007547034", communication="TEST")
    _, resend_mock = _run_handler(monkeypatch, payment)
    resend_mock.assert_called_once()


def test_handler_sends_to_correct_address(monkeypatch):
    payment = PaymentDetails(beneficiary_name="Acme BV", amount="10.00", iban="BE68539007547034", communication="REF")
    _, resend_mock = _run_handler(monkeypatch, payment)
    call_args = resend_mock.call_args[0][0]
    assert call_args["to"] == ["sender@example.com"]


def test_handler_attaches_png(monkeypatch):
    payment = PaymentDetails(beneficiary_name="Acme BV", amount="25.50", iban="BE68539007547034", communication="X")
    _, resend_mock = _run_handler(monkeypatch, payment)
    call_args = resend_mock.call_args[0][0]
    attachments = call_args.get("attachments", [])
    assert attachments, "No attachments in email"
    raw = base64.b64decode(attachments[0]["content"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "Attachment is not a valid PNG"


# ---------------------------------------------------------------------------
# Tests – early-exit / error cases
# ---------------------------------------------------------------------------

def test_handler_no_attachments_returns_ok(monkeypatch):
    for k, v in {
        "RESEND_API_KEY": "r", "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    with patch("handler.verify_webhook", return_value=True):
        import handler
        event = {
            "body": json.dumps({
                "type": "email.received",
                "data": {
                    "email_id": "evt_2",
                    "from": "a@b.com",
                    "attachments": [],
                },
            })
        }
        result = handler.handle(event, context=None)
    assert result["statusCode"] == 200


def test_handler_validation_error_returns_ok(monkeypatch):
    """Malformed body → 200, no Resend send call."""
    for k, v in {
        "RESEND_API_KEY": "r", "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock), \
         patch("handler.verify_webhook", return_value=True):
        import handler
        # Missing required "data" field → ValidationError
        event = {"body": json.dumps({"type": "email.received"})}
        result = handler.handle(event, context=None)

    assert result["statusCode"] == 200
    resend_mock.assert_not_called()


def test_handler_wrong_event_type_returns_ok(monkeypatch):
    """type='email.sent' → 200, no Resend send call."""
    for k, v in {
        "RESEND_API_KEY": "r", "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock), \
         patch("handler.verify_webhook", return_value=True):
        import handler
        event = {
            "body": json.dumps({
                "type": "email.sent",
                "data": {
                    "email_id": "evt_3",
                    "from": "sender@example.com",
                    "attachments": [],
                },
            })
        }
        result = handler.handle(event, context=None)

    assert result["statusCode"] == 200
    resend_mock.assert_not_called()


def test_handler_attachment_download_failure_returns_500(monkeypatch):
    """Transport failure in get_pdf_attachment → 500 so Resend retries."""
    for k, v in {
        "RESEND_API_KEY": "r", "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    import httpx
    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock), \
         patch("resend.Emails.Receiving.Attachments.get", side_effect=httpx.ConnectError("timeout")), \
         patch("handler.verify_webhook", return_value=True):
        import handler
        result = handler.handle(_make_event(), context=None)

    assert result["statusCode"] == 500
    resend_mock.assert_not_called()


def test_handler_invalid_signature_returns_ok(monkeypatch):
    """Requests with bad webhook signatures are dropped: 200 returned, Resend never called."""
    for k, v in {
        "RESEND_API_KEY": "r", "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock), \
         patch("handler.verify_webhook", return_value=False):
        import handler
        event = {"body": json.dumps({"type": "email.received", "data": {"from": "attacker@evil.com", "email_id": "x", "attachments": []}})}
        result = handler.handle(event, context=None)

    assert result["statusCode"] == 200
    resend_mock.assert_not_called()
