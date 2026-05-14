# Resend Webhook Attachment Fetch — Design

## Goal

Adapt the inbound `email.received` handler to Resend's current webhook contract:

- The webhook payload is nested under a top-level `data` object (`{type, created_at, data: {...}}`).
- Attachments in the webhook carry **metadata only** (id, filename, content_type, content_disposition, content_id). No `content` field is present.

To obtain the PDF bytes we must call Resend's Received Email **Attachments API**.
We'll use the Python SDK already installed (`resend==2.30.1`) which exposes
`resend.Emails.Receiving.Attachments.get(email_id, attachment_id)` returning a
signed `download_url` we then `GET` over HTTPS.

The webhook already includes each attachment's `id` inside `data.attachments[]`,
so we can skip the "list attachments" call and go straight to "get attachment".

## Data Flow (new)

1. Verify svix signature (unchanged).
2. Parse request body into a Pydantic `InboundWebhook` model.
3. Short-circuit with 200 if `type != "email.received"`.
4. Extract `email_id`, `from`, `attachments` from `webhook.data`.
5. `download.get_pdf_attachment(email_id, attachments)` →
   a. `pick_pdf_attachment(attachments)` picks first PDF by `content_type` /
      `.pdf` filename.
   b. `resend.Emails.Receiving.Attachments.get(email_id, att.id)` →
      `{download_url, expires_at, ...}`.
   c. `httpx.get(download_url, timeout=30)` with a 10 MB size cap → `bytes`.
6. `extract_pdf_text(pdf_bytes)` — text extraction (pdf module, now bytes-first).
7. Unchanged: LLM extract → QR generate → `Mailer.send_reply`.

Early-exit rules (each returns 200 + no-op):
- wrong event `type`;
- Pydantic `ValidationError` on the payload;
- no PDF attachment;
- Resend API / HTTP download failure;
- PDF parse failure.

## Proposed Changes

### `mail2pay/models.py` — add webhook models

```python
class WebhookAttachment(BaseModel):
    id: str
    filename: str | None = None
    content_type: str | None = None
    content_disposition: str | None = None
    content_id: str | None = None

class ReceivedEmailData(BaseModel):
    email_id: str
    from_: EmailStr = Field(alias="from")
    to: list[str] = []
    subject: str | None = None
    attachments: list[WebhookAttachment] = []
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

class InboundWebhook(BaseModel):
    type: str
    created_at: str | None = None
    data: ReceivedEmailData
    model_config = ConfigDict(extra="ignore")
```

### `mail2pay/download.py` — new module (single entry point)

```python
def pick_pdf_attachment(attachments: list[WebhookAttachment]) -> WebhookAttachment | None: ...

def get_pdf_attachment(
    email_id: str,
    attachments: list[WebhookAttachment],
) -> bytes | None:
    """Pick the first PDF attachment, fetch its signed URL, download and
    return the raw bytes. Returns None if no PDF attachment is present."""
```

Internals:
- `resend.Emails.Receiving.Attachments.get(email_id, att.id)` for the signed URL.
- `httpx.get(url, timeout=30)` with streaming, size-capped at 10 MB
  (`_MAX_PDF_BYTES`); raises on non-2xx or size overflow.

### `mail2pay/pdf.py` — simplify

- Drop `pick_pdf_attachment` (moved to `download.py`).
- Change `extract_pdf_text(base64_pdf: str) -> str` to
  `extract_pdf_text(pdf: bytes) -> str`. Drop the base64-decode step; size cap
  moves to the download module.

### `handler.py` — wire it up

- Parse body with `InboundWebhook.model_validate_json(event["body"])` inside a
  `try/except ValidationError`.
- Short-circuit on wrong event type.
- Call `download.get_pdf_attachment(data.email_id, data.attachments)`.
- Pass resulting `bytes` to `extract_pdf_text`.
- Reply-to address is `data.from_` (webhook guarantees bare email, no display name).

### `pyproject.toml`

- Add explicit `httpx` dependency (currently only transitive via `resend`).

### Tests

`tests/test_handler.py` — rewrite helpers and patches:
- `_make_event` emits the new envelope:
  ```json
  {"type":"email.received","data":{"email_id":"evt_1","from":"sender@example.com",
   "attachments":[{"id":"att_1","filename":"invoice.pdf","content_type":"application/pdf"}]}}
  ```
  No `content` field.
- `_run_handler` patches:
  - `resend.Emails.Receiving.Attachments.get` → `{"download_url":"https://signed/…","expires_at":"…"}`;
  - `mail2pay.download._download` (or `httpx.get`) → bytes from `_make_pdf_bytes()`.
- Keep existing assertions: 200, one `resend.Emails.send` call, correct `to`, PNG attachment.
- Add:
  - `test_handler_validation_error_returns_ok` — malformed body → 200, no send.
  - `test_handler_wrong_event_type_returns_ok` — `type:"email.sent"` → 200, no send.
  - `test_handler_attachment_download_failure_returns_ok` — `httpx.get` raises → 200, no send.
- Drop `test_handler_no_from_returns_ok` (pydantic now enforces `from`).

`tests/test_download.py` — new:
- `pick_pdf_attachment` picks by `content_type` and falls back to `.pdf` filename; returns None otherwise.
- `get_pdf_attachment` returns `None` when no PDF present.
- `get_pdf_attachment` calls `Attachments.get(email_id, att.id)` and returns
  bytes from the signed URL (both patched).
- Size cap: `_download` raises when response exceeds 10 MB.

## Verification

- `uv run ty check .` → 0 diagnostics.
- `uv run pytest` → green.

## Open Questions

1. Should we also validate that `att.content_type` returned by Resend
   matches `application/pdf` post-download, or trust webhook metadata?
   (Currently we trust metadata; propose keeping that.)
   -> fine
2. Timeout / size cap values — 30 s / 10 MB proposed; override via env vars?
   (Propose hardcoded for now; revisit if needed.)
   -> hard coded is fine
3. On retryable transport errors (timeouts, 5xx), do we want to return a
   non-200 so Resend retries, instead of silently dropping? Current SPEC is
   "always 200" — keep as-is unless told otherwise.
   -> return 500.  Make sure we log those.
