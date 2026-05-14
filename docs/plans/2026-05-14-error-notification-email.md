---
date: 2026-05-14
topic: error-notification-email
status: active
origin: docs/brainstorms/2026-05-14-error-notification-email-requirements.md
---

# feat: Error notification email on non-retryable failures

## Summary

When mail2pay's processing pipeline fails non-retryably, send the original sender a short generic reply so they know their invoice was received but couldn't be processed. Guard against the most common email loops (self-loops and no-reply senders). Handler still returns HTTP 200 for non-retryable errors.

---

## Problem Frame

Non-retryable failures (`PDFTooLargeError`, PDF parse failure, LLM extraction/validation failure, QR generation failure) are currently logged and silently return 200. Senders have no visibility into failure. The origin doc (see origin: `docs/brainstorms/2026-05-14-error-notification-email-requirements.md`) resolves WHAT to build; this plan resolves HOW.

---

## Requirements Trace

Carried forward from origin (`R1`–`R10`, `AE1`–`AE6`). See origin for full text. Summary:

- **R1–R4** — reply path: generic message via existing mailer on all non-retryable failures.
- **R5, R7, R8** — loop prevention: skip when sender == `FROM_ADDRESS` or sender local-part matches no-reply patterns. Log suppression.
- **R9** — error-reply transport failure logged and swallowed; return 200.
- **R10** — original success-reply failure behavior unchanged.

**R6 (Auto-Submitted / Precedence header suppression) is deferred** — see Scope Boundaries. Resend's `email.received` webhook does not include headers, and fetching them would require an extra API call per request for a suppression rule whose forwarding by Resend is unconfirmed. R5 + R7 cover the dominant loop sources without that cost.

---

## Key Technical Decisions

- **New module `mail2pay/loop_guard.py`** with a pure `should_send_error_reply(from_addr: str, self_from: str) -> tuple[bool, str | None]` returning `(send, suppression_reason)`. Testable in isolation; keeps handler linear.
- **New method `Mailer.send_error_reply(to: str)`** rather than overloading `send_reply`. One concern per method, no optional-attachment branching, matches the existing single-purpose style of `send_reply`.
- **No-reply local-part regex**: case-insensitive match on local-part (before `@`) against `^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)$`. `mailer-daemon`/`postmaster` added because bounce-handler addresses are a common loop source and cheap to cover while we're here.
- **Wire-in points in `handler.py`**: (a) the `except PDFTooLargeError` branch, (b) the outer `except Exception` around the non-retryable processing block (PDF parse / LLM / QR / original send). **Do not** call `send_error_reply` from inside the original `Mailer.send_reply` failure path — R10 keeps that behavior unchanged, and sending an error reply about a failed original reply would retry the same transport that just failed.
- **Error-reply transport failures**: wrap the `send_error_reply` call in its own `try/except Exception: logger.exception(...)` — never escalate to 500 (R9).
- **No changes to `ReceivedEmailData` or `download.py`.** No extra Resend API calls.
- **No new env vars, no new dependencies.**

---

## Affected Files

- `mail2pay/mailer.py` — add `send_error_reply`.
- `mail2pay/loop_guard.py` — new module.
- `handler.py` — call guard + `send_error_reply` on non-retryable failures.
- `tests/test_mailer.py` — new file, covers `send_error_reply`.
- `tests/test_loop_guard.py` — new file.
- `tests/test_handler.py` — extend to cover new failure paths and suppressions.

---

## Implementation Units

### U1. Loop guard module

- **Goal**: Decide whether an error reply is safe to send, centralizing R5/R7 logic with an explicit suppression reason for logging (R8).
- **Requirements**: R5, R7, R8 (origin); AE3, AE5.
- **Dependencies**: none.
- **Files**: `mail2pay/loop_guard.py`, `tests/test_loop_guard.py`.
- **Approach**:
  - Single pure function `should_send_error_reply(from_addr: str, self_from: str) -> tuple[bool, str | None]`.
  - Returns `(False, "<reason>")` when suppressed; `(True, None)` otherwise.
  - Suppression reasons: `"self_loop"`, `"no_reply_local_part"`.
  - Case-insensitive email compare on full addresses (both sides lowercased).
  - No-reply local-part regex: `re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)$", re.IGNORECASE)` matched against the part before the last `@`.
- **Technical design** *(directional; not implementation spec)*:
  ```
  def should_send_error_reply(from_addr, self_from):
      if from_addr.lower() == self_from.lower(): return False, "self_loop"
      local = from_addr.rsplit("@", 1)[0]
      if NO_REPLY_RE.match(local): return False, "no_reply_local_part"
      return True, None
  ```
- **Test scenarios**:
  - Happy: ordinary `sender@example.com` → `(True, None)`.
  - **Covers AE3.** Sender equals `self_from` (any casing) → `(False, "self_loop")`.
  - **Covers AE5.** `from=no-reply@x`, `noreply@x`, `do-not-reply@x`, `DoNotReply@x`, `mailer-daemon@x`, `postmaster@x` → `(False, "no_reply_local_part")`.
  - Edge: sender local-part `notifications@x` (not in allow-list) → not suppressed.
  - Edge: malformed `from_addr` without `@` — does not crash; local-part rule applied to the whole string (acceptable; upstream `EmailStr` already validates format).
- **Verification**: `uv run ty check .` 0 diagnostics; `uv run pytest tests/test_loop_guard.py` passes.

### U2. `Mailer.send_error_reply`

- **Goal**: Emit the generic error reply via the existing Resend transport.
- **Requirements**: R1, R2, R3, R4 (origin).
- **Dependencies**: none.
- **Files**: `mail2pay/mailer.py`, `tests/test_mailer.py`.
- **Approach**:
  - New method `send_error_reply(self, to: str) -> None` that calls `resend.Emails.send` with the same `from`, no attachments.
  - **Subject**: `"We couldn't process your invoice"`.
  - **Body (html)**: two short paragraphs. Para 1: we received your email but couldn't extract payment details from the PDF. Para 2: please try again with a clearer PDF or a different attachment. No error-type detail, no extracted fields, no stack trace (R2).
  - Do not catch exceptions inside the method — the caller owns R9's "log and swallow" policy. This keeps the method symmetric with `send_reply`.
- **Patterns to follow**: `Mailer.send_reply` shape in `mail2pay/mailer.py`.
- **Test scenarios**:
  - Happy: `send_error_reply("user@example.com")` invokes `resend.Emails.send` once with `from=self._from`, `to=["user@example.com"]`, expected subject, an `html` body, and no `attachments` key (or empty list).
  - Error path: when `resend.Emails.send` raises, the exception propagates (caller handles).
  - Assert body does not mention "IBAN", "PDF", "Mistral", or any internal field names (R2 leakage guard).
- **Verification**: `uv run pytest tests/test_mailer.py` passes.

### U3. Wire error reply into handler

- **Goal**: Trigger `send_error_reply` (through the loop guard) on every non-retryable failure path, while preserving current retryable/non-retryable status-code behavior.
- **Requirements**: R1, R8, R9, R10; AE1, AE2, AE6.
- **Dependencies**: U1, U2.
- **Files**: `handler.py`, `tests/test_handler.py`.
- **Approach**:
  - Add a small private helper `_notify_sender_of_failure(from_addr: str, email_id: str) -> None` in `handler.py` that:
    1. Calls `should_send_error_reply(from_addr, _cfg.from_address)`.
    2. On suppression, logs `logger.info("Suppressing error reply email_id=%s reason=%s", email_id, reason)` and returns.
    3. Otherwise calls `_mailer.send_error_reply(from_addr)` inside its own `try/except Exception: logger.exception("Failed to send error reply email_id=%s", email_id)`.
  - Call sites:
    - Inside `except PDFTooLargeError:` branch, before `return {"statusCode": 200, ...}`.
    - Inside the outer `except Exception:` around the PDF parse / LLM / QR / original `send_reply` block, before the existing final `return`.
  - **Do not** call it in the download-transport `except Exception` branch that returns 500 (that path is retryable, R10-style reasoning).
  - **Do not** call it in the webhook-signature / validation / `type != "email.received"` / no-attachments / no-PDF branches — those are not failures from the sender's perspective.
- **Execution note**: Extend `tests/test_handler.py` test-first — the suppressions are easy to get wrong; locking them in before touching the handler reduces regression risk.
- **Patterns to follow**: existing `handler.py` error-branch structure; existing test mocking of `_mailer` and `_extractor` in `tests/test_handler.py`.
- **Test scenarios**:
  - **Covers AE1.** LLM extraction raises `ValidationError`: handler returns 200, `_mailer.send_error_reply` called once with the sender address, `send_reply` not called.
  - **Covers AE2.** `get_pdf_attachment` raises `PDFTooLargeError`: handler returns 200, `send_error_reply` called once.
  - QR generation raises: handler returns 200, `send_error_reply` called once.
  - PDF text extraction raises: handler returns 200, `send_error_reply` called once.
  - Original `send_reply` raises inside the outer try block: handler returns 200, `send_error_reply` called once (the outer except catches it). Documented consequence of sharing the outer try; acceptable because the error-reply path uses the same transport anyway and will likely also fail harmlessly.
  - **Covers AE3.** `from == FROM_ADDRESS` + forced failure: `send_error_reply` NOT called; suppression log emitted; handler returns 200.
  - **Covers AE5.** `from=no-reply@acme.com` + forced failure: `send_error_reply` NOT called.
  - **Covers AE6.** `_mailer.send_error_reply` raises: handler returns 200, exception logged, no 500.
  - Retryable path unchanged: download transport error still returns 500, `send_error_reply` NOT called.
  - Non-failure short-circuit paths unchanged: bad signature, non-`email.received` event, no attachments, no PDF — `send_error_reply` NOT called, 200 returned.
- **Verification**: `uv run ty check .` 0 diagnostics; `uv run pytest` full suite passes.

---

## System-Wide Impact

- **Outbound volume**: One additional email per non-retryable failure, minus suppressions. On current volumes negligible; Resend rate limits are the backstop.
- **Observability**: New log lines — one suppression-info log per skip, one exception log per error-reply transport failure.

---

## Scope Boundaries

Carried from origin. See origin doc for full text.

### Deferred to Follow-Up Work

- **R6 (Auto-Submitted / Precedence header suppression)** — not implemented in v1. Rationale: Resend's `email.received` webhook does not expose headers, and the retrieve-received-email endpoint's curated `headers` dict is not documented to include `Auto-Submitted`/`Precedence`. Implementing R6 would add a Resend API call per request for a suppression rule whose payload may be stripped. If loops from auto-responders are observed in practice, revisit by either (a) fetching the received email and checking its `headers` dict, or (b) fetching `raw.download_url` and parsing headers from the raw email.

### Outside this plan (non-goals)

- Error-specific message variants; echoing partial extraction; per-sender rate limiting; localization; retries of the error reply; admin/support notifications.

---

## Risks & Mitigations

- **Auto-responder loops not blocked** — with R6 deferred, a cooperative auto-responder that (a) has a non-`FROM_ADDRESS` sender and (b) does not use a no-reply local-part will receive one error reply, and its reply will hit our webhook again. The reply typically has no PDF attachment, so the handler short-circuits on "no attachments" and does not send another error email. Net: bounded at most one extra round-trip per loop, not infinite. Accept.
- **Shared outer `try/except` means an original `send_reply` failure also triggers an error reply** — the error reply uses the same transport and will most likely also fail (harmlessly swallowed by the helper), or succeed (the sender gets one "couldn't process" email instead of silence). Either outcome is acceptable; documented in U3 test scenarios.
- **No-reply regex is allow-listed, not exhaustive** — catches the common cases; unusual patterns (`autoresponder@`, locale variants) will slip through. Acceptable for v1.

---

## Deferred to Implementation

- Exact HTML copy inside `send_error_reply` body paragraphs — draft during U2; keep under ~40 words total.
- Whether to include a short reference line like "If you need help, reply to this email." — decide during U2; current lean: yes, one line, because it gives the sender a next step without leaking failure detail.
