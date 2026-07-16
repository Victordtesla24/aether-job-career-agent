# PHASE 6 — BLOCKED-ON-HUMAN checklist (§2)

Consolidated, emitted once by the orchestrator per §2. The swarm builds and unit-tests **everything**
below with mocked dependencies and deploys the code; these items are the **live verification round-trips
the swarm cannot perform itself** (creating external accounts, clicking OAuth consent, provisioning
secret keys). Human-gated gates NEVER close by inference and are NEVER faked (§0.5).

Only **Cluster D** (billing) halts pending these; all other clusters proceed in parallel.

## What the human must provide

| # | Prerequisite | Unblocks gates | Action required | Where it goes |
|---|---|---|---|---|
| 1 | Stripe **test** secret key `STRIPE_SECRET_KEY` | GATE-13/14/16/17 | Stripe → test mode → Developers → API keys | server `.env` (name only; never commit) |
| 2 | Stripe **webhook** signing secret `STRIPE_WEBHOOK_SECRET` | GATE-13/14/33 | Register endpoint `https://5cb5f0620.abacusai.cloud/api/billing/webhooks/stripe` in Stripe → copy signing secret | server `.env` |
| 3 | Stripe **Price IDs** (1 monthly + 1 annual per paid tier: Starter/Pro/Power) | GATE-13 | Create Products + Prices in Stripe test mode | server `.env` (`STRIPE_PRICE_*`) |
| 4 | **ABN** + Stripe Tax enabled | GATE-15/16 | Enable Stripe Tax in dashboard; enter ABN | Stripe dashboard |
| 5 | **2 test Gmail accounts** + Google OAuth consent | GATE-05 | Add 2 Gmail accounts as test users on the existing Google OAuth consent screen; click "Connect Gmail" for each on `/dashboard/email` | Google Cloud console + in-app consent |
| 6 | **Admin credential rotation** env vars | GATE-17/31 | After admin panel deploys: set `AETHER_ADMIN_EMAIL` + `AETHER_ADMIN_PASSWORD_HASH` (bcrypt), rotate off admin/admin123 | server `.env` |
| 7 (optional, recommended) | **Adzuna AU API creds** `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | Strengthens GATE-07 volume margin | Free registration at https://developer.adzuna.com/ (needs an email account → human). Absent: adapter skips honestly, GATE-07 met by ATS+public APIs but with a thin/decaying fresh margin (see risk below) | server `.env` |

## Not awaited (resolved autonomously)

- **Anthropic OAuth (was GATE-04 human item):** verified PROHIBITED for third-party apps
  (`anthropic-oauth-verification.md`). Per ADR-P6-OAUTH the swarm ships API-key-only + a disabled,
  flag-gated OAuth stub with honest "coming soon" copy. **GATE-04 = CONDITIONALLY-CLOSED** with the
  verification artifact — no human consent is awaited (consumer-subscription OAuth in a third-party app
  would violate Anthropic's ToS, so it must not be built as active).
- **GATE-02 (LLM mode live/auto):** already satisfied — production runs `AETHER_LLM_MODE=auto` on
  OpenRouter (probe-03). No Anthropic API key needed to pass this gate.

## How verification proceeds once each item lands

- **1–4 (Stripe):** re-run the billing E2E — checkout with test card `4242…`, observe
  `checkout.session.completed` webhook, assert transaction-safe idempotency (replayed event creates no
  second entitlement), GST line `round(total/11,2)`, ABN on invoice, cancel → `subscription.deleted`
  removes entitlement. Closes GATE-13/14/15/16/33 + confirms GATE-34 backfill.
- **5 (Gmail):** connect 2 accounts, assert `GET /emails/accounts` returns 2 independent-token rows,
  account-filtered vs unified views. Closes GATE-05.
- **6 (admin rotation):** admin/admin123 login shows `isAdmin=false`; env admin shows `isAdmin=true`.
  Closes GATE-31 + completes GATE-17.

**Status:** emitted 2026-07-16. Cluster D billing CODE proceeds now (mocked Stripe); its live-verify
gates hold at BLOCKED-ON-HUMAN until items 1–4 are provided.

## GATE-07 sourcing-volume RISK (honest disclosure, not a blocker)
The sourcing reviewer flagged the fresh-jobs margin as time-sensitive: at snapshot the compliant
sources yielded 40 relevant / 29 fresh(≤30d) jobs (Greenhouse/Lever/Ashby), but Lever sits at
exactly 5 fresh, Adzuna contributes 0 without item-7 creds, and several postings are already
20-28 days old — so the ≥25 margin can erode within days. This is disclosed honestly rather than
masked. Mitigation: (a) production QA re-probes LIVE volume at gate-closure time (not the snapshot);
(b) enabling item-7 Adzuna creds adds durable AU source diversity; (c) if live volume dips below 25,
a follow-up broadens the (real, verified) ATS token set — counts are never fabricated to pass GATE-07.
