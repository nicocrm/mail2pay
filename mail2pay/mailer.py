"""Outbound email via Resend."""
import re
from typing import cast

import resend

from .config import Config
from .models import PaymentDetails


def _threading_payload(
    in_reply_to: str | None,
    original_subject: str | None,
    default_subject: str,
) -> tuple[str, dict[str, str]]:
    """Return (subject, headers) for a threaded reply.

    - subject: "Re: " + stripped original (strip one leading "Re:" case-
      insensitively; keep "Fwd:"). Falls back to default_subject when
      original is missing/empty.
    - headers: {"In-Reply-To": <id>, "References": <id>} when in_reply_to
      is provided; empty dict otherwise.
    """
    if original_subject and original_subject.strip():
        stripped = re.sub(r"(?i)^Re:\s*", "", original_subject.strip())
        subject = f"Re: {stripped}"
    else:
        subject = default_subject

    if in_reply_to:
        headers: dict[str, str] = {
            "In-Reply-To": in_reply_to,
            "References": in_reply_to,
        }
    else:
        headers = {}

    return subject, headers


class Mailer:
    """Thin wrapper around Resend that owns its own API key and from-address.

    Instantiated once at cold-start and cached in handler._mailer so the
    resend.api_key global is set exactly once rather than on every request.
    """

    def __init__(self, cfg: Config) -> None:
        resend.api_key = cfg.resend_api_key
        self._from = cfg.from_address

    def send_reply(
        self,
        to: str,
        qr_b64: str,
        payment: PaymentDetails,
        *,
        in_reply_to: str | None = None,
        original_subject: str | None = None,
    ) -> None:
        """Send a reply email with the EPC QR code PNG attached."""
        subject, headers = _threading_payload(
            in_reply_to, original_subject, "Your payment QR code"
        )
        payload: dict = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "html": (
                "<p>Please find your EPC payment QR code attached.</p>"
                f"<p>This QR code initiates a payment of "
                f"<strong>€{payment.amount}</strong> "
                f"to <strong>{payment.beneficiary_name}</strong>.</p>"
                "<p>Scan it with your banking app to complete the payment.</p>"
            ),
            "attachments": [
                {
                    "filename": "payment_qr.png",
                    "content": qr_b64,
                }
            ],
        }
        if headers:
            payload["headers"] = headers
        resend.Emails.send(cast(resend.Emails.SendParams, payload))

    def send_error_reply(
        self,
        to: str,
        *,
        in_reply_to: str | None = None,
        original_subject: str | None = None,
    ) -> None:
        """Send a generic "we couldn't process your invoice" reply.

        Intentionally does not expose error-type detail, extracted fields, or
        any internal identifiers (R2). Exceptions from the underlying transport
        propagate — the caller owns the log-and-swallow policy (R9).
        """
        subject, headers = _threading_payload(
            in_reply_to, original_subject, "We couldn't process your invoice"
        )
        payload: dict = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "html": (
                "<p>Thanks for your email. We received it but were unable to "
                "generate a payment QR code from the attachment.</p>"
                "<p>Please try again with a clearer invoice, or reply to this "
                "email if you need help.</p>"
            ),
        }
        if headers:
            payload["headers"] = headers
        resend.Emails.send(cast(resend.Emails.SendParams, payload))
