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
