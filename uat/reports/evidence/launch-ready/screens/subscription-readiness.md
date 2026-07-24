# W-E §7.2 — Subscription-readiness walk (production)

Audited: 2026-07-24 (AEST) · prod `https://5cb5f0620.abacusai.cloud` · admin session (live Stripe mode)

## Chain walked

| Step | Endpoint / surface | Result | Verdict |
|---|---|---|---|
| Pricing | `GET /billing/plans` (+ `/pricing` UI, audited in `pricing/audit.md`) | 200 — `currency: AUD`, `gstIncluded: true`, 4 plans (Free non-purchasable, Starter/Pro/Elite purchasable), monthly+annual price breakdowns | **VERIFIED** |
| Checkout session | `POST /billing/checkout {planId:"starter",interval:"month"}` | 200 — real `checkout.stripe.com/c/pay/cs_live_…` session URL minted (live mode) | **VERIFIED** (session minting) |
| Checkout validation | `POST /billing/checkout` with wrong shape | 422 with explicit field error (`planId` required) — honest, no dead end | **VERIFIED** |
| Webhook | `POST /billing/webhooks/stripe` unsigned → 400; forged `Stripe-Signature` → 400 `{"detail":"Invalid signature"}` | Signature enforcement active; no unauthenticated state mutation | **VERIFIED** (rejection path) |
| Entitlement | `GET /billing/entitlement` | 200 — `active_paid: true`, plan id/status, `requiresSubscription: true` | **VERIFIED** |
| Quota | `GET /billing/subscription` → `quota` | 200 — runsUsed/runsAllowed (50/100), spend cap USD, `periodEnd` | **VERIFIED** |
| Portal (cancel/downgrade surface) | `POST /billing/portal` | 200 — real `billing.stripe.com/p/session/live_…` portal session URL minted | **VERIFIED** (session minting) |

## CONDITIONALLY-CLOSED (human-gated, per spec §11)

The steps below require completing a **real live-mode payment** (or operating
the Stripe dashboard), which charges an actual card and is operator-only:

1. **Checkout completion → `checkout.session.completed` webhook → entitlement flip** —
   session minting and webhook signature enforcement are verified above; the
   live end-to-end flip needs one real transaction (or a Stripe test-clock in
   the dashboard).
2. **Cancel / downgrade via the Stripe-hosted portal** — portal session mints;
   executing a cancel requires an active live subscription owned by a real card.

Operator instructions: see `docs/delivery/LAUNCH-READY-BLOCKED-ON-HUMAN.md`.

## Honest-state checks

- No mock/stub billing code on the walked paths — sessions are real Stripe live objects.
- Failure states are explicit (422 field errors, 400 invalid-signature), no silent dead ends.
- Settings → Billing renders plan, price (AUD via `formatAud`), next billing date (en-AU after this wave), quota + reset date, and a working "Manage subscription" portal handoff.
