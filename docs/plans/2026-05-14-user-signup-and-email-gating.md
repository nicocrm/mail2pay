---
date: 2026-05-14
topic: user-signup-and-email-gating
status: active
origin: docs/brainstorms/2026-05-14-user-signup-and-email-gating-requirements.md
---

# feat: User Sign-Up Site and Clerk-Based Email Gating

## Summary

Add a plain-HTML Clerk-authenticated sign-up site under `website/` (deployed to GitHub Pages), and gate `handler.py` so inbound emails from senders not registered in Clerk are silently dropped before any Mistral / Resend spend.

---

## Problem Frame

mail2pay today processes every inbound Resend webhook without any notion of "who is allowed to use this." This plan implements the two-sided change specified in the origin requirements doc: a self-service sign-up surface, and a pre-processing allowlist check in the serverless handler. See origin: `docs/brainstorms/2026-05-14-user-signup-and-email-gating-requirements.md`.

---

## Requirements Trace

All R-IDs from the origin are carried forward:

- **R1–R4** (static site): U1, U2
- **R5–R8** (email gating): U3, U4, U5
- Deployment to GitHub Pages (R4): U6

AE1–AE3 map to test scenarios in U3 and U5.

---

## Key Technical Decisions

- **Clerk Backend API for lookup** — use `GET https://api.clerk.com/v1/users?email_address=<addr>` authenticated with `CLERK_SECRET_KEY`. The endpoint returns a list; we treat a non-empty result with `email_addresses[*].verification.status == "verified"` as "registered." Chosen over Clerk's SDKs to avoid adding a heavy dependency to the serverless bundle — `httpx` is already in the tree.
- **Email normalization** — compare sender address lowercased and stripped. Display-name form (`"Alice <a@b.com>"`) is already parsed out by `mail2pay.models.InboundWebhook.data.from_` (Pydantic `EmailStr`). Plus-addressing (`a+tag@b.com`) is treated as distinct from `a@b.com` — matching Clerk's own behavior, which stores the full local-part.
- **No lookup cache in v1** — one Clerk API call per inbound email is acceptable given current volume. Documented as a deferred optimization.
- **Plain HTML + Clerk CDN** — no build step, no Node in the repo. `website/index.html` loads `@clerk/clerk-js` via CDN, renders a landing page, and mounts Clerk's drop-in `<SignUp />` / `<UserButton />` components.
- **GitHub Pages via Actions** — deploy `website/` via `actions/deploy-pages` on pushes to `main` that touch `website/**`. Keeps Pages config in code, avoids the "serve from branch" UI toggle.
- **Gate placement in `handler.py`** — the check runs immediately after payload validation and before `get_pdf_attachment`. Failing the gate returns `200 "ok"` with a log line, mirroring the existing "no attachments / wrong event type" early-exit pattern.
- **Gate failures are non-retryable** — return 200, not 500. An unregistered sender isn't a transient error; retries would waste Clerk API calls.
- **Clerk API failure posture** — if the Clerk lookup itself fails (network/5xx), return 500 so Resend retries. The gate is fail-closed (no Clerk response ⇒ don't process), but a transient Clerk outage shouldn't permanently drop legitimate email.

---

## Output Structure

```
website/
  index.html          # Landing + Clerk mount points
  styles.css          # Minimal styling
  app.js              # Clerk init, UI wiring
.github/
  workflows/
    deploy-pages.yml  # Build+deploy website/ to GitHub Pages
mail2pay/
  clerk.py            # New: Clerk user lookup
handler.py            # Modified: gate check before processing
mail2pay/config.py    # Modified: add CLERK_SECRET_KEY
tests/
  test_clerk.py       # New
  test_handler.py     # Modified: gating scenarios
```

The `**Files:**` lists in each unit are authoritative.

---

## Implementation Units

### U1. Clerk-authenticated static landing page

**Goal:** Create `website/index.html` with a landing page and Clerk sign-up / sign-in flow.

**Requirements:** R1, R2, R3.

**Dependencies:** none.

**Files:**
- `website/index.html` (new)
- `website/styles.css` (new)
- `website/app.js` (new)

**Approach:**
- Single-page static site. `index.html` contains: headline, 2–3 sentences describing mail2pay, "Sign up" and "Sign in" buttons.
- `app.js` loads `@clerk/clerk-js` from Clerk's CDN (`https://{frontend-api}.clerk.accounts.dev/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`), initialises with `VITE_CLERK_PUBLISHABLE_KEY` substituted at build time — since there is no build, inline the publishable key directly in `app.js`. Clerk publishable keys are safe to expose client-side.
- When signed in, swap the sign-up CTA for `<UserButton />` plus a short "You're registered — send invoices to `<inbound-address>`" message.
- No framework. No bundler. Browser-native modules via `<script type="module">`.

**Patterns to follow:** Clerk's own Vanilla JS quickstart (`clerk.load()` → `clerk.mountSignUp(...)`).

**Test scenarios:** none — this is static frontend content without behavioral logic worth unit-testing. Manual verification via `python -m http.server --directory website 8080` and loading `localhost:8080` is the acceptance test.

**Verification:** Page loads, Clerk sign-up modal opens, a test sign-up lands a user in the Clerk dashboard, signed-in state renders correctly.

---

### U2. Clerk configuration and publishable key wiring

**Goal:** Make the Clerk publishable key configurable per environment without a build step.

**Requirements:** R2.

**Dependencies:** U1.

**Files:**
- `website/app.js` (modify)
- `website/config.example.js` (new)
- `website/README.md` (new — short note on how to configure)
- `.gitignore` (modify — ignore `website/config.js`)

**Approach:**
- `website/app.js` reads the publishable key from `window.CLERK_CONFIG.publishableKey`.
- `website/config.example.js` is a committed template; developers copy it to `website/config.js` (gitignored) and the GH Actions workflow (U6) writes `config.js` from a repo secret at deploy time.
- This avoids committing the key to source while keeping the site fully static.

**Patterns to follow:** existing `.env.example` pattern in the repo root.

**Test scenarios:** none — configuration-only change.

**Verification:** Local dev with a hand-written `website/config.js` renders Clerk UI; deploy workflow (U6) injects the production key.

---

### U3. Clerk user-lookup module

**Goal:** A small module that answers `is_registered(email: str) -> bool` by calling Clerk's Backend API.

**Requirements:** R5, R6.

**Dependencies:** none (parallel with U1/U2).

**Files:**
- `mail2pay/clerk.py` (new)
- `tests/test_clerk.py` (new)

**Approach:**
- Single function `is_registered_user(email: str, secret_key: str, *, client: httpx.Client | None = None) -> bool`.
- Normalises the input: `email.strip().lower()`.
- Calls `GET https://api.clerk.com/v1/users?email_address=<normalised>&limit=1` with `Authorization: Bearer <secret_key>`.
- Returns `True` iff response is 200 and the JSON list is non-empty and the matching `email_addresses[*].email_address` equals the normalised input AND `verification.status == "verified"`.
- Raises `ClerkLookupError` on network errors or 5xx (handler converts this to a 500 for retry).
- Timeout: 5s.

**Patterns to follow:** `mail2pay/download.py`'s use of `httpx` and its `PDFTooLargeError`-style custom exception.

**Test scenarios:**
- Happy path: Clerk returns one user matching the email → `True`.
  *Covers AE2.*
- Empty result: Clerk returns `[]` → `False`.
  *Covers AE1.*
- Case-insensitive match: input `Alice@Example.com`, Clerk has `alice@example.com` → `True`.
- Unverified email: Clerk returns the user but `verification.status == "unverified"` → `False`.
- Plus-addressing: `a+tag@b.com` is NOT matched by `a@b.com` in Clerk.
- Empty / whitespace-only input → `False` without making an HTTP call.
- Clerk 5xx → raises `ClerkLookupError`.
- Network timeout → raises `ClerkLookupError`.
- Clerk 401 (bad secret) → raises `ClerkLookupError` (misconfiguration is a retryable ops problem, not a "drop the email" signal).

**Verification:** `uv run pytest tests/test_clerk.py` green; `uv run ty check .` clean.

---

### U4. Add `CLERK_SECRET_KEY` to config

**Goal:** Make the new secret available to `handler.py` via the existing `Config` object.

**Requirements:** R5.

**Dependencies:** none.

**Files:**
- `mail2pay/config.py` (modify)
- `tests/conftest.py` (modify — add to base env)
- `.env.example` (modify, create if missing)
- `README.md` (modify — add to env vars table)
- `Makefile` (modify — add to `deploy` env-vars list)

**Approach:**
- Add `clerk_secret_key: str = Field(alias="CLERK_SECRET_KEY")` to `Config`.
- No default — fail loud at `_bootstrap()` time if missing, mirroring the existing pattern.
- Extend the `deploy` target's `--env-vars` to include `CLERK_SECRET_KEY=$$CLERK_SECRET_KEY`.

**Patterns to follow:** every existing field in `mail2pay/config.py`.

**Test scenarios:** none — the existing `test_config.py` pattern covers loading.

**Verification:** `uv run ty check .` clean; `uv run pytest` green.

---

### U5. Wire the gate into the webhook handler

**Goal:** `handler.handle` drops unregistered senders silently before any PDF/LLM/Resend work.

**Requirements:** R5, R6, R7, R8.

**Dependencies:** U3, U4.

**Files:**
- `handler.py` (modify)
- `tests/test_handler.py` (modify)

**Approach:**
- In `_bootstrap()`, no new singleton needed — the Clerk lookup uses a fresh `httpx.Client` per call (volume is low; keeping it stateless simplifies testing).
- Insert the gate immediately after the `webhook.type != "email.received"` check and before the `data.attachments` check. Rationale: cheap rejects first (signature, type), then the Clerk lookup (one network call), then attachment work. Putting it before the attachments check means even a payment-less email from a registered user still gets the "no attachments" log line, while unregistered senders are rejected regardless.
- Gate logic:
  - `from_addr = str(data.from_)`
  - `try: allowed = is_registered_user(from_addr, _cfg.clerk_secret_key)`
  - On `ClerkLookupError`: log exception, return `500 "error"` (retryable).
  - If `not allowed`: log at INFO with the sender address and the reason `"sender not registered"`, return `200 "ok"`.
- Log message shape: `"Gating drop: sender=%s reason=%s email_id=%s"` — structured enough to grep in Scaleway logs.

**Patterns to follow:** the existing early-exit pattern (`return {"statusCode": 200, "body": "ok"}`) used for no-attachments and wrong-event-type.

**Test scenarios:**
- Registered sender + PDF attachment → existing happy-path behavior unchanged (Resend send called, 200 returned).
  *Covers AE2.*
- Unregistered sender + PDF attachment → 200, `resend.Emails.send` NOT called, `resend.Emails.Receiving.Attachments.get` NOT called (i.e. gate fires before PDF fetch), Mistral Extractor NOT called.
  *Covers AE1.*
- Unregistered sender → gate log line is emitted containing the sender address and `"not registered"`.
  *Covers AE3.*
- Clerk lookup raises `ClerkLookupError` → 500 returned, no downstream calls, log line identifies the failure.
- Gate runs AFTER signature verification (invalid-signature test still returns 200 without a Clerk lookup — patch `is_registered_user` and assert not called).
- Gate runs AFTER event-type check (event type `email.sent` short-circuits without a Clerk lookup).
- Gate runs BEFORE attachment download (unregistered sender → `download._download` is NOT patched/called).
- Existing happy-path and error-path tests continue to pass once Clerk lookup is stubbed in the test helper.

**Verification:** `uv run pytest` green; `uv run ty check .` clean.

---

### U6. GitHub Pages deployment workflow

**Goal:** Push to `main` that touches `website/**` deploys the site to GitHub Pages.

**Requirements:** R4.

**Dependencies:** U1, U2.

**Files:**
- `.github/workflows/deploy-pages.yml` (new)

**Approach:**
- Standard `actions/configure-pages` + `actions/upload-pages-artifact` + `actions/deploy-pages` triple.
- Trigger: `push` to `main` with `paths: ['website/**', '.github/workflows/deploy-pages.yml']`, plus `workflow_dispatch`.
- Build step: `cp website/ _site/` (or similar) and write `_site/config.js` from `${{ secrets.CLERK_PUBLISHABLE_KEY }}` using a short inline script.
- `permissions: pages: write, id-token: write`.
- Concurrency group `pages` with `cancel-in-progress: false`.

**Patterns to follow:** GitHub's own documented Pages workflow template for static sites.

**Test scenarios:** none — CI workflow. Verified by landing the PR and confirming the Pages deployment succeeds and the live URL loads the signed site.

**Verification:** Workflow run green on the PR; production URL serves `index.html`; Clerk sign-up functional from the live site.

---

## Scope Boundaries

Carried from origin:

- Replying to unregistered senders with an error / invitation message — deliberately not done.
- SMTP-level rejection at Resend's edge — out of scope.
- Post-login dashboard, account settings, admin UI.
- Subscription tiers, paid plans, quotas, rate limits.

### Deferred to Follow-Up Work

- In-memory cache for Clerk lookups (TTL-based) if volume grows enough to matter.
- Custom domain for the Pages site.
- Richer post-login content (usage instructions, inbound address display).

---

## System-Wide Impact

- **Env vars:** new required variable `CLERK_SECRET_KEY` for the serverless function, new required secret `CLERK_PUBLISHABLE_KEY` for the GH Actions workflow. Both must be set before the first deploy after this change lands.
- **Deployment:** the next `make deploy` after this change will fail at bootstrap if `CLERK_SECRET_KEY` is not in `.env`. Ops note in the PR description.
- **No DB, no migration, no schema changes.**

---

## Risks and Mitigations

- **Clerk outage blocks all mail2pay processing.** Mitigation: fail-closed with 500 triggers Resend retry; Clerk's uptime is high; transient outages self-recover within the retry window. Alternative (cache + fail-open) rejected as lower-priority for v1.
- **Publishable key leaked in repo history.** Mitigation: key is publishable — safe to expose — but injected via workflow secret anyway for hygiene. The gitignored `website/config.js` path prevents casual dev mistakes.
- **Sender address mismatch between sign-up email and sending email.** Accepted v1 behavior (silent drop). Users seeing their invoices disappear into a void is the diagnostic cost; documented in origin's Dependencies/Assumptions.
- **Plus-addressing edge case.** Documented in Key Technical Decisions; can be revisited if real users hit it.

---

## Outstanding Questions

### Deferred to Implementation

- [Affects U3][Technical] Exact Clerk API response shape for `GET /v1/users?email_address=...` — verified against Clerk's live API during implementation. If the response shape differs from what's described, U3's matching logic is adjusted without re-planning.
- [Affects U6][Technical] Whether the Pages workflow needs a `jobs.build` step that substitutes `config.js`, or whether a simpler `cp` + `sed` inline script is enough. Resolved at implementation time.
