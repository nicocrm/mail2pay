from unittest.mock import patch

import pytest

from mail2pay.config import Config
from mail2pay.mailer import Mailer


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
