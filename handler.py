import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level cache – populated on first invocation (cold-start optimisation).
_cfg = None
_extractor = None


def _bootstrap():
    global _cfg, _extractor
    if _cfg is None:
        from mail2pay.config import get_config
        from mail2pay.llm import Extractor
        import resend

        _cfg = get_config()
        _extractor = Extractor(_cfg)
        resend.api_key = _cfg.resend_api_key  # set once at bootstrap


def _verify_webhook(event: dict, secret: str) -> bool:
    """Verify Resend webhook signature via svix."""
    from svix.webhooks import Webhook, WebhookVerificationError

    headers = event.get("headers") or {}
    # Normalise to lowercase keys (Scaleway may vary casing)
    headers = {k.lower(): v for k, v in headers.items()}
    payload = (event.get("body") or "").encode()

    wh = Webhook(secret)
    try:
        wh.verify(payload, headers)
        return True
    except WebhookVerificationError:
        return False


def handle(event, context):
    _bootstrap()
    assert _cfg is not None and _extractor is not None

    if not _verify_webhook(event, _cfg.webhook_secret):
        logger.warning("Webhook signature verification failed – ignoring request.")
        return {"statusCode": 200, "body": "ok"}

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.error("Failed to parse request body: %s", exc)
        return {"statusCode": 200, "body": "bad request"}

    from_addr = body.get("From") or body.get("from")
    attachments = body.get("Attachments") or body.get("attachments") or []

    if not from_addr:
        logger.info("No From address – ignoring.")
        return {"statusCode": 200, "body": "ok"}

    if not attachments:
        logger.info("No attachments – ignoring.")
        return {"statusCode": 200, "body": "ok"}

    try:
        from mail2pay.pdf import extract_pdf_text, pick_pdf_attachment
        from mail2pay.qr import generate_qr_base64
        from mail2pay.mailer import send_reply

        att = pick_pdf_attachment(attachments)
        if att is None:
            logger.info("No PDF attachment found – ignoring.")
            return {"statusCode": 200, "body": "ok"}

        pdf_b64 = att.get("Content") or att.get("content", "")
        raw_text = extract_pdf_text(pdf_b64)
        logger.info("Extracted %d chars of text from PDF.", len(raw_text))

        payment = _extractor.extract(raw_text)
        logger.info("Payment details: amount=%s iban=%s", payment.amount, payment.iban)

        qr_b64 = generate_qr_base64(payment, _cfg.company_name)
        logger.info("QR code generated (%d bytes base64).", len(qr_b64))

        send_reply(_cfg, from_addr, qr_b64)
        logger.info("Reply sent to %s.", from_addr)

    except Exception:
        logger.exception("mail2pay failure")

    return {"statusCode": 200, "body": "ok"}
