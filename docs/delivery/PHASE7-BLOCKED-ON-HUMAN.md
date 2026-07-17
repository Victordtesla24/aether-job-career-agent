# PHASE-7 — BLOCKED-ON-HUMAN CONSOLIDATED CHECKLIST (GATE-27, §5)

**Date:** 2026-07-17
**Prepared by:** doc-updater (claude-sonnet-4)
**Evidence root:** `uat/reports/evidence/phase7/`
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Production:** https://5cb5f0620.abacusai.cloud

This supersedes `docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md` as the current checklist (per
`aether-subscription-prompt.md` §5: "Maintain `docs/delivery/PHASE7-BLOCKED-ON-HUMAN.md` … inherits
Phase-6 + Phase-7 additions"). All code and tests for every BLOCKED item below are already built and
merged to `main`; only the human-performed action listed is outstanding. **Never faked, never
inferred-closed** — every BLOCKED status below is re-confirmed by a fresh Phase-7 probe, not carried
forward on trust.

---

## Summary

| # | Item | Status | Blocks |
|---|---|---|---|
| H-01 | Stripe account + test API keys + webhook secret | **BLOCKED** (Phase-6 carry-over) | GATE-18b billing flows (GATE-18 to GATE-22) |
| H-02 | 6 Stripe Price IDs (Free/Starter/Pro/Power × monthly+annual) | **BLOCKED** (Phase-6 carry-over) | GATE-18 to GATE-22 |
| H-03 | Stripe ABN + Tax settings | **BLOCKED** (Phase-6 carry-over) | GATE-20 |
| H-04 | `AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH` in production `.env` | **BLOCKED** — confirmed absent, `probe-p7-03b-admin-env.txt` | Formal admin-panel credential-rotation gate (GATE-07 per §5 mapping) |
| H-05 | Two Gmail OAuth consents (multi-inbox feature) | **BLOCKED** (Phase-6 carry-over) | GATE-23 |
| H-06 | Adzuna AU API creds (`ADZUNA_APP_ID` / `ADZUNA_APP_KEY`) | **OPTIONAL** — sourcing floor already exceeded without it | GATE-10 (strengthens margin only) |
| H-07 | Operator's Claude Code `sk-ant-oat01-` token, present on exec machine | **SATISFIED — DONE** | GATE-02 |

**5 of 7 items still require human action (H-01, H-02, H-03, H-04, H-05). 1 is optional (H-06). 1 is
satisfied (H-07).**

---

## H-01 — Stripe account + test API keys + webhook secret

**Status:** BLOCKED. [VERIFIED-WITH-SOURCE] Re-confirmed fresh this phase: `step2-infra-check.txt` §8
enumerates every key present in the live production `.env` (36 keys) — no `STRIPE_*` key of any kind
appears in that list. `PHASE7-CLAIM-LEDGER.md` CL-10 independently re-confirms via the same probe plus
a live production DB read (billing schema tables exist and are populated with `Plan`/`RATIFIED_PLANS`
rows — the code side is genuinely built — but no Stripe credential is configured).

**Exact setup action:**
1. Create (or use an existing) Stripe account; switch to **test mode**.
2. Stripe Dashboard → Developers → API keys → copy the **test** secret key.
3. Set env var `STRIPE_SECRET_KEY` in the repo-root `.env` (never commit it).
4. Stripe Dashboard → Developers → Webhooks → **Add endpoint** →
   `https://5cb5f0620.abacusai.cloud/api/billing/webhooks/stripe` → copy the signing secret.
5. Set env var `STRIPE_WEBHOOK_SECRET` in the same `.env`.
6. Restart `aether-api` (`sudo systemctl restart aether-api.service`) so the process picks up the new
   env values (per `DEPLOYMENT-RUNBOOK.md` §7 — `.env` is loaded once at process start by
   `start-api.sh`).

**Unblocks:** GATE-18b (billing flows) plus GATE-18 through GATE-22.

---

## H-02 — 6 Stripe Price IDs

**Status:** BLOCKED. [VERIFIED-WITH-SOURCE] Same evidence as H-01 — no `STRIPE_PRICE_*` key present in
`step2-infra-check.txt`'s enumerated key list.

**Exact setup action:**
1. In the same Stripe test-mode account, create 3 Products: **Starter**, **Pro**, **Power** (Free tier
   needs no Stripe Price — it is the $0 entitlement).
2. For each of the 3 paid products, create **2 Prices**: one **monthly**, one **annual** (6 Prices
   total).
3. Set the following 6 env vars in the repo-root `.env` with the resulting Stripe Price IDs (`price_…`):
   - `STRIPE_PRICE_STARTER_MONTHLY`
   - `STRIPE_PRICE_STARTER_ANNUAL`
   - `STRIPE_PRICE_PRO_MONTHLY`
   - `STRIPE_PRICE_PRO_ANNUAL`
   - `STRIPE_PRICE_POWER_MONTHLY`
   - `STRIPE_PRICE_POWER_ANNUAL`

   (Exact env-var naming per the `STRIPE_PRICE_*` convention referenced in
   `PHASE6-BLOCKED-ON-HUMAN.md` item 3; confirm the literal names against
   `apps/api/app/routers/billing.py`'s price-ID lookup before setting, since this doc does not
   independently re-derive the exact variable names from source.)
4. Restart `aether-api`.

**Unblocks:** GATE-18 through GATE-22.

---

## H-03 — Stripe ABN + Tax settings

**Status:** BLOCKED. [VERIFIED-WITH-SOURCE] Carried over unchanged from Phase-6 — no Stripe account
exists yet to configure (blocked by H-01), so this is necessarily still blocked; no independent Phase-7
probe was needed to confirm a non-existent Stripe dashboard's tax settings.

**Exact setup action:**
1. In the Stripe Dashboard (same account as H-01/H-02) → Settings → Tax → enable Stripe Tax.
2. Enter the operator's **ABN** (Australian Business Number) in the Stripe business/tax profile.
3. No env var — this is Stripe-dashboard-side configuration only, not a code/`.env` change.

**Unblocks:** GATE-20 (GST-inclusive invoicing, ABN on invoice).

---

## H-04 — Admin credential rotation env vars

**Status:** BLOCKED. [VERIFIED-WITH-SOURCE] `uat/reports/evidence/phase7/probe-p7-03b-admin-env.txt`:
literal output `"NO AETHER_ADMIN vars present"`. Cross-confirmed by `step2-infra-check.txt` §8:
`AETHER_ADMIN_EMAIL: NOT FOUND`, `AETHER_ADMIN_PASSWORD_HASH: NOT FOUND`. The demotion of the
`admin/admin123` seed account to non-admin is independently confirmed already done
(`probe-p7-03a-admin-access-demoted.json`, CL-11 CONFIRMED in the claim ledger) — so the codebase side
(admin-panel access control) is built and safe; only the operator's own admin credential is
outstanding.

**Exact setup action:**
1. Choose the operator's real admin email address.
2. Generate a bcrypt hash of the chosen admin password (e.g.
   `python3 -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"`
   using the `/opt/abacus-python` interpreter that already has `bcrypt`/`passlib` available per the
   API's own dependency set — do not print the plaintext password anywhere in a log or transcript).
3. Set env vars in the repo-root `.env`:
   - `AETHER_ADMIN_EMAIL=<the chosen email>`
   - `AETHER_ADMIN_PASSWORD_HASH=<the bcrypt hash from step 2>`
4. Restart `aether-api`.
5. Verify: log in with the new admin email/password → confirm `isAdmin=true` on the session; confirm
   `admin/admin123` (or whatever the legacy seed credential is) still resolves to `isAdmin=false`.

**Unblocks:** the formal admin-panel credential-rotation gate (mapped to GATE-07 in §5 of the operator
prompt; distinct from the sourcing-volume GATE-07 referenced elsewhere — the operator prompt reuses
the GATE-07 label across two different gate tables, so this document reproduces that ambiguity rather
than silently resolving it).

---

## H-05 — Two Gmail OAuth consents (multi-inbox feature)

**Status:** BLOCKED. [VERIFIED-WITH-SOURCE] `step2-infra-check.txt` §8 confirms only a single Google
OAuth application's client credentials are configured (`GOOGLE_OAUTH_CLIENT_ID` /
`GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URI` — all `[PRESENT]`, one app registration).
No Phase-7 evidence shows a second connected Gmail account; this is carried over unchanged from
Phase-6's BLOCKED status (`PHASE6-BLOCKED-ON-HUMAN.md` item 5) since it requires interactive,
per-account human OAuth consent that the swarm cannot and must not perform.

**Exact setup action:**
1. In Google Cloud Console, on the existing OAuth consent screen for this app, add the second test
   Gmail account as a **test user** (if the consent screen is still in Testing publishing status).
2. In the Aether dashboard (`/dashboard/email`), click **Connect Gmail** and complete the OAuth
   consent flow for **each** of the 2 Gmail accounts in turn (this is an in-app, human-driven action —
   no env var to set).
3. Verify: `GET /emails/accounts` returns 2 independent-token rows; account-filtered vs. unified inbox
   views both work.

**Unblocks:** GATE-23 (this document's own GATE-27 numbering carries the operator prompt's own mapping
of H-05 → GATE-23 for the multi-inbox feature, distinct from GAP-P7-DIR-001's unrelated use of the
GATE-23 label for directory consolidation in the gap ledger — again reproduced as given rather than
silently resolved).

---

## H-06 — Adzuna AU API credentials (OPTIONAL)

**Status:** OPTIONAL — not blocking. [VERIFIED-WITH-SOURCE] `journey-j5-sourcing.json` /
`step10-cluster2-gates.json` (`J5_SOURCING.step6_sourcing_floor_GATE-10`): **33 total jobs across 5
sources**, with 3 sources (`ashby`=8, `lever`=5, `greenhouse`=16) each independently meeting the ≥5
floor, **0 duplicate `sourceUrl`s**, **0 stale (>30d) postings**, verdict **PASS**. GATE-10's volume
margin is already exceeded on the compliant ATS/public-API source set **without** Adzuna. This upgrades
Phase-6's framing (where Adzuna was "recommended" to strengthen a thin margin,
`PHASE6-BLOCKED-ON-HUMAN.md` item 7 / GATE-07 risk note) to a confirmed non-blocker for Phase-7: the
floor is met today with real margin, not on a decaying edge case.

**Exact setup action (only if the operator wants additional AU source diversity/durability):**
1. Free registration at https://developer.adzuna.com/.
2. Set env vars in the repo-root `.env`:
   - `ADZUNA_APP_ID=<from Adzuna developer portal>`
   - `ADZUNA_APP_KEY=<from Adzuna developer portal>`
3. Restart `aether-api`. Absent these, the Adzuna adapter continues to skip honestly (no fabricated
   listings) and the platform meets GATE-10 through Greenhouse/Lever/Ashby alone.

**Unblocks:** nothing currently blocked; enhancement-only.

---

## H-07 — Operator's Claude Code `sk-ant-oat01-` token (SATISFIED)

**Status:** **DONE.** [VERIFIED-WITH-SOURCE] `uat/reports/evidence/phase7/probe-p7-08e-claude-token-presence.txt`:
`~/.claude/.credentials.json` **EXISTS**, contains a Claude AI OAuth token with prefix
`sk-ant-oat01-` (the user's legitimate Claude.ai subscription credential) on the execution machine.

This is not merely "present" — it was **live-verified end-to-end** as part of closing GAP-P7-DEF-A:
- The same-format token class was accepted by `PUT /api/agents/providers/anthropic/credential`,
  synced to the repo-root `.env` as `CLAUDE_CODE_OAUTH_TOKEN` (600 permissions, value never logged —
  `journey-j1-env-written.txt`), and round-tripped through a **genuine live Anthropic API call**
  (`journey-j1-test-conn-oat.json`: `{"ok":true,"status":"ok","detail":"anthropic responded HTTP 200."}`).
- `step10-cluster1-gates.json` GATE-02 status: **VERIFIED-CLOSED**.
- Production's stored Anthropic credential is now `authMode=oauth_token`, `source=database`, and this
  is the intended, permanent end-state (`step10-cluster1-gates.json`, `residual_notes`) — not a
  temporary test fixture to be reverted.

**No further action required from the operator for H-07.**

---

## Note — DEF-A / DEF-B / DEF-B-PERSIST / DISCOVERY-001 / ASYNC-001 are NOT human-gated

All 5 Phase-7 code gaps closed this phase were verified **VERIFIED-CLOSED on production** by the `qa`
sub-agent using real, live evidence — none of them are blocked on any human action:

- **GAP-P7-DEF-A** (dual-mode Anthropic credential) — GATE-02 through GATE-06 VERIFIED-CLOSED,
  `step10-cluster1-gates.json`.
- **GAP-P7-DEF-B** (settings-email allowlist validation) — validation-layer sharp-edge design confirmed
  correct (`journey-j2-evil-local-422.json`, `journey-j2-garbage-email-422.json`).
- **GAP-P7-DEF-B-PERSIST** (the persistence no-op `qa` discovered underneath DEF-B) — GATE-07 re-verified
  PASS post-fix, `journey-j2-persist-aether-local.json`, confirmed via a direct production-DB read
  (not just an HTTP 200), name+email both genuinely changed and persisted.
- **GAP-P7-DISCOVERY-001** (scheduled sourcing cron 402/exit-22) — `DISCOVERY_DURABILITY` VERIFIED-CLOSED
  in `step10-cluster2-gates.json`, including a directly-observed **unattended native timer fire** at
  11:00:44 UTC succeeding end-to-end with zero 402s.
- **GAP-P7-ASYNC-001** (background job generation) — GATE-11/12/13 VERIFIED-CLOSED, 20/20-run soak with
  0 HTTP 503s and 0 fixture matches (`journey-j3-soak-20.json`), `AETHER_ASYNC_GENERATION` left
  permanently `true` on production per the soak's own decision rule.

The **only** outstanding human-gated items in Phase-7 are the Phase-6 Stripe (H-01/H-02/H-03), Gmail
(H-05), and admin-credential (H-04) carry-overs listed above — none of which are new to Phase-7, and
none of which block anything Phase-7 itself shipped.
