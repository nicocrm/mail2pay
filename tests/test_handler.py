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


def _make_event(
    from_addr: str = "sender@example.com",
    to_addr: str = "noreply@test.com",
    message_id: str | None = None,
    subject: str | None = None,
) -> dict:
    body: dict = {
        "type": "email.received",
        "data": {
            "email_id": "evt_1",
            "from": from_addr,
            "to": [to_addr],
            "attachments": [
                {
                    "id": "att_1",
                    "filename": "invoice.pdf",
                    "content_type": "application/pdf",
                }
            ],
        },
    }
    if message_id is not None:
        body["data"]["message_id"] = message_id
    if subject is not None:
        body["data"]["subject"] = subject
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

def _run_handler(
    monkeypatch,
    payment: PaymentDetails,
    env: dict | None = None,
    message_id: str | None = None,
    subject: str | None = None,
):
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
        result = handler.handle(
            _make_event(message_id=message_id, subject=subject), context=None
        )

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
                    "to": ["f@f.com"],
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
                    "to": ["f@f.com"],
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
        result = handler.handle(_make_event(to_addr="f@f.com"), context=None)

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
        event = {"body": json.dumps({"type": "email.received", "data": {"from": "attacker@evil.com", "to": ["f@f.com"], "email_id": "x", "attachments": []}})}
        result = handler.handle(event, context=None)

    assert result["statusCode"] == 200
    resend_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Tests – non-retryable failures trigger sender notification
# ---------------------------------------------------------------------------

def _run_handler_with_mailer_stub(
    monkeypatch,
    *,
    from_addr: str = "sender@example.com",
    message_id: str | None = None,
    subject: str | None = None,
    extractor_side_effect: Exception | None = None,
    qr_side_effect: Exception | None = None,
    pdf_side_effect: Exception | None = None,
    send_reply_side_effect: Exception | None = None,
    download_side_effect: Exception | None = None,
    send_error_reply_side_effect: Exception | None = None,
):
    """Run handle() with the Mailer singleton replaced by a MagicMock.

    Returns ``(result, mailer_mock)``. Failures are injected at whichever layer
    the caller names, driving the non-retryable except branches in handler.
    """
    for k, v in {
        "RESEND_API_KEY": "test-resend",
        "MISTRAL_API_KEY": "test-mistral",
        "FROM_ADDRESS": "noreply@test.com",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdHNlY3JldA==",
    }.items():
        monkeypatch.setenv(k, v)

    payment = PaymentDetails(
        beneficiary_name="Acme BV",
        amount="99.00",
        iban="BE68539007547034",
        communication="TEST",
    )

    class RaisingExtractor:
        def __init__(self, cfg, client=None):
            pass
        def extract(self, raw_text: str) -> PaymentDetails:
            if extractor_side_effect is not None:
                raise extractor_side_effect
            return payment

    import mail2pay.llm as llm_mod
    monkeypatch.setattr(llm_mod, "Extractor", RaisingExtractor)

    # Replace the Mailer class with one that yields a mock instance so we can
    # assert on send_reply / send_error_reply calls through the module cache.
    mailer_instance = MagicMock()
    if send_reply_side_effect is not None:
        mailer_instance.send_reply.side_effect = send_reply_side_effect
    if send_error_reply_side_effect is not None:
        mailer_instance.send_error_reply.side_effect = send_error_reply_side_effect

    import mail2pay.mailer as mailer_mod
    class StubMailer:
        def __init__(self, cfg):
            pass
        def __new__(cls, cfg):
            return mailer_instance
    monkeypatch.setattr(mailer_mod, "Mailer", StubMailer)

    attachments_get_mock = MagicMock(
        return_value={"download_url": "https://signed.example.com/invoice.pdf"}
    )
    if download_side_effect is not None:
        attachments_get_mock.side_effect = download_side_effect

    pdf_text_patcher = patch("handler.extract_pdf_text")
    qr_patcher = patch("handler.generate_qr_base64")

    with patch("resend.Emails.Receiving.Attachments.get", attachments_get_mock), \
         patch("mail2pay.download._download", return_value=_make_pdf_bytes()), \
         patch("handler.verify_webhook", return_value=True), \
         pdf_text_patcher as pdf_text_mock, \
         qr_patcher as qr_mock:

        if pdf_side_effect is not None:
            pdf_text_mock.side_effect = pdf_side_effect
        else:
            pdf_text_mock.return_value = "invoice text"

        if qr_side_effect is not None:
            qr_mock.side_effect = qr_side_effect
        else:
            qr_mock.return_value = "aGVsbG8="

        import handler
        result = handler.handle(_make_event(from_addr=from_addr, message_id=message_id, subject=subject), context=None)

    return result, mailer_instance


def test_extractor_failure_triggers_error_reply(monkeypatch):
    """AE1: LLM extraction failure → 200, send_error_reply called, send_reply not."""
    from pydantic import ValidationError
    # Trigger a real ValidationError on PaymentDetails.
    try:
        PaymentDetails(beneficiary_name="x", amount="0", iban="BE68539007547034", communication="")
    except ValidationError as exc:
        validation_error = exc

    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch, extractor_side_effect=validation_error
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_called_once()
    assert mailer.send_error_reply.call_args.args == ("sender@example.com",)
    mailer.send_reply.assert_not_called()


def test_pdf_too_large_triggers_error_reply(monkeypatch):
    """AE2: PDFTooLargeError → 200, send_error_reply called once."""
    from mail2pay.download import PDFTooLargeError
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch, download_side_effect=PDFTooLargeError("too big")
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_called_once()
    assert mailer.send_error_reply.call_args.args == ("sender@example.com",)
    mailer.send_reply.assert_not_called()


def test_qr_failure_triggers_error_reply(monkeypatch):
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch, qr_side_effect=RuntimeError("qr failed")
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_called_once()
    assert mailer.send_error_reply.call_args.args == ("sender@example.com",)


def test_pdf_parse_failure_triggers_error_reply(monkeypatch):
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch, pdf_side_effect=RuntimeError("parse failed")
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_called_once()
    assert mailer.send_error_reply.call_args.args == ("sender@example.com",)


def test_send_reply_failure_also_triggers_error_reply(monkeypatch):
    """When the success reply raises inside the outer try, the error reply still fires."""
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch, send_reply_side_effect=RuntimeError("boom")
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_called_once()
    assert mailer.send_error_reply.call_args.args == ("sender@example.com",)


def test_self_loop_suppresses_error_reply(monkeypatch):
    """AE3: from == FROM_ADDRESS → no error reply, still 200."""
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch,
        from_addr="noreply@test.com",  # matches FROM_ADDRESS
        qr_side_effect=RuntimeError("qr failed"),
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_not_called()


def test_no_reply_local_part_suppresses_error_reply(monkeypatch):
    """AE5: from=no-reply@... → no error reply."""
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch,
        from_addr="no-reply@acme.com",
        qr_side_effect=RuntimeError("qr failed"),
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_not_called()


def test_error_reply_send_failure_is_swallowed(monkeypatch):
    """AE6: send_error_reply raises → handler still returns 200, no 500."""
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch,
        qr_side_effect=RuntimeError("qr failed"),
        send_error_reply_side_effect=RuntimeError("transport down"),
    )
    assert result["statusCode"] == 200
    mailer.send_error_reply.assert_called_once()
    assert mailer.send_error_reply.call_args.args == ("sender@example.com",)


def test_retryable_download_error_does_not_trigger_error_reply(monkeypatch):
    """Download-transport failures remain retryable (500) — no error reply."""
    import httpx
    result, mailer = _run_handler_with_mailer_stub(
        monkeypatch, download_side_effect=httpx.ConnectError("timeout")
    )
    assert result["statusCode"] == 500
    mailer.send_error_reply.assert_not_called()
    mailer.send_reply.assert_not_called()


# ---------------------------------------------------------------------------
# Tests – threading kwargs propagated from webhook data
# ---------------------------------------------------------------------------

def test_send_reply_receives_threading_kwargs(monkeypatch):
    """Success path: mailer.send_reply called with in_reply_to and original_subject."""
    payment = PaymentDetails(
        beneficiary_name="Acme BV", amount="10.00",
        iban="BE68539007547034", communication="REF"
    )
    _, mailer = _run_handler_with_mailer_stub(
        monkeypatch,
        message_id="<fwd123@gmail.com>",
        subject="Fwd: Facture 42",
    )
    mailer.send_reply.assert_called_once()
    kwargs = mailer.send_reply.call_args.kwargs
    assert kwargs.get("in_reply_to") == "<fwd123@gmail.com>"
    assert kwargs.get("original_subject") == "Fwd: Facture 42"


def test_send_error_reply_receives_threading_kwargs_on_extractor_failure(monkeypatch):
    """Error path (extractor): mailer.send_error_reply called with threading kwargs."""
    from pydantic import ValidationError
    try:
        PaymentDetails(beneficiary_name="x", amount="0", iban="BE68539007547034", communication="")
    except ValidationError as exc:
        validation_error = exc

    _, mailer = _run_handler_with_mailer_stub(
        monkeypatch,
        extractor_side_effect=validation_error,
        message_id="<fwd456@gmail.com>",
        subject="Fwd: Invoice",
    )
    mailer.send_error_reply.assert_called_once()
    kwargs = mailer.send_error_reply.call_args.kwargs
    assert kwargs.get("in_reply_to") == "<fwd456@gmail.com>"
    assert kwargs.get("original_subject") == "Fwd: Invoice"


def test_send_error_reply_receives_threading_kwargs_on_pdf_too_large(monkeypatch):
    """Error path (PDFTooLargeError): send_error_reply called with threading kwargs."""
    from mail2pay.download import PDFTooLargeError
    _, mailer = _run_handler_with_mailer_stub(
        monkeypatch,
        download_side_effect=PDFTooLargeError("too big"),
        message_id="<fwd789@gmail.com>",
        subject="Fwd: Big Invoice",
    )
    mailer.send_error_reply.assert_called_once()
    kwargs = mailer.send_error_reply.call_args.kwargs
    assert kwargs.get("in_reply_to") == "<fwd789@gmail.com>"
    assert kwargs.get("original_subject") == "Fwd: Big Invoice"


def test_send_reply_no_threading_when_message_id_absent(monkeypatch):
    """No message_id in webhook → in_reply_to=None passed to send_reply."""
    _, mailer = _run_handler_with_mailer_stub(monkeypatch)
    mailer.send_reply.assert_called_once()
    kwargs = mailer.send_reply.call_args.kwargs
    assert kwargs.get("in_reply_to") is None
