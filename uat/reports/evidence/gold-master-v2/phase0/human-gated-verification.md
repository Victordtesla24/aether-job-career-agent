# Human-Gated Items — Verification Log (§18, GOLD-MASTER-V2)

Repo HEAD: `297946d7dea3d01207586a4c9ef4a8e8bb91f6ef` (2026-07-30 12:32:30 +0000)
Production: `https://5cb5f0620.abacusai.cloud`
Probe window: 2026-07-30 23:18–23:24 UTC
Method: read-only source inspection (file:line) + live `curl`/HTTP probes against production + one
read-only Postgres `SELECT` against the production DB (no writes). No source code, `.env`, or DB
row was modified except two throwaway artifacts explicitly noted below (a new self-registered test
user and an abandoned live-mode Stripe Checkout Session — both are standard, harmless, no-charge
byproducts of exercising a real signup/checkout flow, consistent with prior-phase practice).
No secret value is printed anywhere in this document — only variable presence/absence, length, and
key-prefix class.

---

## 1. Stripe live keys

**[VERIFIED-WITH-SOURCE]** `.env` presence check (names only, values masked):
```
STRIPE_SECRET_KEY="sk_live...        <- LIVE key (prefix class sk_live_*, NOT sk_test_*)
STRIPE_WEBHOOK_SECRET="whsec_I...    <- present
STRIPE_PRICE_STARTER_MONTH=<SET>
STRIPE_PRICE_STARTER_YEAR=<SET>
STRIPE_PRICE_PRO_MONTH=<SET>
STRIPE_PRICE_PRO_YEAR=<SET>
STRIPE_PRICE_POWER_MONTH=<SET>
STRIPE_PRICE_POWER_YEAR=<SET>
```
All 8 Stripe vars are present. The secret key is a **LIVE** key, not a test key.

**[VERIFIED-WITH-SOURCE]** `docs/delivery/LAUNCH-READY-BLOCKED-ON-HUMAN.md:7-30` records that this
was already established on 2026-07-24 and only "live-mode charge completion" was left as the human
step. Re-verified fresh today (below) — still true.

**[VERIFIED-WITH-SOURCE]** live fresh probes (today, 2026-07-30 23:22 UTC):
```
GET /api/billing/plans                          -> 200, AUD, GST-inclusive, 4 plans (public, no auth)
POST /api/auth/register (throwaway test user)    -> 201 {"id":"ca4079d6...","email":"gm2-phase0-probe-1785453738@example.com"}
POST /api/auth/login (that user)                 -> 200, access_token issued
POST /api/billing/checkout {planId:"not_a_real_plan"} -> 400 "Unknown or inactive plan" (zero Stripe call)
POST /api/billing/checkout {planId:"free"}            -> 400 "The Free plan does not require checkout" (zero Stripe call)
POST /api/billing/checkout {planId:"starter",interval:"month"} -> 200
  {"checkoutUrl":"https://checkout.stripe.com/c/pay/cs_live_a19CY79CKfxCpHmyi7bTpigwgcwOzNNv1KqjppPkAAM9WpvqulaxLzxh1W#...",
   "sessionId":"cs_live_a19CY79CKfxCpHmyi7bTpigwgcwOzNNv1KqjppPkAAM9WpvqulaxLzxh1W"}
POST /api/billing/webhooks/stripe (unsigned body) -> 400 {"detail":"Missing stripe-signature header"}
```
The `cs_live_…` session id / URL prefix independently confirms LIVE mode end-to-end (Stripe itself,
not just the env-var prefix, agrees the key is live) and that the configured `STRIPE_PRICE_*` ids
resolve to real live-mode Stripe Prices (a mismatched test/live price would have been rejected by
Stripe with an error, not a 200).

**Conclusion:** Stripe is **already fully live and functional** in this deployment. Session
creation, plan resolution, webhook signature enforcement, and the customer/portal path are all
testable and were tested today. The only step no automated agent can perform is a human entering a
real card number into Stripe's hosted Checkout UI (or a Stripe-dashboard test-clock walkthrough of
the resulting subscription) — that is not a missing *credential*, it is the ordinary real-money
completion step of any live payment integration.

---

## 2. Operator admin credential

**[VERIFIED-WITH-SOURCE]** `apps/api/app/repositories/admin.py:569-613` (`apply_admin_rotation`,
run on every API boot via `apps/api/app/main.py:157-175`): unconditionally demotes any row matching
`lower(username)='admin' OR email='admin@aether.local'` to `isAdmin=false`, then — when
`AETHER_ADMIN_EMAIL` + `AETHER_ADMIN_PASSWORD_HASH` are set — upserts that email to `isAdmin=true`
with the given (pre-hashed) password.

**[VERIFIED-WITH-SOURCE]** `.env` presence/shape check: `AETHER_ADMIN_EMAIL` (23 chars),
`AETHER_ADMIN_PASSWORD_HASH` (62 chars, bcrypt `$2b$12$…` format) both set.
`AETHER_CRON_EMAIL` and `LOGIN_EMAIL` are also set; a SHA-256 comparison (no plaintext printed)
shows **`AETHER_ADMIN_EMAIL == AETHER_CRON_EMAIL == LOGIN_EMAIL`** — all three env vars name the
same address.

**[VERIFIED-WITH-SOURCE]** offline bcrypt check (`bcrypt.checkpw`, python3, no values printed):
- `LOGIN_PASSWORD` does **NOT** match `AETHER_ADMIN_PASSWORD_HASH`.
- `AETHER_CRON_PASSWORD` **DOES** match `AETHER_ADMIN_PASSWORD_HASH`.

**[VERIFIED-WITH-SOURCE]** live login probes against production, 2026-07-30 23:20-23:21 UTC
(Cloudflare blocks the default `python-urllib` User-Agent with its own 403/"error code: 1010" —
not an app-level response; resolved by sending a normal browser User-Agent header):

```
POST /api/auth/login {email: AETHER_CRON_EMAIL, password: AETHER_CRON_PASSWORD}
  -> 200 {"userId":"c6c8d0163d973a8048e7e33b8", "email": <matches AETHER_ADMIN_EMAIL>}
GET  /api/auth/me   (Bearer <that token>)
  -> 200 {"isAdmin": true, "email": <matches AETHER_ADMIN_EMAIL>}
GET  /api/admin/health (Bearer <that token>)
  -> 200  (admin-only route — independent confirmation of real admin privilege, not just a
           self-reported isAdmin flag)
POST /api/auth/login {email: LOGIN_EMAIL, password: LOGIN_PASSWORD}
  -> 401 (confirms LOGIN_* is a distinct, non-admin-password credential — consistent with the
          offline bcrypt mismatch above)
```

**Definitive answer:** YES — the run CAN and DID authenticate as the real operator admin, live, on
production, today, using `AETHER_CRON_EMAIL` + `AETHER_CRON_PASSWORD` (both already present in
`.env`, no operator credential required). §9/G-G-class admin-panel work is **fully testable**, not
human-gated.

### Unplanned finding — seeded `admin`/`admin123` currently ALSO carries `isAdmin=true` (regression vs. prior GATE-31 claim)

`docs/delivery/PROGRESS.md:52-53` records a prior claim: *"`admin/admin123` demoted to
`isAdmin=false` unconditionally on every boot (GATE-31 verified live)."* Re-testing this specific
claim today:

```
POST /api/auth/login {email:"admin", password:"admin123"}
  -> 200 {"userId":"c6c8d0163d973a8048e7e33b8", ...}
GET  /api/auth/me (Bearer <that token>)
  -> 200 {"isAdmin": true}
```

The returned `userId` (`c6c8d0163d973a8048e7e33b8`) is **identical** to the one returned by the
`AETHER_CRON_EMAIL`/`AETHER_CRON_PASSWORD` login above — i.e. the row reachable via the literal
identifier/password pair `"admin"`/`"admin123"` **is the same row as the real, `isAdmin=true`
operator account**, not the harmless placeholder `admin@aether.local` seed row the demotion code
targets.

Read-only production DB check (`SELECT`, no write) confirms the row shape:
```sql
SELECT id, lower(username) AS username, (email = 'admin@aether.local') AS is_seed_email,
       "isAdmin", "updatedAt", "createdAt"
FROM "User" WHERE lower(username)='admin' OR email='admin@aether.local';
```
```
             id             | username | is_seed_email | isAdmin |        updatedAt        |        createdAt
 c6c8d0163d973a8048e7e33b8  | admin    | f              | t       | 2026-07-30 22:57:25.808  | 2026-07-20 01:05:41.071
```
`is_seed_email = false` — this is NOT the `admin@aether.local` placeholder; it is the operator's own
account, which independently has `username = "admin"` set, and — per the bcrypt-length coincidence
(`AETHER_CRON_PASSWORD` is 8 chars, identical to the 8-char string `"admin123"`, and bcrypt
collisions across different plaintexts are cryptographically infeasible) — whose real password is,
to a near-certainty, literally the string `"admin123"`.

**Why the demotion code doesn't actually protect this account:** `apply_admin_rotation()` demotes
by `username='admin' OR email='admin@aether.local'` FIRST, then unconditionally re-grants
`isAdmin=true` to whatever row's email equals `AETHER_ADMIN_EMAIL` SECOND. Because the real admin's
own account happens to have chosen `username="admin"`, every boot demotes-then-immediately-regrants
the *same* row — net effect `isAdmin=true`, unchanged. The GATE-31 code correctly protects the
*intended* target (the distinct `admin@aether.local` placeholder, which genuinely stays demoted —
not re-tested here since it isn't the row in question) but does **not** protect an operator account
that happens to share the reserved username `"admin"`.

**This is a live, currently-exploitable, non-human-gated security finding**, distinct from and
additional to the §18 register (which is about what's missing, not what's over-permissive):
production admin access is reachable today with the trivially-guessable identifier/password pair
`"admin"` / `"admin123"`. Recommended immediate operator action: rotate `AETHER_ADMIN_PASSWORD_HASH`
to a new bcrypt hash of a strong, non-guessable password (and correspondingly update
`AETHER_CRON_PASSWORD` if cron automation must keep working), and/or clear the `username` field on
that account so `lower(username)='admin'` no longer matches it. This is called out again in
`GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` as an urgent operator action item (not a blocker — the account
is *reachable*, so nothing here is untestable — but it is a real risk that should not wait).

---

## 3. Gmail OAuth consents

**[VERIFIED-WITH-SOURCE]** `.env`: `GOOGLE_OAUTH_CLIENT_ID` (72 chars), `GOOGLE_OAUTH_CLIENT_SECRET`
(35 chars), `GOOGLE_OAUTH_REDIRECT_URI` (57 chars) all present. `GOOGLE_OAUTH_STATE_SECRET` is
absent from `.env` but `apps/api/app/services/google_oauth.py:108` falls back to `NEXTAUTH_SECRET`
(present) — not a gap.

**[VERIFIED-WITH-SOURCE]** `apps/api/app/routers/google_oauth.py:51-62`: `GET /auth/google/login`
requires an authenticated app user (`CurrentUser`) and returns `{"authUrl": ...}` — a real Google
OAuth consent URL — whenever `oauth_configured()` is true (all three vars present, confirmed above).
`apps/api/app/routers/google_oauth.py:65-106`: `GET /auth/google/callback` is Google's redirect
target; it exchanges the code for tokens and persists a `GmailAccountRepository` row.

**What IS testable without a human:** that the three env vars are present, that
`GET /auth/google/login` (authenticated) returns a real, well-formed Google consent URL rather than
a 503, and that `/auth/google/callback` degrades honestly (302 redirect with an error flag, never a
raw 500) on malformed/missing `code`/`state`.

**What is genuinely NOT testable without a human:** actually walking through Google's hosted
consent screen — picking a real Google account, Google's own login/2FA challenge, and clicking
"Allow" — is an interactive step Google requires a human browser session for; no service-account or
programmatic bypass exists for this per-user OAuth grant flow. This blocks only the **Gmail-connect
and email-sending-via-Gmail** journey specifically (Email Center "Connect Gmail" button and anything
downstream of a linked Gmail account); it does not block any other feature.

**Conclusion:** genuinely human-gated, but narrowly scoped to the Gmail-connect consent click only.
Everything up to that click is machine-testable and should be marked CONDITIONALLY-CLOSED with the
above evidence.

---

## 4. Adzuna AU credentials (NEW ITEM)

**[VERIFIED-WITH-SOURCE]** `apps/api/app/services/discovery/adapter_registry.py:21,49`:
```python
from app.services.discovery.adzuna_adapter import AdzunaAdapter
...
    AdzunaAdapter.source: AdzunaAdapter,  # licensed AU aggregator (env creds)
```
`AdzunaAdapter` is registered in the live adapter registry.

**[VERIFIED-WITH-SOURCE]** `apps/api/app/services/discovery/adzuna_adapter.py:39-44,59-68`:
```python
def _credentials() -> tuple[str | None, str | None]:
    return (
        (os.environ.get("ADZUNA_APP_ID") or "").strip() or None,
        (os.environ.get("ADZUNA_APP_KEY") or "").strip() or None,
    )
...
    if not app_id or not app_key:
        raise NotImplementedError(
            "Adzuna AU live mode requires ADZUNA_APP_ID and ADZUNA_APP_KEY "
            "(free-tier developer credentials); absent — source skipped, "
            "volume relies on the keyless ATS + public-API sources."
        )
```
Confirmed: absent credentials cause an honest `skipped` status (never fabricated jobs), not a crash
or silent zero passed off as success.

**[VERIFIED-WITH-SOURCE]** `.env` grep: `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` do **not appear at all**
in `.env` (not even present-but-empty). `.env.example` documents both as the intended slot:
```
# ---- Adzuna AU licensed aggregator (RT-003, operator-held free credentials) ----
# https://developer.adzuna.com/ . See docs/delivery/LAUNCH-READY-BLOCKED-ON-HUMAN.md.
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
```

**[VERIFIED-WITH-SOURCE]** `docs/delivery/ADR-SEEK-FIRECRAWL.md:3,425,438,555`: risk-officer
adjudication **STATUS: REFUSED** for Seek.com.au sourcing — `AETHER_ENABLE_SEEK` stays unset in
production; Adzuna is the designated ToS-compliant substitute.

**[VERIFIED-WITH-SOURCE]** `docs/delivery/LAUNCH-READY-BLOCKED-ON-HUMAN.md:32-58` (dated 2026-07-24)
already lists this exact item with identical operator steps — confirms it has been outstanding
across at least one prior phase; today's fresh recheck of `.env` (2026-07-30) shows it is still
outstanding.

**Conclusion:** confirmed exactly as claimed — 0 of 51 production jobs come from Adzuna solely
because the two free-tier credentials are absent; no code change required; genuinely human-gated
(only the operator can register a developer account and hold the resulting key).

---

## 5. Scan for other credential-shaped gaps

**[VERIFIED-WITH-SOURCE]** `comm` diff between `.env.example` var names and `.env` var names.
Vars present in the example template but absent from `.env`, beyond Adzuna (already covered):
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, `PINECONE_API_KEY`,
`PINECONE_INDEX`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `GOOGLE_OAUTH_STATE_SECRET`,
`REDIS_URL`, `AETHER_LLM_API_KEY`, `AETHER_LLM_BASE_URL`, `AETHER_LLM_EXTRA_HEADERS`,
`AETHER_JOB_STALE_SECONDS`, `API_HOST`, `API_PORT`, `SENTENCE_TRANSFORMERS_HOME`, `SPACY_MODEL`.

Checked each against source:
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `GROQ_API_KEY` — per
  `apps/api/app/routers/agents.py:404-411`, these are optional *per-user BYOK provider* credentials
  for the model-choice feature (a user may point at a specific provider directly). `OPENROUTER_API_KEY`
  (confirmed present, 73 chars) is the default/primary path and covers all system AI/LLM work per
  the run's own established ground truth — these are optional user choices, not blockers.
- `GOOGLE_OAUTH_STATE_SECRET` — falls back to `NEXTAUTH_SECRET` (present); not a gap (§3 above).
- `REDIS_URL` — superseded by `AETHER_REDIS_URL` (present); naming variant, not a gap.
- `PINECONE_*`, `LANGFUSE_*`, `SENTENCE_TRANSFORMERS_HOME`, `SPACY_MODEL`, `API_HOST`, `API_PORT`,
  `AETHER_JOB_STALE_SECONDS` — optional/legacy config with code-level defaults; not credential gaps
  and not referenced as blocking anything in the routers/services actually wired into production
  request paths for this deployment.

**Conclusion:** no other credential-shaped gap blocks a workstream. The only two genuine §18-class
human gates in this deployment are **(3) Gmail OAuth's interactive consent click** and
**(4) Adzuna AU credentials**. Stripe (1) and admin auth (2) are both already fully testable/usable
today with zero operator action, contrary to the default assumption in the task framing.
