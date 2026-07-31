# GOLD-MASTER-V2 — Items Blocked on a Human Operator (§18)

Per §18: *"Operator-held credentials only... Nothing else is human-gated."* This register is
deliberately narrow. Every candidate below was checked against first-hand evidence (source
`file:line` + live production probes) before being included or excluded — see the full evidence
log at `uat/reports/evidence/gold-master-v2/phase0/human-gated-verification.md` for every command
run and every response observed, timestamped 2026-07-30.

**Bottom line up front:** of the four candidates examined, only **two are genuinely human-gated**
(Gmail OAuth consent, Adzuna AU credentials). Stripe live keys and the operator admin credential
are **already fully configured and testable today with zero operator action** — this reverses the
default assumption that both were blocked.

---

## NOT human-gated (verify and close these, do not park them)

### Stripe live keys — [VERIFIED-WITH-SOURCE] already live, already testable

`STRIPE_SECRET_KEY` is a **live** key (`sk_live_*` prefix, confirmed from the prefix only — the raw
key is never printed), and all 6 `STRIPE_PRICE_*` vars plus `STRIPE_WEBHOOK_SECRET` are set. A fresh
production probe today created a real `cs_live_…` Stripe Checkout Session end-to-end through a
throwaway self-registered test account — Stripe itself confirms live mode and valid live-mode price
ids by accepting the session (a mismatched test/live price would have errored). The webhook endpoint
correctly rejects an unsigned payload (400 `Missing stripe-signature header`).

**Testable and tested today, no operator action:** `/billing/plans`, `/billing/checkout` (session
creation, plan validation, "already on this plan" idempotency, unconfigured-plan honest 503),
`/billing/webhooks/stripe` signature enforcement, `/billing/entitlement`, `/billing/subscription`,
`/billing/portal` session creation.

**Not testable by any automated agent (not a credential gap — this is normal real-money usage):**
completing an actual purchase requires a human to enter a real card number in Stripe's hosted
Checkout UI (or drive a Stripe-dashboard test clock), and confirming the resulting
`checkout.session.completed` webhook flips `/billing/entitlement` to the purchased plan. This one
step stays **CONDITIONALLY-CLOSED** — see operator steps below — but it is not blocking Stripe
integration work broadly; only the live-purchase confirmation loop.

**Operator steps to close the remaining conditional piece (optional, for full closure of the
purchase-confirmation loop only):**
1. Open `https://5cb5f0620.abacusai.cloud/pricing`, pick a paid plan, complete Stripe Checkout with
   a real card (refundable — see the prior payment-pipeline run precedent).
2. Confirm the webhook delivery in the Stripe dashboard (Developers → Webhooks → recent deliveries →
   2xx) and that `GET /billing/entitlement` reflects the new plan.
3. Exercise cancel/downgrade via Settings → Billing → "Manage subscription" and confirm
   `GET /billing/subscription` reflects it.

### Operator admin credential — [VERIFIED-WITH-SOURCE] authentication confirmed live on production

`AETHER_ADMIN_EMAIL` + `AETHER_ADMIN_PASSWORD_HASH` are set, and — critically — `AETHER_CRON_EMAIL`
/ `AETHER_CRON_PASSWORD` (already in `.env` for the discovery cron job) **are the same account and
the same password**: a live login against production today with those exact credentials returned
`isAdmin: true` and successfully called an admin-only endpoint (`GET /admin/health` → 200). No
operator action is needed to authenticate as admin — the run already can, and did.

**Testable and tested today, no operator action:** the full admin login → `isAdmin=true` → admin-API
access chain, live, on production.

**Not testable:** nothing — this item is fully closed, not conditional.

### URGENT (separate from this register, flagged here for visibility): seeded `admin`/`admin123` currently ALSO grants admin

A prior claim (`docs/delivery/PROGRESS.md:52-53`, "GATE-31 verified live") states the seeded
`admin`/`admin123` test credential is demoted to `isAdmin=false` on every boot. Re-testing this today
shows the opposite: `POST /auth/login {"email":"admin","password":"admin123"}` returns 200 and
`isAdmin: true` — because the operator's *own* real admin account independently has
`username="admin"` set, and its real password appears (via an 8-character length match plus a
successful bcrypt verification — no plaintext printed) to literally be `"admin123"`. The demotion
code only protects the intended `admin@aether.local` placeholder row; it does not protect a real
admin account that happens to share the reserved username. Full mechanism and evidence in the
verification log linked above.

**This is not a human gate — it is a live, currently-exploitable over-permission that should be
fixed by the operator as soon as practical:** rotate `AETHER_ADMIN_PASSWORD_HASH` to a strong,
non-guessable password (bcrypt-hash it and set the new hash — never store plaintext), update
`AETHER_CRON_PASSWORD` to match if cron automation must keep working, then restart per the runbook
command below. This is an operator security action, not a blocker on any workstream — everything
downstream of admin auth is already fully testable regardless.

---

## Genuinely human-gated

### 1. Gmail OAuth consent — [VERIFIED-WITH-SOURCE] interactive consent has no programmatic bypass

`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` are all set (and
`GOOGLE_OAUTH_STATE_SECRET`'s absence is a non-issue — it falls back to `NEXTAUTH_SECRET`, present).
`GET /auth/google/login` (authenticated) already returns a real, well-formed Google consent URL.

**What IS testable without a human (must be tested and marked CONDITIONALLY-CLOSED):** env vars
present, `oauth_configured()` true, `/auth/google/login` returns a real `authUrl` for an
authenticated user, `/auth/google/callback` degrades honestly (302 with an error flag, never a raw
500) on missing/malformed `code`/`state`.

**What is genuinely untestable without a human:** clicking through Google's own hosted consent
screen (choosing a Google account, satisfying Google's login/2FA, clicking "Allow") — Google
requires a real interactive browser session for this per-user OAuth grant; there is no
service-account or headless bypass for it.

**Scope of the block:** narrow — only the Gmail-connect step in Email Center and anything
downstream of a linked Gmail account (sending mail via the user's own Gmail). No other feature is
affected.

**Operator steps:**
1. Sign in to the Aether app as the account you want to connect Gmail for (any user, or the
   operator/admin account).
2. Navigate to Dashboard → Email Center → "Connect Gmail".
3. Complete Google's consent screen with a real Google account, granting the requested Gmail scopes.
4. Confirm the app redirects back with `gmail_connected=1` (not `=0`) and that the connected account
   appears in the Email Center.
5. If it fails, capture the `error=` query param on the redirect and file it in the gap ledger.

No restart is required — this is a per-user, in-browser consent action, not a config change.

### 2. Adzuna AU credentials — [VERIFIED-WITH-SOURCE] confirmed unset; highest-yield lever for AU volume

**Why this matters:** a binding risk-officer adjudication this run **REFUSED** enabling Seek.com.au
sourcing (`docs/delivery/ADR-SEEK-FIRECRAWL.md`, **STATUS: REFUSED** — `AETHER_ENABLE_SEEK` stays
unset in production). Its designated ToS-compliant substitute is the licensed Adzuna AU aggregator.
`AdzunaAdapter` is **already registered** in the live adapter registry
(`apps/api/app/services/discovery/adapter_registry.py:49`) and is fully implemented, tested, and
production-ready (`apps/api/app/services/discovery/adzuna_adapter.py`) — it contributes 0 of the
production jobs solely because `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` are unset in `.env` (confirmed
today: both are entirely absent, not even present-but-empty). **No code change is required** — this
is the single highest-yield compliant lever for AU job volume, and it has been outstanding across at
least one prior phase (first flagged 2026-07-24 in the now-superseded
`LAUNCH-READY-BLOCKED-ON-HUMAN.md`; still unresolved as of this run, 2026-07-30).

**What IS testable without the credential (tested and marked CONDITIONALLY-CLOSED):** the adapter's
honest-degrade behaviour — with credentials absent, `_fetch_live` raises `NotImplementedError`, the
scout records the source as a benign `skipped` (never fabricates jobs), and discovery volume falls
back to the keyless ATS + public-API sources. This graceful-degradation path is verified in source
and matches the live per-source status behaviour already exercised elsewhere in this run.

**What is genuinely untestable without the credential:** any live Adzuna AU search result, pagination,
relevance filtering of real Adzuna postings, or AU job-volume uplift — none of this can be exercised
until real credentials are present, because Adzuna's API itself requires them; there is no test-mode
Adzuna key.

**Operator steps (exact, copy-pasteable):**
1. Go to `https://developer.adzuna.com/` and register a free developer account (email signup +
   confirmation).
2. Once approved, create an application in the Adzuna developer console and copy the issued
   **Application ID** and **Application Key**.
3. Open `/home/ubuntu/github_repos/aether-job-career-agent/.env` and add two lines (the slots are
   already documented in `.env.example`):
   ```
   ADZUNA_APP_ID=<your issued Application ID>
   ADZUNA_APP_KEY=<your issued Application Key>
   ```
   Never commit `.env` — it is already gitignored.
4. Restart the services that read this env var, per
   `docs/delivery/DEPLOYMENT-RUNBOOK.md` §3 (`Restart Individual Services`):
   ```
   sudo systemctl restart aether-api.service
   sudo systemctl restart aether-worker.service
   ```
   (The discovery job itself, `aether-discovery.service`, is a `oneshot` triggered every 30 minutes
   by `aether-discovery.timer` and re-reads `.env` fresh on every run via `scripts/discovery_cron.sh`
   — it needs no restart of its own, but it calls the long-running API process to actually run scout,
   so `aether-api.service` must be restarted for the new credentials to reach the adapter.)
5. Verify: watch the next discovery cron tick (`/var/log/aether/discovery.log`, runs every 30 minutes
   at :00/:30) for a line with `"source":"adzuna"` and `"status":"ok"` with non-zero `fetched`; then
   confirm AU-located jobs with `source: adzuna` start appearing on the Jobs screen.

Until then, Adzuna AU sourcing carries status **CONDITIONALLY-CLOSED**: the adapter, pagination,
relevance filter, honest-degrade path, and per-source disclosure are all implemented and verified;
only the operator-held free-tier key is missing.

---

## Scan for other credential-shaped gaps

**None found.** Optional per-user BYOK provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, `GROQ_API_KEY`) are absent but not blocking — `OPENROUTER_API_KEY` is present and
is the default/primary path covering all system AI/LLM work; the BYOK keys are an optional
convenience for a user who wants to route through a specific provider directly, not a requirement
for any workstream. `GOOGLE_OAUTH_STATE_SECRET` falls back to the already-present `NEXTAUTH_SECRET`.
`PINECONE_*`, `LANGFUSE_*`, and a handful of other `.env.example` entries are optional/legacy config
with code-level defaults, not credentials gating any production request path. Full diff and
per-variable disposition in the evidence log.

---

## Summary table

| # | Item | Genuinely human-gated? | Status |
|---|------|------------------------|--------|
| 1 | Stripe live keys | **No** — already live, tested end-to-end today | Fully testable; only the real-money purchase-confirmation loop is CONDITIONALLY-CLOSED |
| 2 | Operator admin credential | **No** — live login confirmed `isAdmin=true` today | Fully closed |
| — | Seeded `admin`/`admin123` also carrying `isAdmin=true` | N/A (not a gate — a live risk) | Flagged for urgent operator remediation, not blocking |
| 3 | Gmail OAuth consent | **Yes** — narrow scope | CONDITIONALLY-CLOSED; only the interactive consent click needs a human |
| 4 | Adzuna AU credentials | **Yes** | CONDITIONALLY-CLOSED; highest-yield lever, outstanding since 2026-07-24, no code change needed |
| 5 | Any other credential-shaped gap | **No** — none found | — |

Evidence: `uat/reports/evidence/gold-master-v2/phase0/human-gated-verification.md`
(repo HEAD `297946d7dea3d01207586a4c9ef4a8e8bb91f6ef`, probes run 2026-07-30 23:18–23:24 UTC).
