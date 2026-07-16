# Aether — Subscription Terms of Service

**Status:** Describes the subscription/billing terms for the system as actually built and
unit-tested (2026-07-16, Cluster D — `GAP-P6-BILL-001/002`, `GAP-P6-PRICING-001`, all
`FIX-READY-MERGED`, `merged_sha 80ff45d`). **Live Stripe billing is not yet active in
production** — see §7. This is the operator-facing source of truth for subscription terms;
reconcile with the existing live `/terms` page (`apps/web/src/app/terms/page.tsx`, last updated
2026-07-11, Delaware governing law, no mention of subscriptions) before publishing either as final.

**Production:** https://5cb5f0620.abacusai.cloud

---

## 1. Plans and pricing (AUD, GST-inclusive)

All prices are in Australian dollars and **include** the 10% Goods and Services Tax (GST). These
are the ratified tiers, seeded verbatim into the `Plan` table (`apps/api/app/repositories/billing.py::RATIFIED_PLANS`):

| Plan | Monthly (incl. GST) | Annual (incl. GST) | Agent runs / month | Model access |
|---|---:|---:|---:|---|
| **Free** | A$0 | — | 5 | Light tier |
| **Starter** | A$19 | A$179 | 30 | Light + Standard tier |
| **Pro** | A$39 | A$359 | 100 | Light + Standard tier |
| **Power** | A$69 | A$649 | 300 | Full model access |

Annual billing is charged once per year and is cheaper per month than paying monthly (roughly
two months free relative to the monthly rate).

### GST disclosure

Prices above are **GST-inclusive**. The GST component of any price is computed as:

```
gst = round(total / 11, 2)
net (ex-GST) = total - gst
```

For example, the Starter monthly price of A$19.00 breaks down as GST A$1.73 / net A$17.27. This
computation is done server-side (`GET /api/billing/plans` returns `{total, gst, net}` for every
plan) — the app, not the customer, does the tax math, and the same figure appears on invoices.

**ABN / business registration:** tax invoices require a registered Australian Business Number.
**[Operator ABN]** and **[Business Name]** are placeholders the operator must supply before GST
invoices are legally complete. Automated Stripe Tax is deliberately **not** enabled at launch
(`STRIPE_AUTOMATIC_TAX` defaults to `false`) — for a single-jurisdiction, single-rate (10% GST)
product the manual `round(total/11,2)` calculation above is fully sufficient and Stripe Tax's
subscription fee (from A$140/month) is not justified at current volume. This may be revisited if
the operator later sells into a second tax jurisdiction.

---

## 2. Billing cycle

- **Monthly** or **annual**, selected at checkout; a plan can bill under either interval
  (`billingInterval` on the `Subscription` record).
- Payment is processed by Stripe; accepted methods are **card** (instant confirmation) and
  **au_becs_debit** (Australian direct debit — asynchronous; the subscription shows
  pending/processing until Stripe confirms the debit by webhook, never assumed active on checkout
  return).
- The current billing period (`currentPeriodStart`/`currentPeriodEnd`) and renewal are managed
  entirely by Stripe and synced into Aether via webhook (`checkout.session.completed`,
  `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`).
  Webhook processing is idempotent — each Stripe event is processed exactly once even if Stripe
  retries delivery.

---

## 3. Agent-run quota model

Each plan carries a monthly quota of **metered agent runs** — runs that invoke the LLM and
therefore cost money: **tailor** (resume tailoring), **coverLetter**, **storyExtractor**, and
**emailAgent**. Deterministic agents that make no LLM call — **scout**, **fitScorer**, **matcher**,
**supervisor** — are unlimited and never counted against your quota, because they incur no cost.

- Quota resets automatically at the start of each billing period (rolled over atomically on the
  first run request after the period ends — no manual reset needed).
- Each plan also carries a USD safety spend cap (separate from the AUD subscription price — the
  LLM provider bills in US dollars) so that unusually expensive usage within a period cannot run
  away; see `docs/subscription/admin-guide.md` §4–5 for exactly how that is enforced and why spend
  is shown in USD rather than AUD.
- **When your run quota or spend cap is exhausted, the next metered agent-run request returns
  HTTP 429** with a machine-readable reason (`quota_exceeded` or `spend_cap_exceeded`) and the
  numbers needed to build an "upgrade your plan" prompt (`runsUsed`, `runsAllowed`, `resetsAt`).
  No metered run is silently allowed through over quota, and no run that fails or errors counts
  against your quota (it is refunded automatically).

---

## 4. Cancellation

Subscriptions are managed through the **Stripe Billing Portal** (`POST /api/billing/portal` /
"Manage billing" in the dashboard). From the portal you can:
- Change plan (upgrade/downgrade),
- Update payment method,
- Cancel the subscription.

**Cancellation takes effect at the end of the current billing period** — you keep the plan's
access (run quota, model tier) through `currentPeriodEnd`; there is no pro-rated mid-period
cutoff. When the period ends, Stripe's `customer.subscription.deleted` webhook fires and Aether
automatically downgrades the account to the **Free** plan with the Free run quota and spend cap.

If you have never subscribed to a paid plan (no Stripe customer on file), the billing portal
endpoint returns an honest 409 rather than a broken portal link.

---

## 5. Refunds

**No automated refund flow is built.** There is no self-service "request a refund" button and no
refund-issuing endpoint in the API. Refund requests, if the operator chooses to honor any, must be
handled manually by the operator directly in the Stripe dashboard. **[Operator: state your refund
policy here — e.g., pro-rated refunds within X days, or no refunds — before publishing this
document publicly.]** This section is a deliberate placeholder, not a claim that refunds are or are
not available.

---

## 6. Acceptable use

By subscribing, you agree not to:
- Circumvent the agent-run quota or spend cap by any technical means.
- Share your account credentials or a single paid subscription across multiple distinct users.
- Use the service to submit fraudulent, misleading, or spam job applications.
- Misrepresent your qualifications or experience in any AI-generated resume, cover letter, or
  interview material.
- Attempt to scrape, reverse engineer, or extract data from the platform beyond the functionality
  it provides through its own UI/API.

Violation may result in suspension (an admin can suspend an account, which returns 403 on all of
that account's authenticated routes until lifted) or termination, at the operator's discretion.

---

## 7. Current billing status — what is live vs. pending operator action

**Built, unit-tested, and deployed:** the `Plan`/`Subscription`/`UsageQuota`/`StripeEvent` schema,
the `/api/billing/*` endpoints (plans, checkout, webhook, subscription status, portal), the
`/pricing` page, GST computation, and quota/spend-cap enforcement — all reviewed and passing
against a **mocked** Stripe SDK.

**Not yet live, pending the operator:** real payment processing. Going live requires the operator
to:
1. Create a Stripe account and supply `STRIPE_SECRET_KEY`.
2. Create the Starter/Pro/Power products and prices in Stripe (monthly + annual each) and supply
   the resulting Price IDs.
3. Register the webhook endpoint (`/api/billing/webhooks/stripe`) in Stripe and supply
   `STRIPE_WEBHOOK_SECRET`.
4. Enable `card` and `au_becs_debit` payment methods in the Stripe dashboard.
5. Supply an ABN and decide on Stripe Tax (recommendation: leave off at launch, §1).
6. Activate the Stripe Billing Portal configuration.

Until these are supplied, `POST /api/billing/checkout` and `/portal` fail with an honest
"Stripe not configured" error rather than pretending to process a payment — see
`docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md` for the full checklist and how each item is verified
once provided.
