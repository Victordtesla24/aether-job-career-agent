# LAUNCH-READY — Items blocked on a human operator (spec §11)

Only credentials/actions that genuinely require the operator are listed here.
Everything else in the launch-ready campaign is agent-executable and tracked
in `docs/delivery/MODELS-LIVE-GAPS.json` + `LAUNCH-READY-STATE.json`.

## 1. Live Stripe payment completion (W-E §7.2 — CONDITIONALLY-CLOSED)

**What is already verified on prod (agent-side, 2026-07-24):**
- `GET /billing/plans` — AUD, GST-inclusive, 4 plans.
- `POST /billing/checkout` — mints real live-mode `cs_live_…` Stripe Checkout sessions.
- `POST /billing/webhooks/stripe` — rejects unsigned and forged-signature calls (400).
- `GET /billing/entitlement` / `GET /billing/subscription` — entitlement + quota live.
- `POST /billing/portal` — mints real live-mode Stripe customer-portal sessions.

**What only you can do (live mode charges a real card):**
1. Open `https://5cb5f0620.abacusai.cloud/pricing`, pick a paid plan, complete
   the Stripe Checkout with a real card (or drive a subscription with a
   test clock from the Stripe dashboard).
2. Confirm the `checkout.session.completed` webhook arrives (Stripe dashboard →
   Developers → Webhooks → recent deliveries → 2xx) and that
   `GET /billing/entitlement` flips to the purchased plan.
3. From Settings → Billing → "Manage subscription", exercise cancel and
   downgrade in the Stripe-hosted portal; confirm `cancelAtPeriodEnd` /
   plan change reflects in `GET /billing/subscription`.
4. If any step fails, file it in `docs/delivery/MODELS-LIVE-GAPS.json`
   (category `quality`, screen `settings`/`pricing`).

Until then the two flows above carry status **CONDITIONALLY-CLOSED** in the
ledger — everything machine-verifiable around them is green.

## 2. Adzuna AU credentials — unlocks Australian job volume (RT-003, 2026-07-24)

**Why this matters:** discovery currently persists ~0 new jobs/day. The
keyless ATS sources (greenhouse/lever/ashby/workable/remotive/remoteok) are
saturated at ~37 mostly-global postings, wellfound is externally 403-blocked,
and direct Seek scraping is prohibited by its ToS (ADR-P6-SEEK). The
ToS-compliant path to AU listings (including many roles advertised on Seek)
is the **licensed Adzuna AU aggregator** — the adapter is fully implemented
and production-ready (`apps/api/app/services/discovery/adzuna_adapter.py`);
it is skipped ONLY because the free-tier credentials are absent. LinkedIn
has no lawful public jobs API and stays a disclosed "unavailable" source.

**What only you can do (account registration):**
1. Register a free developer account at `https://developer.adzuna.com/`
   (Signup → confirm email → create an application).
2. Copy the issued **Application ID** and **Application Key**.
3. Add to `/home/ubuntu/github_repos/aether-job-career-agent/.env`:
   `ADZUNA_APP_ID=<id>` and `ADZUNA_APP_KEY=<key>` (never commit them).
4. Restart services: `sudo systemctl restart aether-api aether-worker` —
   or simply tell the agent the keys are in place and it will restart+verify.
5. Verify: the next discovery cron (every 30 min, `/var/log/aether/discovery.log`)
   shows `"source":"adzuna"` with `status:"ok"` and non-zero `fetched`;
   AU-located jobs appear on the Jobs screen.

Until then AU job volume carries status **CONDITIONALLY-CLOSED**: the
adapter, pagination, relevance filter, and per-source disclosure are all
implemented and tested; only the operator-held key is missing.
