"""Outbound email via Resend."""
import resend

from .config import Config
from .models import PaymentDetails


class Mailer:
    """Thin wrapper around Resend that owns its own API key and from-address.

    Instantiated once at cold-start and cached in handler._mailer so the
    resend.api_key global is set exactly once rather than on every request.
    """

    def __init__(self, cfg: Config) -> None:
        resend.api_key = cfg.resend_api_key
        self._from = cfg.from_address

    def send_reply(self, to: str, qr_b64: str, payment: PaymentDetails) -> None:
        """Send a reply email with the EPC QR code PNG attached."""
        resend.Emails.send({
            "from": self._from,
            "to": [to],
            "subject": "Your payment QR code",
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
        })

    def send_error_reply(self, to: str) -> None:
        """Send a generic "we couldn't process your invoice" reply.

        Intentionally does not expose error-type detail, extracted fields, or
        any internal identifiers (R2). Exceptions from the underlying transport
        propagate — the caller owns the log-and-swallow policy (R9).
        """
        resend.Emails.send({
            "from": self._from,
            "to": [to],
            "subject": "We couldn't process your invoice",
            "html": (
                "<p>Thanks for your email. We received it but were unable to "
                "generate a payment QR code from the attachment.</p>"
                "<p>Please try again with a clearer invoice, or reply to this "
                "email if you need help.</p>"
            ),
        })
