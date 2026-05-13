"""Webhook signature verification for inbound Resend events (via svix)."""
import logging

from svix.webhooks import Webhook

logger = logging.getLogger(__name__)


def verify_webhook(event: dict, secret: str) -> bool:
    """Return True if the svix signature on *event* is valid.

    Catches all exceptions so that malformed headers, an invalid secret
    format, or an unexpected svix error never propagate as a 500 — they
    are logged as a warning and treated as verification failure.
    """
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    payload = (event.get("body") or "").encode()

    try:
        Webhook(secret).verify(payload, headers)
        return True
    except Exception as exc:  # WebhookVerificationError, KeyError, ValueError, …
        logger.warning("Webhook verification failed: %s", exc)
        return False
