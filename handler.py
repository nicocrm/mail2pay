import logging
from typing import Any

from pydantic import ValidationError

from mail2pay.download import PDFTooLargeError, get_pdf_attachment
from mail2pay.loop_guard import should_send_error_reply
from mail2pay.models import InboundWebhook
from mail2pay.pdf import extract_pdf_text
from mail2pay.qr import generate_qr_base64
from mail2pay.webhook import verify_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level cache – populated on first invocation (cold-start optimisation).
_cfg: Any = None
_extractor: Any = None
_mailer: Any = None


def _bootstrap() -> None:
    """Initialise shared singletons on the first request.

    Intentionally fail loud: if required env vars are absent the exception
    propagates, Scaleway returns a 500, and the misconfiguration is visible
    immediately in logs rather than being silently swallowed.
    """
    global _cfg, _extractor, _mailer
    if _cfg is not None:
        return

    from mail2pay.config import get_config
    from mail2pay.llm import Extractor
    from mail2pay.mailer import Mailer

    try:
        cfg = get_config()
    except Exception:
        logger.exception(
            "Fatal: failed to load Config – ensure RESEND_API_KEY, MISTRAL_API_KEY, "
            "FROM_ADDRESS, and RESEND_WEBHOOK_SECRET are set."
        )
        raise

    _cfg = cfg
    _extractor = Extractor(_cfg)
    _mailer = Mailer(_cfg)  # also sets resend.api_key


def _notify_sender_of_failure(
    from_addr: str,
    email_id: str,
    *,
    message_id: str | None = None,
    subject: str | None = None,
) -> None:
    """Send a generic error-reply email unless loop-prevention rules suppress it.

    Failures sending the error reply itself are logged and swallowed (R9) — we
    do not try to email about an email failure, retry, or escalate to 500.
    """
    send, reason = should_send_error_reply(from_addr, _cfg.from_address)
    if not send:
        logger.info(
            "Suppressing error reply email_id=%s reason=%s", email_id, reason
        )
        return

    try:
        _mailer.send_error_reply(
            from_addr,
            in_reply_to=message_id,
            original_subject=subject,
        )
    except Exception:
        logger.exception("Failed to send error reply email_id=%s", email_id)


def handle(event, context):
    _bootstrap()

    if not verify_webhook(event, _cfg.webhook_secret):
        logger.warning("Webhook signature verification failed – ignoring request.")
        return {"statusCode": 200, "body": "ok"}

    body = event.get("body") or "{}"

    try:
        webhook = InboundWebhook.model_validate_json(body)
    except ValidationError as exc:
        logger.error("Webhook payload validation error: %s", exc)
        return {"statusCode": 200, "body": "ok"}

    if webhook.type != "email.received":
        logger.info("Ignoring event type %r", webhook.type)
        return {"statusCode": 200, "body": "ok"}

    data = webhook.data
    from_addr = str(data.from_)

    # Verify email was addressed to our inbox
    if not data.to or _cfg.from_address.lower() not in [addr.lower() for addr in data.to]:
        logger.info(
            "Email not addressed to configured inbox (from=%s, to=%s) – ignoring.",
            from_addr,
            data.to,
        )
        return {"statusCode": 200, "body": "ok"}

    if not data.attachments:
        logger.info("No attachments – ignoring.")
        return {"statusCode": 200, "body": "ok"}

    # --- Transport / Resend API call (retryable → 500) ---
    try:
        pdf_bytes = get_pdf_attachment(data.email_id, data.attachments)
    except PDFTooLargeError:
        logger.warning(
            "PDF attachment too large for email_id=%s – non-retryable, returning 200",
            data.email_id,
        )
        _notify_sender_of_failure(
            from_addr,
            data.email_id,
            message_id=data.message_id,
            subject=data.subject,
        )
        return {"statusCode": 200, "body": "ok"}
    except Exception:
        logger.exception(
            "Failed to fetch PDF attachment for email_id=%s – retryable, returning 500",
            data.email_id,
        )
        return {"statusCode": 500, "body": "error"}

    if pdf_bytes is None:
        logger.info("No PDF attachment found – ignoring.")
        return {"statusCode": 200, "body": "ok"}

    # --- Non-retryable processing steps (PDF parse, LLM, QR, send) ---
    try:
        raw_text = extract_pdf_text(pdf_bytes)
        logger.info("Extracted %d chars of text from PDF.", len(raw_text))

        payment = _extractor.extract(raw_text)
        logger.info("Payment details: amount=%s iban=%s", payment.amount, payment.iban)

        qr_b64 = generate_qr_base64(payment)
        logger.info("QR code generated (%d bytes base64).", len(qr_b64))

        _mailer.send_reply(
            from_addr,
            qr_b64,
            payment,
            in_reply_to=data.message_id,
            original_subject=data.subject,
        )
        logger.debug("Reply sent to %s.", from_addr)  # PII – debug only

    except Exception:
        logger.exception("mail2pay processing failure")
        _notify_sender_of_failure(
            from_addr,
            data.email_id,
            message_id=data.message_id,
            subject=data.subject,
        )

    return {"statusCode": 200, "body": "ok"}
