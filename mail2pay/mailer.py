import resend

from .config import Config


def send_reply(cfg: Config, to: str, qr_b64: str) -> None:
    """Send a reply email with the EPC QR code attached.

    Note: resend.api_key must be set before calling this function.
    It is initialised once in handler._bootstrap().
    """
    resend.Emails.send({
        "from": cfg.from_address,
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
