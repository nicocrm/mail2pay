"""Outbound email via Resend."""
import resend

from .config import Config


class Mailer:
    """Thin wrapper around Resend that owns its own API key and from-address.

    Instantiated once at cold-start and cached in handler._mailer so the
    resend.api_key global is set exactly once rather than on every request.
    """

    def __init__(self, cfg: Config) -> None:
        resend.api_key = cfg.resend_api_key
        self._from = cfg.from_address

    def send_reply(self, to: str, qr_b64: str) -> None:
        """Send a reply email with the EPC QR code PNG attached."""
        resend.Emails.send({
            "from": self._from,
            "to": [to],
            "subject": "Your payment QR code",
            "html": (
                "<p>Please find your EPC payment QR code attached.</p>"
                "<p>Scan it with your banking app to initiate the payment.</p>"
            ),
            "attachments": [
                {
                    "filename": "payment_qr.png",
                    "content": qr_b64,
                }
            ],
        })
