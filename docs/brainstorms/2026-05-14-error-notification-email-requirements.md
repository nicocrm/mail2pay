---
date: 2026-05-14
topic: error-notification-email
---

# Error Notification Email on Non-Retryable Failures

## Summary

When mail2pay cannot produce a QR code for an inbound invoice due to a non-retryable error, reply to the sender with a short generic message so they know their email was received but could not be processed.

## Problem Frame

Today a sender emails an invoice and either gets a QR reply back or gets nothing. Non-retryable failures — PDF too large, PDF unreadable, LLM unable to extract payment details, non-Belgian IBAN, QR generation failure — are swallowed silently: the handler logs and returns 200. From the sender's perspective the system is a black hole, and they may assume the request is still in flight or that the QR reply was lost in their spam folder. That silence is the pain.

## Requirements

**Error reply**
- R1. When any non-retryable failure occurs in the processing pipeline (attachment download rejected as too large, PDF text extraction fails, LLM extraction/validation fails, QR generation fails), send a reply email to the original sender.
- R2. The reply is a single generic message. It does not distinguish error types, echo extracted fields, or expose internal detail (model names, stack traces, field-level validation messages).
- R3. The reply subject and body make clear (a) the invoice was received, (b) it could not be processed, (c) the sender may try again with a different attachment. Keep it short and neutral in tone.
- R4. The reply is sent via the existing mailer/`FROM_ADDRESS` transport — no new channel.

**Loop prevention**
- R5. Do not send an error reply when the original sender address equals the configured `FROM_ADDRESS`.
- R6. Do not send an error reply when the inbound email carries auto-submission signals — specifically an `Auto-Submitted` header with any value other than `no`, or a `Precedence` header of `bulk`, `list`, or `junk`.
- R7. Do not send an error reply when the sender's local-part matches common no-reply patterns (`no-reply`, `noreply`, `do-not-reply`, `donotreply`, case-insensitive).
- R8. When an error reply is suppressed by R5–R7, log the suppression with the email id and the reason, and still return HTTP 200.

**Failure isolation**
- R9. If sending the error reply itself fails, log the exception and return HTTP 200. Do not attempt to email about an email failure, do not retry, do not escalate to 500.
- R10. If sending the original success reply (`Mailer.send_reply`) fails, behavior is unchanged from today — logged and swallowed. No error reply is sent in that case either.

## Acceptance Examples

- AE1. **Covers R1, R2, R3.** Given a sender emails a PDF from which the LLM cannot extract a valid Belgian IBAN, when the handler finishes, the sender receives one email from `FROM_ADDRESS` with a generic "we couldn't process your invoice" body and no mention of IBAN validation.
- AE2. **Covers R1.** Given a sender emails a 20 MB PDF that triggers `PDFTooLargeError`, when the handler finishes, the sender receives the same generic error reply.
- AE3. **Covers R5.** Given an inbound email's `from` equals `FROM_ADDRESS` and processing fails non-retryably, when the handler finishes, no reply is sent and the suppression is logged.
- AE4. **Covers R6.** Given an inbound email carries `Auto-Submitted: auto-replied` and processing fails, when the handler finishes, no reply is sent.
- AE5. **Covers R7.** Given the sender address is `no-reply@example.com` and processing fails, when the handler finishes, no reply is sent.
- AE6. **Covers R9.** Given processing fails non-retryably and the subsequent error-reply send raises, when the handler finishes, the handler returns HTTP 200 and logs both failures.

## Success Criteria

- Senders whose invoice cannot be processed learn that within seconds instead of waiting indefinitely.
- No observed reply loops against no-reply addresses or our own `FROM_ADDRESS` after rollout.
- `uv run ty check .` reports 0 diagnostics and `uv run pytest` passes, including new tests covering R1–R9.

## Scope Boundaries

- Error-specific messages (distinct text for "too large" vs "couldn't extract" vs "non-Belgian IBAN") — explicitly declined.
- Echoing partially extracted fields back to the sender for verification — explicitly declined.
- Per-sender rate limiting / dedup of error replies — out of scope; rely on Resend limits and loop-prevention guards above.
- Localization of the error message — out of scope; single language matching current reply.
- Retries of the error reply on transport failure — out of scope (R9).
- Notifying anyone other than the original sender (e.g. admin alert, support ticket) — out of scope.

## Key Decisions

- Generic message, not error-specific: minimizes leakage, keeps the copy maintainable, and the sender's recovery action is the same in every case (send a clearer PDF).
- Loop guard = FROM_ADDRESS match + Auto-Submitted/Precedence headers + no-reply local-part patterns: cheap, covers the dominant loop sources without state.
- Error-reply transport failures are swallowed: the handler is already returning 200 for non-retryable errors; retrying via 500 would re-run LLM/QR and waste budget.

## Dependencies / Assumptions

- `InboundWebhook` / `data` surfaces inbound email headers (`Auto-Submitted`, `Precedence`) in a usable form. **Unverified** — `mail2pay/models.py` should be checked during planning; if headers are not currently modeled, R6 may require extending the webhook model.
- `Mailer` can send a plain message without a QR attachment, or can be easily extended to do so. **Unverified** — current `Mailer.send_reply` signature takes a base64 QR; planning will confirm whether a new method or a parameter change is cleaner.

## Outstanding Questions

### Deferred to Planning

- [Affects R6][Technical] Are inbound email headers already exposed on `InboundWebhook`, or does the model need extending?
- [Affects R1, R4][Technical] Add a new `Mailer.send_error_reply` method, or generalize the existing `send_reply`?
- [Affects R3][User decision] Exact subject line and body copy — draft during planning for review.
