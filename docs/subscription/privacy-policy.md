# Aether — Privacy Policy (Subscription/Data-Handling Reference)

**Status:** Describes data handling as actually implemented in the codebase as of this Phase 6 run
(2026-07-16), including the new billing/admin subsystem. This is an internal reference document for
the operator, written to be accurate to the running system — not itself the user-facing legal page.

**Relationship to the live in-app page:** the product already serves a public page at
`/privacy-policy` (`apps/web/src/app/privacy-policy/page.tsx`, last updated 2026-07-11). That page
predates this Phase 6 subscription build: it does not mention Stripe, subscription billing, AUD/GST
pricing, or the Australian Privacy Act, and it states self-service data export/deletion "via the
Settings page" that does not currently exist in the codebase (no such endpoint was found in
`apps/api/app/routers/*`). **This document does not silently override that page** — the operator
should reconcile the two before or alongside enabling live billing. Everything below is scoped to
what is actually built, tagged where relevant.

**Production:** https://5cb5f0620.abacusai.cloud

---

## 1. Who this covers / jurisdiction

Aether is billed in Australian dollars (AUD) with GST accounted for at 10%, which means Australian
Privacy Act 1988 (Cth) and the Australian Privacy Principles (APPs) are the relevant framework for
Australian users. The operator has not yet supplied a registered business name or ABN for this
service — **[Business Name]** / **[Operator ABN]** are placeholders the operator must fill in before
this can serve as a compliant public policy (see `docs/subscription/terms-of-service.md` §"Business
details").

---

## 2. What personal data is collected

| Category | Detail | Where it lives |
|---|---|---|
| Account credentials | Email address, username, hashed password (bcrypt, `passlib`) | `User` table |
| Profile / resume content | Uploaded/generated resumes, work history, skills, career profile | `CareerProfile` and related tables |
| Job & application data | Sourced jobs, applications, statuses, notes, outreach tasks | `Job`, `Application`, `OutreachTask`, etc. |
| Gmail tokens (only if connected) | OAuth access + refresh tokens, **encrypted at rest** | `GmailAccount` / `ProviderCredential` / `UserProviderCredential` tables |
| LLM provider credentials (only if user-supplied) | API keys for a user's own LLM provider, **encrypted at rest** | `UserProviderCredential` table |
| Usage / billing metadata | Plan, subscription status, agent-run count, per-run LLM cost in USD | `Subscription`, `UsageQuota`, `AgentRun` tables |

**Encryption of tokens/credentials:** access tokens, refresh tokens, and user-supplied provider API
keys are encrypted at rest with **Fernet symmetric encryption** (`apps/api/app/services/credential_vault.py`),
keyed by a single deployment-wide key held in an environment variable (never committed to source).
Encryption is **per-record** (each stored secret is its own ciphertext) rather than per-user-key —
there is one vault key for the deployment, not one key per user. If the key is absent, encryption
and decryption both raise an explicit error rather than silently storing or returning plaintext.

Passwords are never stored in plaintext or reversibly encrypted — they are one-way hashed with
bcrypt (`passlib.context.CryptContext(schemes=["bcrypt"])`).

---

## 3. How data is used

- **Job sourcing** — the platform queries licensed/compliant sources: Adzuna AU (licensed API),
  official ATS job-board APIs (Greenhouse, Lever, Workable, Ashby), and public Remotive/RemoteOK
  APIs. **Seek is not scraped** — Seek's Terms of Service and `robots.txt` prohibit AI-agent
  scraping (verified; `uat/reports/evidence/phase6/seek-tos-check.md`), so that adapter is disabled.
- **Resume tailoring, cover-letter drafting, story extraction, and email drafting** — these four
  agent types send relevant resume/job text to the configured LLM provider for generation. In
  production this is **OpenRouter** (`AETHER_LLM_MODE=auto`, routing to deepseek-family models by
  plan tier) for the standard billing/routing path. The in-app, interactive "Connect with Anthropic"
  OAuth-consent flow remains removed and unsupported (`ADR-P6-OAUTH`). Separately, as of Phase 7
  (`ADR-P7-01`, `GAP-P7-DEF-A`), the operator (or a signed-in user, for their own per-user credential)
  may manually paste a pre-generated Anthropic credential — a Claude Console API key or a Claude Code
  OAuth token obtained by running `claude setup-token` on their own machine — into the agent-provider
  settings; this is a manual paste of a credential the person already possesses, not an in-app OAuth
  consent screen. A pasted OAuth-token credential is stored encrypted and never logged. See
  `docs/subscription/billing-architecture.md` for the full mechanism.
- **Email management** — if a user connects Gmail, the app reads/drafts/labels messages via the
  Gmail API strictly to support the Email Center feature. Each connected Gmail account's tokens are
  stored and encrypted independently; disconnecting one account (`DELETE /api/emails/accounts/{id}`)
  removes only that account's rows.
- **Billing/quota enforcement** — per-run LLM cost (USD) is recorded to enforce each plan's monthly
  run quota and USD spend cap (see `docs/subscription/admin-guide.md` §4); this is operational
  metering, not used for any purpose beyond that.

---

## 4. Storage

All application data — accounts, resumes, jobs, applications, subscriptions, quotas, and encrypted
credentials — lives in a single hosted PostgreSQL database accessed directly via `psycopg2` (no
ORM at the API layer). There is no separate data warehouse or analytics export pipeline.

---

## 5. User rights (access, correction, deletion)

- **Correction:** users can edit their own profile/resume data directly through the app UI wherever
  those edit flows exist (dashboard/settings, resume editor).
- **Gmail access revocation (self-service, built and live):** a connected Gmail account can be
  disconnected at any time via `DELETE /api/emails/accounts/{account_id}`, which deletes that
  account's stored (encrypted) tokens immediately.
- **Full account data export or full account deletion (admin-mediated only, not self-service):**
  there is currently **no self-service "export my data" or "delete my account" endpoint** in the
  codebase. The admin panel's audit/mutation surface (spend-cap, suspend, settings) is built and
  live, but a dedicated **per-user data export/delete action is Tier 2 and not yet built**
  (`GAP-P6-ADMIN-003`, tracked, deferred until Tier 1 admin is fully closed). Until that ships, a
  user requesting export or deletion must be handled manually by the operator via direct database
  access. **This is a real gap** — the existing live `/privacy-policy` page's claim of self-service
  "Delete your data via the Settings page" does not match the current build and should be corrected
  or the feature should be built before that page's claim is accurate.

---

## 6. Third parties

- **Stripe** — payment processing for paid subscriptions. Billing code (checkout, webhooks,
  customer/subscription sync) is built and unit-tested against a mocked Stripe SDK, but **live
  Stripe is not yet active in production** — it requires the operator to supply `STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET`, and Price IDs (see `docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md`). Until
  then, no payment data is transmitted to Stripe because no live Stripe account is wired in.
- **LLM provider (OpenRouter, production default)** — receives resume/job text as needed to
  generate tailored content; billed in USD, tracked per run (`AgentRun.costUsd`).
- **Google (Gmail API)** — only if a user explicitly connects an account; OAuth consent is required
  and the connection is revocable at any time (§5).

No user data is sold. No personal data is shared with any party beyond what is functionally
required to deliver the feature the user invoked (sourcing, tailoring, email, payment).

---

## 7. Security measures actually in place

- **Encryption at rest** for OAuth tokens and user-supplied provider credentials (Fernet, §2).
- **Password hashing** with bcrypt, never plaintext or reversible storage.
- **TLS in transit** (platform ingress terminates HTTPS).
- **Rate limiting** on authentication: login capped at 5 failed attempts per identifier per
  15-minute window; registration capped at 3 attempts per email per hour
  (`apps/api/app/rate_limit.py`). Billing endpoints are separately rate-limited (checkout 5/hour/user,
  billing portal 10/hour/user).
- **Webhook integrity** — the Stripe webhook handler verifies the raw-body signature *before*
  parsing any payload, and processes each event exactly once via a transaction-scoped idempotency
  table (`StripeEvent`), so a replayed or forged webhook cannot mutate billing state.
- **No secrets in source** — all credentials (JWT signing secret, Fernet vault key, Stripe keys,
  admin credential) are read from environment variables only, never committed.
- **Account suspension** — an admin can suspend a user, which returns 403 on every one of that
  user's authenticated routes until lifted (§ admin-guide.md).

---

## 8. Changes to this document

This document reflects the system as verified during the Phase 6 run (2026-07-16). It should be
re-verified against the codebase before being treated as a durable policy, and the operator should
reconcile it with the live `/privacy-policy` page (§ "Relationship to the live in-app page" above)
before relying on either as the sole public-facing privacy notice.
