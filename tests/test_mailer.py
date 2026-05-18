from unittest.mock import patch

import pytest

from mail2pay.config import Config
from mail2pay.mailer import Mailer, _threading_payload
from mail2pay.models import PaymentDetails


@pytest.fixture
def mailer(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MISTRAL_API_KEY", "ms_test")
    monkeypatch.setenv("FROM_ADDRESS", "bot@mail2pay.example")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_test")
    return Mailer(Config())  # ty: ignore[missing-argument]


# --- send_error_reply ------------------------------------------------------

def test_send_error_reply_invokes_resend_once(mailer):
    with patch("mail2pay.mailer.resend.Emails.send") as send:
        mailer.send_error_reply("user@example.com")

    assert send.call_count == 1
    payload = send.call_args.args[0]
    assert payload["from"] == "bot@mail2pay.example"
    assert payload["to"] == ["user@example.com"]
    assert payload["subject"] == "We couldn't process your invoice"
    assert "html" in payload
    # No attachments on the error reply.
    assert "attachments" not in payload or not payload["attachments"]


def test_send_error_reply_body_does_not_leak_internals(mailer):
    with patch("mail2pay.mailer.resend.Emails.send") as send:
        mailer.send_error_reply("user@example.com")

    body = send.call_args.args[0]["html"].lower()
    # R2: don't leak internal error-type detail or extracted fields.
    for forbidden in ("iban", "mistral", "traceback", "beneficiary", "amount"):
        assert forbidden not in body, f"error body leaked internal term {forbidden!r}"


def test_send_error_reply_propagates_transport_error(mailer):
    with patch(
        "mail2pay.mailer.resend.Emails.send", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError, match="boom"):
            mailer.send_error_reply("user@example.com")


# --- _threading_payload ----------------------------------------------------

def test_threading_payload_with_in_reply_to():
    subject, headers = _threading_payload(
        "<abc@mail.example>", "Fwd: Facture 42", "Your payment QR code"
    )
    assert subject == "Re: Fwd: Facture 42"
    assert headers == {
        "In-Reply-To": "<abc@mail.example>",
        "References": "<abc@mail.example>",
    }


def test_threading_payload_no_double_re_prefix():
    subject, headers = _threading_payload(
        "<abc@mail.example>", "Re: Some invoice", "Your payment QR code"
    )
    assert subject == "Re: Some invoice"


def test_threading_payload_re_case_insensitive():
    subject, _ = _threading_payload(
        "<abc@mail.example>", "RE:  Some invoice", "default"
    )
    assert subject == "Re: Some invoice"


def test_threading_payload_no_in_reply_to_no_headers():
    subject, headers = _threading_payload(None, "Fwd: X", "Your payment QR code")
    assert headers == {}
    assert subject == "Re: Fwd: X"


def test_threading_payload_missing_subject_uses_default():
    subject, headers = _threading_payload(None, None, "default subject")
    assert subject == "default subject"
    assert headers == {}


def test_threading_payload_empty_subject_uses_default():
    subject, _ = _threading_payload("<x@y>", "  ", "fallback")
    assert subject == "fallback"


# --- send_reply with threading args ----------------------------------------

def test_send_reply_includes_threading_headers(mailer):
    payment = PaymentDetails(
        beneficiary_name="Acme", amount="10.00",
        iban="BE68539007547034", communication="REF"
    )
    with patch("mail2pay.mailer.resend.Emails.send") as send:
        mailer.send_reply(
            "user@example.com",
            "aGVsbG8=",
            payment,
            in_reply_to="<fwd123@gmail.com>",
            original_subject="Fwd: Facture 99",
        )

    payload = send.call_args.args[0]
    assert payload["subject"] == "Re: Fwd: Facture 99"
    assert payload["headers"] == {
        "In-Reply-To": "<fwd123@gmail.com>",
        "References": "<fwd123@gmail.com>",
    }


def test_send_reply_no_threading_args_no_headers_key(mailer):
    payment = PaymentDetails(
        beneficiary_name="Acme", amount="10.00",
        iban="BE68539007547034", communication="REF"
    )
    with patch("mail2pay.mailer.resend.Emails.send") as send:
        mailer.send_reply("user@example.com", "aGVsbG8=", payment)

    payload = send.call_args.args[0]
    assert "headers" not in payload
    assert payload["subject"] == "Your payment QR code"


# --- send_error_reply with threading args ----------------------------------

def test_send_error_reply_includes_threading_headers(mailer):
    with patch("mail2pay.mailer.resend.Emails.send") as send:
        mailer.send_error_reply(
            "user@example.com",
            in_reply_to="<fwd456@gmail.com>",
            original_subject="Fwd: Invoice",
        )

    payload = send.call_args.args[0]
    assert payload["subject"] == "Re: Fwd: Invoice"
    assert payload["headers"] == {
        "In-Reply-To": "<fwd456@gmail.com>",
        "References": "<fwd456@gmail.com>",
    }


def test_send_error_reply_no_threading_args_no_headers_key(mailer):
    with patch("mail2pay.mailer.resend.Emails.send") as send:
        mailer.send_error_reply("user@example.com")

    payload = send.call_args.args[0]
    assert "headers" not in payload
    assert payload["subject"] == "We couldn't process your invoice"
