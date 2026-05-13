import json
import logging
from typing import Any

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
            "COMPANY_NAME, FROM_ADDRESS, and RESEND_WEBHOOK_SECRET are set."
        )
        raise

    _cfg = cfg
    _extractor = Extractor(_cfg)
    _mailer = Mailer(_cfg)  # also sets resend.api_key


def handle(event, context):
    _bootstrap()

    if not verify_webhook(event, _cfg.webhook_secret):
        logger.warning("Webhook signature verification failed – ignoring request.")
        return {"statusCode": 200, "body": "ok"}

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.error("Failed to parse request body: %s", exc)
        return {"statusCode": 200, "body": "bad request"}

    from_addr = body.get("from")
    attachments = body.get("attachments") or []

    if not from_addr:
        logger.info("No From address – ignoring.")
        return {"statusCode": 200, "body": "ok"}

    if not attachments:
        logger.info("No attachments – ignoring.")
        return {"statusCode": 200, "body": "ok"}

    try:
        from mail2pay.pdf import extract_pdf_text, pick_pdf_attachment
        from mail2pay.qr import generate_qr_base64

        att = pick_pdf_attachment(attachments)
        if att is None:
            logger.info("No PDF attachment found – ignoring.")
            return {"statusCode": 200, "body": "ok"}

        pdf_b64 = att.get("content") or ""
        raw_text = extract_pdf_text(pdf_b64)
        logger.info("Extracted %d chars of text from PDF.", len(raw_text))

        payment = _extractor.extract(raw_text)
        logger.info("Payment details: amount=%s iban=%s", payment.amount, payment.iban)

        qr_b64 = generate_qr_base64(payment, _cfg.company_name)
        logger.info("QR code generated (%d bytes base64).", len(qr_b64))

        _mailer.send_reply(from_addr, qr_b64)
        logger.debug("Reply sent to %s.", from_addr)  # PII – debug only

    except Exception:
        logger.exception("mail2pay failure")

    return {"statusCode": 200, "body": "ok"}
