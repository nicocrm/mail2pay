---
date: 2026-05-14
topic: user-signup-and-email-gating
---

# User Sign-Up and Email Gating

## Summary

Add a static sign-up site (Clerk-authenticated, hosted on GitHub Pages) and gate the mail2pay serverless handler so only emails from registered Clerk users are processed. Unregistered senders are silently dropped.

---

## Problem Frame

mail2pay currently processes every inbound email forwarded by Resend — no notion of "who is allowed to use this." Anyone who discovers the inbound address can trigger Mistral calls and receive QR-code replies, which means unbounded LLM spend, no audit of users, and no path to future per-user features (usage limits, billing, account settings). There is today no registration surface for users at all.

---

## Requirements

**Static sign-up site**
- R1. A static website exists that users can visit to sign up for mail2pay.
- R2. The site uses Clerk as the sole authentication provider (sign-up, sign-in, session management).
- R3. The site contains a landing page with a brief product description and a sign-up / sign-in call-to-action. No post-login pages beyond Clerk's default account UI are in scope.
- R4. The site is deployable to GitHub Pages as a purely static artifact (no server-side rendering, no backend).

**Email gating in the serverless handler**
- R5. When the handler receives an inbound email webhook, it looks up the sender's email address in Clerk's user directory before any PDF / LLM / QR / reply work.
- R6. If the sender's email is not found as a registered Clerk user, the handler silently drops the email: no reply is sent, no Mistral call is made, and processing stops early.
- R7. If the sender's email is found, the handler proceeds with the existing behavior unchanged.
- R8. Gating failures log enough detail (sender address, reason) to be observable in Scaleway logs, but do not emit any outbound email.

---

## Acceptance Examples

- AE1. **Covers R5, R6.** Given `alice@example.com` has never signed up, when an inbound email from `alice@example.com` is delivered to the handler, then the handler returns early without calling Mistral, without calling Resend, and without replying to Alice.
- AE2. **Covers R5, R7.** Given `bob@example.com` has completed Clerk sign-up, when an inbound email from `bob@example.com` with a PDF invoice is delivered, then the handler extracts the invoice, generates the EPC QR code, and replies to Bob as it does today.
- AE3. **Covers R6, R8.** Given an unregistered sender triggers the handler, then a log entry identifying the sender and the gating reason is written, and no record of the email appears in Resend's outbound traffic.

---

## Success Criteria

- A new user can land on the site, sign up via Clerk, and send an email to the mail2pay address and receive a QR code reply — without any manual provisioning step in between.
- Inbound emails from senders who have not signed up produce no outbound traffic and no Mistral spend.
- Planning can proceed to implementation without having to decide on user experience, scope, or gating semantics.

---

## Scope Boundaries

- Replying to unregistered senders with an error / invitation message — deliberately not done; silent drop only.
- SMTP-level rejection / bouncing at Resend's edge — out of scope; gating happens inside the webhook handler.
- Post-login dashboard, usage history, account settings beyond Clerk's defaults.
- Admin UI or user-management surface.
- Subscription tiers, paid plans, per-user quotas or rate limits.
- Migration tooling for any "legacy" senders (there are no existing users to migrate).

---

## Key Decisions

- **Silent drop for unregistered senders**: avoids turning mail2pay into an outbound-mail vector for arbitrary addresses (anyone could spoof a From header and trigger a reply) and keeps the handler's behavior simple. Trade-off: a legitimate user who mistypes their sign-up email gets no feedback loop.
- **Clerk as sole auth provider**: lets the site stay fully static and avoids building a user database / session layer in this project.
- **Gate inside the webhook handler, not at Resend**: Resend inbound email does not support per-address allowlists, so the gate must live in code.
- **GitHub Pages hosting**: free, aligns with a static-only site, and keeps the website co-located with the repo.

---

## Dependencies / Assumptions

- A Clerk application is provisioned and its publishable key is available for the static site.
- A Clerk Backend API secret key can be added to the serverless function's environment as a new variable (e.g. `CLERK_SECRET_KEY`) — this is an addition to the env matrix in `README.md` and `config.py`.
- The serverless function has outbound network access to Clerk's API (Scaleway functions do by default).
- The sender address on inbound Resend webhooks is the address Clerk will have on file — i.e. users sign up with the same email they send invoices from. A user signing up with one address and forwarding from another will be silently dropped; this is accepted for v1.
- GitHub Pages is enabled (or will be enabled) for this repo, on a branch or `/docs` path to be decided in planning.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R1, R4][Technical] Where does the static site live — a `website/` subdirectory in this repo, a `/docs` folder served by GitHub Pages, or a separate repo? (Repo layout choice.)
- [Affects R1][Technical] Which static-site toolchain — plain HTML + Clerk's JS SDK, or a framework like Astro / Next static export? (Implementation detail.)
- [Affects R5][Technical] Which Clerk Backend API call to use for the lookup (users list filtered by email vs. a dedicated lookup endpoint), and what caching / rate-limit behavior is appropriate.
- [Affects R5][Technical] How to match sender address case / normalization against Clerk's stored email (lowercase, plus-addressing handling).
