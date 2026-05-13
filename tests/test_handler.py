import base64
import io
import json
import importlib
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from mail2pay.models import PaymentDetails


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf_b64() -> str:
    """Create a minimal valid PDF and return it base64-encoded."""
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return base64.b64encode(buf.getvalue()).decode()


def _make_event(pdf_b64: str, from_addr: str = "sender@example.com") -> dict:
    body = {
        "From": from_addr,
        "Attachments": [
            {
                "Filename": "invoice.pdf",
                "ContentType": "application/pdf",
                "Content": pdf_b64,
            }
        ],
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
# Tests
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


def _run_handler(monkeypatch, payment: PaymentDetails, env: dict | None = None):
    """Run handle() with Resend mocked, webhook verification bypassed, and LLM stubbed."""
    env = env or {}
    base_env = {
        "RESEND_API_KEY": "test-resend",
        "OPENAI_API_KEY": "test-openai",
        "COMPANY_NAME": "Test Corp",
        "FROM_ADDRESS": "noreply@test.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }
    for k, v in {**base_env, **env}.items():
        monkeypatch.setenv(k, v)

    import os
    live_key = os.environ.get("OPENAI_API_KEY")
    use_live = live_key and not live_key.startswith("test-")

    if not use_live:
        import mail2pay.llm as llm_mod
        monkeypatch.setattr(llm_mod, "Extractor", _stub_extractor_class(payment))

    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock), \
         patch("handler.verify_webhook", return_value=True):
        import handler
        result = handler.handle(_make_event(_make_pdf_b64()), context=None)

    return result, resend_mock


def test_handler_returns_200(monkeypatch):
    payment = PaymentDetails(amount="99.00", iban="BE68539007547034", communication="TEST")
    result, _ = _run_handler(monkeypatch, payment)
    assert result["statusCode"] == 200


def test_handler_calls_resend_once(monkeypatch):
    payment = PaymentDetails(amount="99.00", iban="BE68539007547034", communication="TEST")
    _, resend_mock = _run_handler(monkeypatch, payment)
    resend_mock.assert_called_once()


def test_handler_sends_to_correct_address(monkeypatch):
    payment = PaymentDetails(amount="10.00", iban="BE68539007547034", communication="REF")
    _, resend_mock = _run_handler(monkeypatch, payment)
    call_args = resend_mock.call_args[0][0]
    assert call_args["to"] == ["sender@example.com"]


def test_handler_attaches_png(monkeypatch):
    payment = PaymentDetails(amount="25.50", iban="BE68539007547034", communication="X")
    _, resend_mock = _run_handler(monkeypatch, payment)
    call_args = resend_mock.call_args[0][0]
    attachments = call_args.get("attachments", [])
    assert attachments, "No attachments in email"
    raw = base64.b64decode(attachments[0]["content"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "Attachment is not a valid PNG"


def test_handler_no_attachments_returns_ok(monkeypatch):
    for k, v in {
        "RESEND_API_KEY": "r", "OPENAI_API_KEY": "o",
        "COMPANY_NAME": "C", "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    with patch("handler.verify_webhook", return_value=True):
        import handler
        event = {"body": json.dumps({"From": "a@b.com", "Attachments": []})}
        result = handler.handle(event, context=None)
    assert result["statusCode"] == 200


def test_handler_no_from_returns_ok(monkeypatch):
    for k, v in {
        "RESEND_API_KEY": "r", "OPENAI_API_KEY": "o",
        "COMPANY_NAME": "C", "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    with patch("handler.verify_webhook", return_value=True):
        import handler
        event = {"body": json.dumps({"Attachments": []})}
        result = handler.handle(event, context=None)
    assert result["statusCode"] == 200


def test_handler_invalid_signature_returns_ok(monkeypatch):
    """Requests with bad webhook signatures are dropped: 200 returned, Resend never called."""
    for k, v in {
        "RESEND_API_KEY": "r", "OPENAI_API_KEY": "o",
        "COMPANY_NAME": "C", "FROM_ADDRESS": "f@f.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock), \
         patch("handler.verify_webhook", return_value=False):
        import handler
        event = {"body": json.dumps({"From": "attacker@evil.com", "Attachments": []})}
        result = handler.handle(event, context=None)

    assert result["statusCode"] == 200
    resend_mock.assert_not_called()  # the security-critical assertion
