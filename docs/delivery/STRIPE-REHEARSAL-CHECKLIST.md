# STRIPE-REHEARSAL-CHECKLIST — real-money dress rehearsal

**Status:** Proposed procedure, not yet executed by this document.
**Production:** `https://5cb5f0620.abacusai.cloud`
**Stripe account:** `acct_1TvSlMRy5o5QDotA` — **livemode**. There is no test-mode rehearsal option
described here; every step below charges/refunds a real card. This is deliberate — the gap
this checklist closes can only be closed with a real charge (see §0).
**Author:** documentation pass, read-only against the repo. No code was changed, no command was
run, no charge was made while writing this document.

---

## 0. Why this rehearsal exists (read this first)

`docs/delivery/SUBSCRIPTION-PRODUCTION-AUDIT-2026-08-03.md` §2 established, as of 2026-08-03, that
**zero real Stripe-delivered `checkout.session.completed` or `customer.subscription.*` event has
ever landed on this production account.** The only paid `"Subscription"` row that has ever existed
(`sarkar.vikram@gmail.com`, `planId='pro'`, `status='active'`, `stripeSubscriptionId` = `NULL`) was
created by locally-crafted webhook payloads whose event ids (`evt_test_*`) do not match Stripe's
real id format — not by a real purchase. Stripe's own event log for this account shows 6+ real
`checkout.session.expired` events (abandoned attempts) and, at last audit, **zero** real
`checkout.session.completed` or `customer.subscription.created` events, ever.

This checklist exists to close exactly that gap: run one real card through the real
Checkout → webhook → entitlement → refund path, end to end, and record what actually happens —
not what the code review says should happen.

---

## 1. Ground truth — the code paths this rehearsal exercises

All routes below are in `apps/api/app/routers/billing.py`, mounted at `/billing`; the public
contract is `/api/billing/...` (nginx `location /api/` in `deploy/5cb5f0620.conf` rewrites
`/api/(.*)` → `/$1` and proxies to `127.0.0.1:8000`).

| Route | Line | Purpose |
|---|---|---|
| `GET /billing/plans` | `billing.py:81` | public plan catalog + GST breakdown |
| `POST /billing/checkout` | `billing.py:121` | creates a Stripe Checkout Session (rate-limited 5/hr/user) |
| `POST /billing/webhooks/stripe` | `billing.py:210` | Stripe-signed webhook receiver |
| `GET /billing/subscription` | `billing.py:766` | current plan/status/quota for the logged-in user |
| `GET /billing/entitlement` | `billing.py:806` | `active_paid` + `requiresSubscription` (drives the dashboard paywall) |
| `POST /billing/portal` | `billing.py:831` | Stripe Billing Portal session (rate-limited 10/hr/user) |
| `POST /billing/admin/refund` | `billing.py:879` | admin-only refund of the user's latest paid charge |

**Plan catalog** (seeded in `apps/api/migrations/0022_billing.sql:104-110` and mirrored in
`apps/api/app/repositories/billing.py`): `free` (A$0, 5 runs), **`starter` (A$19/mo, A$179/yr, 30
runs) — the smallest purchasable plan, use this one for the rehearsal**, `pro` (A$39/mo, 100 runs),
`power` (A$69/mo, 300 runs). `GET /billing/plans` returns each plan's GST breakdown pre-computed by
`gst_breakdown()` (`billing.py:29`, `gst = round(total/11, 2)`, GST backed out of a GST-inclusive
price).

**Stripe Price ID resolution** (`_resolve_price_id`, `billing.py:110-118`): first reads
`Plan.stripePriceIdMonthly` / `Plan.stripePriceIdAnnual` from the DB row (migration comment:
"filled by human after Stripe setup" — `0022_billing.sql:30`); if that column is empty, falls back
to an env var named `STRIPE_PRICE_<PLANID_UPPER>_<MONTH|YEAR>` — for the Starter monthly plan that
is **`STRIPE_PRICE_STARTER_MONTH`**. Do not print the value of this or any Stripe env var; only
confirm it is set.

**Webhook signature verification**: `stripe_webhook()` (`billing.py:210`) reads the raw request body
before any Pydantic parsing, then verifies via `stripe_gateway.construct_event()`
(`apps/api/app/services/stripe_gateway.py`), which calls `stripe.Webhook.construct_event(payload,
sig_header, secret)`. The secret comes from env var **`STRIPE_WEBHOOK_SECRET`**
(`stripe_gateway.py:33-34`). The Stripe secret key comes from env var **`STRIPE_SECRET_KEY`**
(`stripe_gateway.py:25`). If either is unset, the relevant endpoint returns an honest 503 — it never
fabricates a checkout URL or accepts an unverifiable webhook (`billing.py:147-152`, `221-226`).
**`.env.example` in the repo root has zero `STRIPE_*` entries** — there is no committed template to
check names against; confirm the live values are set on the running `aether-api` process's own
environment, not by reading `.env`.

**Webhook idempotency**: each event is inserted into `"StripeEvent"` (id = Stripe's own event id,
`ON CONFLICT ("id") DO NOTHING`) inside the *same* transaction as its side effects
(`billing.py:236-269`) — a handler failure rolls back the whole transaction (including the
`StripeEvent` insert) so Stripe retries; a replayed event id is a no-op.

**Events this deployment handles** (`_dispatch_stripe_event`, `billing.py:282-299`), and the exact
DB write each one makes:

| Event | Handler | DB effect |
|---|---|---|
| `checkout.session.completed` | `_handle_checkout_completed` (`billing.py:395`) | upserts `"Subscription"` (status → `active`), resets `"UsageQuota"` for the new plan |
| `customer.subscription.updated` | `_handle_subscription_updated` (`billing.py:428`) | updates `"Subscription"` status/period/plan, re-derives plan from the Stripe price id |
| `customer.subscription.deleted` | `_handle_subscription_deleted` (`billing.py:555`) | `_revoke_to_free(cancel_stripe=False)` — downgrade to Free |
| `invoice.payment_failed` | `_handle_payment_failed` (`billing.py:565`) | `"Subscription".status` → `past_due` (still entitled during dunning) |
| `invoice.paid` | `_handle_invoice_paid` (`billing.py:611`) | on renewal reasons only, resets `"UsageQuota".runsUsed`/`spendUsedUsd` to 0 |
| `charge.refunded` | `_handle_charge_refunded` (`billing.py:689`) | on a **full** refund, `_revoke_to_free(cancel_stripe=True)` |
| `charge.dispute.created` | `_handle_dispute_created` (`billing.py:704`) | same revoke-to-free + cancel |
| `customer.subscription.trial_will_end` | `_handle_trial_will_end` (`billing.py:492`) | stamps `"Subscription".trialEndNotifiedAt` |

**Tables to check with exact names** (all defined in `apps/api/migrations/0022_billing.sql`, DDL
also executed lazily by `_ensure_billing_tables()`):

- `"Plan"` — `id, name, priceAudMonthly, priceAudAnnual, runsPerMonth, modelTier,
  spendCapUsdMonthly, stripeProductId, stripePriceIdMonthly, stripePriceIdAnnual, active, sortOrder`
- `"Subscription"` — `id, userId, planId, status, billingInterval, stripeCustomerId,
  stripeSubscriptionId, currentPeriodStart, currentPeriodEnd, cancelAtPeriodEnd,
  trialEndNotifiedAt`. No FK to `"User"` by design (text `userId`).
- `"UsageQuota"` — `userId, planId, periodStart, periodEnd, runsAllowed, runsUsed, spendCapUsd,
  spendUsedUsd`
- `"StripeEvent"` — `id` (Stripe event id, PK), `type, status, payloadJson, receivedAt,
  processedAt`
- `"AdminAuditLog"` — `actorUserId, action, targetType, targetId, detailJson, createdAt` (the
  refund step writes `action='billing_refund'` here)

**Refund mechanics** (`POST /billing/admin/refund`, `billing.py:879-949`): admin-only, body
`{"userId": ...}` or `{"email": ...}`. Looks up the customer's latest paid, non-refunded charge via
`stripe_gateway.latest_paid_charge()`, issues a **full** Stripe refund (`stripe.Refund.create`, no
partial-amount parameter exists in this code path), then unconditionally downgrades the user to Free
and cancels the live Stripe subscription (`_revoke_to_free(cancel_stripe=True)`), and writes one
`"AdminAuditLog"` row (`action="billing_refund"`, `detailJson` containing `chargeId`, `refundId`,
`refundStatus`).

**GST / invoice wording**: prices are marketed GST-inclusive; `GET /billing/plans` returns
`{"currency":"AUD","gstIncluded":true,...}` with each plan's `{total, gst, net}` computed by
`gst_breakdown()`. Per `docs/delivery/SUBSCRIPTION-PRODUCTION-AUDIT-2026-08-03.md` §6 (2026-08-03),
the live Stripe account's `GET /v1/tax/settings` showed `status: "active"`, and `GET
/v1/tax/registrations` showed **one active AU registration** (`active_from` 2026-07-21) — this is
in apparent tension with the operator-supplied framing that the business is "an ABN sole trader, not
GST-registered." **This checklist does not resolve that tension** — it is flagged in §5 below as the
thing to adjudicate from the *actual* invoice PDF produced by this rehearsal, not from either
document's prior claims. There is no in-app invoice-retrieval endpoint (`apps/api` has no
`stripe.Invoice` call and no `hosted_invoice_url`/`invoice_pdf` handling) — the invoice only exists
Stripe-side, reached via the customer's emailed receipt or the Billing Portal session created by
`POST /billing/portal` (`billing.py:831`, which calls `stripe_gateway.create_portal_session`).

**Click-path** (frontend, `apps/web/src/app/`): `/signup` → `POST /api/auth/register` → redirect to
`/login?registered=1` → `/login` → `/pricing` (reads `GET /billing/plans`, `POST /billing/checkout`
on plan click, browser redirected to the returned `checkoutUrl`) → Stripe-hosted Checkout → returns
to `success_url = /dashboard/settings?checkout=success` → `dashboard/settings/settings-client.tsx`
polls `GET /billing/subscription` and only shows "active" once the poll confirms it (it does not
claim success from the redirect alone) → first tailored résumé at `apps/web/src/app/dashboard/resume/
page.tsx`, which drives `POST /agents/tailor/run` (`apps/api/app/routers/agents.py:3168`).

---

## 2. Roles

- **Operator (Vikram) ONLY** — every step marked **[OPERATOR — card required]**. Nobody and nothing
  else can enter real card data; this is deliberate and cannot be scripted around.
- **Agent/automation** — every step marked **[AGENT]** can be done by curl/psql/Stripe API reads on
  the operator's behalf, before or after the card step.

---

## 3. Pre-flight checks (before touching a real card)

1. **[AGENT] Webhook endpoint reachable and correctly configured.**
   `GET /v1/webhook_endpoints` (Stripe API, `sk_live_*` key, never print the key) and confirm:
   - exactly one endpoint with `url == "https://5cb5f0620.abacusai.cloud/api/billing/webhooks/stripe"`
   - `status: "enabled"`, `livemode: true`
   - `enabled_events` is a superset of every branch in `_dispatch_stripe_event` (§1's event table)
   This was true as of 2026-08-03 per `SUBSCRIPTION-PRODUCTION-AUDIT-2026-08-03.md` §7 — re-confirm
   it live rather than trusting that record, since config can drift.
2. **[AGENT] Price IDs configured for the plan under test.** Confirm (existence only, never
   values) that either `Plan.stripePriceIdMonthly` is populated for `id='starter'`
   (`SELECT "stripePriceIdMonthly" IS NOT NULL FROM "Plan" WHERE "id"='starter'`) **or** the env var
   `STRIPE_PRICE_STARTER_MONTH` is set on the running `aether-api` process. If neither, `POST
   /billing/checkout` will 400 with "This plan is not yet available for purchase" (`billing.py:142-146`)
   — fix this before the operator ever touches a card.
3. **[AGENT] Stripe SDK configured.** Confirm `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are both
   set on the live process (existence only). `stripe_gateway.is_configured()` gates `/billing/checkout`
   and `/billing/portal`; a missing secret key yields a 503, not a fabricated URL.
4. **[AGENT] Confirm today's plan/price agreement.** `GET /api/billing/plans` (unauthenticated) →
   confirm `starter.monthly.total == 19.0` (or whatever the current seed says — read it fresh, do not
   assume the numbers in this document are still current) and cross-check against the live Stripe
   `Price` object for the resolved price id (`GET /v1/prices/{id}`) — `currency: "aud"`,
   `unit_amount` matching, `active: true`, `livemode: true`, `tax_behavior: "inclusive"`.
5. **[AGENT] Pick/confirm the rehearsal identity.** A fresh email the operator controls (so refund
   confirmation and any Stripe receipt emails are visible). Do not reuse the existing
   `sarkar.vikram@gmail.com` production Pro row from the 2026-08-03 audit — that row already has
   `stripeCustomerId=cus_UvLRWZMJc6iGX2` but `stripeSubscriptionId=NULL`, i.e. an inconsistent state
   from the prior locally-crafted webhook history; starting fresh avoids conflating this rehearsal's
   evidence with that pre-existing anomaly.
6. **[AGENT] Snapshot before-state.** `SELECT * FROM "Subscription" WHERE "userId"=<new user id>`
   (expect: no row, or a Free row from signup backfill) and `SELECT * FROM "StripeEvent" ORDER BY
   "receivedAt" DESC LIMIT 5` (expect: nothing new yet) so the after-state diff is unambiguous.

---

## 4. The rehearsal, step by step

### Step A — Signup [AGENT or OPERATOR]
`POST /api/auth/register` with the rehearsal email → expect `201`. Then `POST /api/auth/login` →
expect `200` with an access token. **Evidence to capture:** the register/login response bodies
(status codes + non-sensitive fields), timestamp.

### Step B — Confirm the paywall reality before paying [AGENT]
`GET /api/billing/entitlement` as the new user → expect `active_paid: false`,
`requiresSubscription: true` (per `SUBSCRIPTION-PRODUCTION-AUDIT-2026-08-03.md` §1/§9, the free tier
is currently gated by `AETHER_REQUIRE_PAID_SUBSCRIPTION=true` — this means the "first value" step
later in this rehearsal is **only reachable after the Checkout completes**, not before). Record this
so the rehearsal isn't misread as proving the Free tier works — it deliberately doesn't, by current
policy.

### Step C — Real Stripe Checkout **[OPERATOR — card required, ~2 minutes]**
Log in as the rehearsal user in a real browser, go to `/pricing`, click **Starter** (the smallest
paid plan — A$19/month at last check, confirm the live number on the page). This calls `POST
/billing/checkout`; the operator is redirected to the Stripe-hosted Checkout page. **Only the
operator does this part**: enter a real card, complete the purchase.

**Evidence to capture:**
- The Checkout Session id (`cs_live_...`) — visible in the redirect URL or captured via `GET
  /v1/checkout/sessions?limit=1` immediately after.
- Stripe event log: `GET /v1/events?type=checkout.session.completed&limit=1` — the **event id**
  (`evt_...`), confirm its `data.object.id` matches the session id above, and confirm its id format
  is a genuine Stripe id (this is exactly the check that failed in the 2026-08-03 audit's synthetic
  rows).
- `GET /v1/events?type=customer.subscription.created&limit=1` — event id, and the `data.object.id`
  (`sub_...`).

### Step D — Confirm the webhook actually landed and wrote the DB [AGENT]
Within a few seconds of Step C:
1. `SELECT id, type, status, "receivedAt", "processedAt" FROM "StripeEvent" WHERE "id" IN
   (<event ids from Step C>)` — expect `status='processed'` for both, `processedAt` populated.
2. `SELECT "userId","planId","status","stripeCustomerId","stripeSubscriptionId",
   "currentPeriodEnd" FROM "Subscription" WHERE "userId"=<rehearsal user id>` — expect `planId='starter'`,
   `status='active'`, `stripeSubscriptionId` populated with a real `sub_...` id (this is the exact
   field that was `NULL` in the only pre-existing paid row per the 2026-08-03 audit — its being
   correctly populated here is the primary thing this rehearsal proves).
3. `SELECT "runsAllowed","runsUsed","spendCapUsd" FROM "UsageQuota" WHERE "userId"=<rehearsal user
   id>` — expect `runsAllowed=30` (Starter), `runsUsed=0`.
4. `GET /api/billing/subscription` as the user → expect the same plan/status back over the API, not
   just in the DB.
5. `GET /api/billing/entitlement` → expect `active_paid: true` now.

### Step E — Onboarding / dashboard access [OPERATOR or AGENT via Playwright]
Load `/dashboard` as the rehearsal user → expect the paywall screen is gone (per ADR-MV-02, the
`SubscriptionGate` at `apps/web/src/app/dashboard/layout.tsx` should now pass). Screenshot the
dashboard landing and the Settings → Billing panel showing "Starter" and the correct run count.

### Step F — First value: one tailored resume [OPERATOR or AGENT via Playwright]
Upload a résumé (`POST /resumes/upload`), then run one tailoring pass from
`apps/web/src/app/dashboard/resume/page.tsx`, which drives `POST /agents/tailor/run`
(`apps/api/app/routers/agents.py:3168`). **Evidence to capture:** the run's response, the resulting
`"AgentRun"` row's `costUsd`, and `GET /api/billing/subscription` afterward showing `runsUsed`
incremented by exactly 1 (the metering behavior documented in
`docs/delivery/ADR-F03-UPLOAD-QUOTA.md` for the sibling upload-quota defect — confirm tailoring
itself increments correctly, since that ADR's fix only concerned the *upload* auto-dispatch, not
tailoring).

### Step G — Refund **[OPERATOR authorizes; AGENT executes the API call]**
The operator decides to issue the refund (real money moving back); the actual call can be made by
either party since it's an authenticated admin API call, not a card-entry step:
`POST /billing/admin/refund` with `{"userId": <rehearsal user id>}` (admin credentials required).

**Evidence to capture:**
- Response body: `refundId`, `status`, `chargeId`, `planId` (expect `"free"`).
- `GET /v1/refunds/{refundId}` (Stripe) → confirm `status: "succeeded"`, `amount` matches the
  Starter charge exactly (this is a full refund only — there is no partial-refund code path in
  `admin_refund`).
- `SELECT * FROM "AdminAuditLog" WHERE "action"='billing_refund' AND "targetId"=<rehearsal user id>
  ORDER BY "createdAt" DESC LIMIT 1` — confirm the row exists with the matching `chargeId`/`refundId`
  in `detailJson`.
- `SELECT "planId","status","stripeSubscriptionId" FROM "Subscription" WHERE "userId"=<rehearsal
  user id>` — expect `planId='free'`, subscription cancelled.
- Wait for (or manually trigger a re-check of) the `charge.refunded` webhook —
  `_handle_charge_refunded` (`billing.py:689`) should independently reach the same
  `_revoke_to_free(cancel_stripe=True)` state; confirm the `"StripeEvent"` row for this event also
  shows `status='processed'` so both the admin-initiated path and the webhook-confirmed path agree.

### Step H — Invoice / GST wording adjudication [AGENT retrieves; OPERATOR + a human decision]
Retrieve the real invoice from this rehearsal's charge: `GET /v1/invoices?customer=<customer_id>` →
find the invoice tied to the Starter charge → `GET /v1/invoices/{id}` for the `hosted_invoice_url`
and PDF. **Read the actual wording Stripe put on it** — do not assume either "GST-registered" or
"ABN sole trader, not GST-registered" framing is correct; the 2026-08-03 audit found the live Stripe
tax settings showing an active AU tax registration, which is the kind of fact that should be
reconciled against the operator's actual ABN/GST-registration status *from the real document*, not
from either prior doc's claim. This is a business/legal adjudication for the operator, informed by
what the PDF actually says — flag any mismatch between the invoice wording and the operator's actual
GST-registration status as a follow-up item, not something this checklist resolves on its own.

---

## 5. Rollback / cleanup

1. Confirm the rehearsal user ends on `planId='free'`, `status` reflecting a cancelled Stripe
   subscription (Step G already does this).
2. In Stripe: confirm the subscription (`sub_...`) shows `status: "canceled"` and there are no
   further scheduled invoices for it (`GET /v1/subscriptions/{id}`).
3. Do not delete the `"StripeEvent"`, `"Subscription"`, or `"AdminAuditLog"` rows this rehearsal
   created — they are the evidence. If a non-production rehearsal account is undesirable to keep
   long-term, that is a separate, later data-retention decision, not part of this checklist.
4. Re-run `GET /api/billing/entitlement` for the rehearsal user one final time and confirm
   `active_paid: false` — i.e., the account is left in the same "must subscribe to use Aether" state
   every other free signup is in, not a lingering entitled state.
5. File all captured evidence (response bodies, Stripe object ids, screenshots, the invoice PDF)
   under `uat/reports/evidence/stripe-rehearsal-<date>/`, following the same pattern
   `SUBSCRIPTION-PRODUCTION-AUDIT-2026-08-03.md` used (`uat/reports/evidence/subscription-audit-2026-08-03/`).

---

## 6. What this rehearsal does and does not prove

**Proves, if every step above passes:** a real card, run through the real Checkout flow, produces a
real Stripe `checkout.session.completed`/`customer.subscription.created` event pair, that the
webhook handler correctly writes `stripeSubscriptionId` (previously never observed populated by a
real event), that entitlement flips, that a metered agent run debits `UsageQuota` correctly, and that
a real refund correctly reverses all of it including the live Stripe subscription cancellation.

**Does not prove:** dunning/`invoice.payment_failed` behavior (no failed real payment is deliberately
provoked here), annual billing (this rehearsal uses monthly), plan-switch/proration behavior
(`billing.py:163-193`), or the currently-unresolved GST-registration wording question — that is
explicitly deferred to §4 Step H as a human adjudication from the real invoice, not something an
automated check can resolve.
