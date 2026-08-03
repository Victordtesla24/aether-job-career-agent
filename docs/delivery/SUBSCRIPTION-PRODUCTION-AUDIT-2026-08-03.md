# SUBSCRIPTION PRODUCTION AUDIT — 2026-08-03

**Auditor:** independent verification pass (not the author of any billing code touched below)
**Production:** `https://5cb5f0620.abacusai.cloud`
**Stripe account:** `acct_1TvSlMRy5o5QDotA` — **livemode**, key class `sk_live_*` (value never printed)
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Run window:** 2026-08-03T11:35Z → 11:43Z (this document is written incrementally as evidence is gathered)

**Acceptance bar:** does the real-money subscription path actually work end-to-end in production
right now, and would a real paying customer get what they were promised?

**Payment-safety statement:** zero real charges made. One live Checkout Session was created
(A$39.00 Pro/month, mode=subscription) and abandoned before entering any card data — Stripe records
it `status: open`, `payment_status: unpaid`; it self-expires in 24h. One Billing Portal session was
created (no cost). All Stripe reads below are `GET`/list calls. All DB reads are `SELECT`. No Price,
Product, refund, or subscription-row write was made by this audit.

---

## Ranked findings (highest real-customer harm first)

### 1. [MISLEADING — HIGH] The "5 free runs" the app sells is universally and immediately denied — reconfirmed live, today, on a brand-new signup

**Claim under test:** ADV-ENT-002 (pre-existing, filed in GOLD-MASTER-V2-ADVERSARIAL-REVIEW.md,
carried OPEN through GOLD-MASTER-V3). Is it still true, right now, in production?

**Evidence (gathered fresh this run):**

1. Created a brand-new account, `aether.audit.qa.1785756940@mailinator.com`, via
   `POST /api/auth/register` → `201`, then `POST /api/auth/login` → `200`. [VERIFIED]
2. `GET /api/billing/plans` (unauthenticated, public) — the Free tier's advertised feature list:
   ```json
   {"id":"free","name":"Free","runsPerMonth":5,"monthly":{"total":0.0,"gst":0.0,"net":0.0},
    "features":["5 tailored agent runs / month","Light model tier",
                "Resume tailoring + ATS scoring","Community support"],"purchasable":false}
   ```
   [VERIFIED — curl, 2026-08-03T11:35Z]
3. `GET /api/billing/subscription` (as the new user, immediately after signup, before any run):
   `{"plan":{"id":"free","name":"Free",...},"status":"active",
   "quota":{"runsUsed":0,"runsAllowed":5,...}}` — the backend genuinely provisions 5 usable-looking
   runs. [VERIFIED]
4. `GET /api/billing/entitlement` (same user): `{"active_paid":false,"plan":{"id":"free",
   "status":"active"},"requiresSubscription":true}`. [VERIFIED]
5. `POST /api/agents/scout/run` with a valid body (`{"query":"software engineer","location":
   "Sydney"}`), same user, **0 of 5 runs ever used**:
   ```json
   {"detail":{"error":"subscription_required",
   "message":"An active subscription is required to use Aether. Subscribe to unlock.",
   "upgradeUrl":"/pricing"}}
   ```
   `HTTP 402`. [VERIFIED — curl, 2026-08-03T11:39Z]
6. Playwright screenshots of the **live production build**, same session, same user:
   - `/pricing` (authenticated): Free tile reads **"$0 · No card required · 5 agent runs / month"**
     with a green **"CURRENT PLAN"** badge and a **"Go to dashboard"** button — an explicit,
     unconditional promise. → `uat/reports/evidence/subscription-audit-2026-08-03/01-pricing-page.png`
   - `/dashboard` (clicking straight through from that promise): full-screen paywall —
     **"Subscribe to unlock Aether — Aether is in limited beta. An active subscription is required
     to run the AI agents..."** — while the **persistent sidebar tile**, rendered on the *same
     screen*, simultaneously reads **"Free — 0/5 runs this period."**
     → `02-dashboard-gated-free-user.png`, verbatim text extract in `02-dashboard-text-extract.txt`
   - `/dashboard/settings` (Billing & Subscription panel): **"Agent runs this period: 0 / 5"** with
     a progress bar implying headroom. → `03-dashboard-settings-billing.png`
   [VERIFIED — Playwright, headless Chromium, 2026-08-03T11:36–11:37Z, against the live build:
   `.next/BUILD_ID` = `UUCwGcKSpFnIllSYtYitK`, built 2026-08-03T10:23Z, `aether-web` service active
   since 10:33:40Z today — i.e. this is the build a real visitor gets right now, not stale JS.]

**Root cause (code, [VERIFIED]):** `apps/api/app/repositories/billing.py::subscription_gate_enabled()`
reads `AETHER_REQUIRE_PAID_SUBSCRIPTION` from the environment; **default is `'true'`**, and the live
`.env` (sourced directly by `start-api.sh`, confirmed against the running `aether-api` process's own
`/proc/<pid>/environ`) sets it explicitly to `true`. `apps/api/app/routers/agents.py::
_require_active_subscription()` runs this check **before any quota/billing work, for every
actionable agent**, and hard-blocks with 402 regardless of the user's `UsageQuota.runsUsed`. This is
a **deliberate, documented gate** ("Aether is a subscription-gated product (limited beta)"), not a
bug in the quota arithmetic — the 5-run quota machinery is real and would serve requests correctly
the moment the flag flips (see §9). The defect is that **three separate user-facing surfaces
(`/pricing`, the dashboard sidebar, and Settings→Billing) still advertise the Free tier as a
functioning allowance**, with no "beta requires a paid plan" disclaimer anywhere outside the paywall
screen itself.

**Verdict: MISLEADING.** Not a broken backend — a marketing/product claim that is false for every
visitor, confirmed with today's evidence, not last month's.

**User impact if a real customer relied on it today:** A visitor reads "$0, no card required, 5
tailored agent runs/month," clicks "Go to dashboard" expecting to try the product, and is walled out
immediately with zero runs ever available — not "5, then a paywall." This is the single most likely
trust-breaking moment in the entire funnel, and it happens on literally the first click for every
new signup, unconditionally.

---

### 2. [UNVERIFIED — CRITICAL exposure, not yet observed as a defect] The real-money entitlement write path has never been exercised by an actual Stripe-delivered event

**Claim under test:** ENTITLEMENT — "what actually flips a user to paid" — proven from code AND a
real production DB row, per the task brief.

**DB row, read-only, live production, 2026-08-03T11:31Z** [VERIFIED — `psql`, `SELECT` only]:

```
 userId                     email                     planId  status  stripeCustomerId      stripeSubscriptionId
 c6c8d0163d973a8048e7e33b8  sarkar.vikram@gmail.com   pro     active  cus_UvLRWZMJc6iGX2     (NULL)
```
This is the **only** non-Free `Subscription` row that has ever existed in this database (2 users
total exist in prod right now). It has been `pro`/`active` since 2026-07-21T03:54:19Z; the app's own
`has_active_paid_subscription()` (`status IN (active,trialing,past_due) AND planId <> 'free'`) grants
this row full Pro entitlement — 100 runs/month — with **no live Stripe subscription behind it at
all**. 66 of 100 runs and US$0.795 of real LLM spend have been consumed under this grant.

**Cross-check against Stripe itself for `cus_UvLRWZMJc6iGX2`, 2026-08-03T11:32Z** [VERIFIED —
`GET /v1/subscriptions`, `/v1/charges`, `/v1/invoices`, `/v1/checkout/sessions`, all
`?customer=cus_UvLRWZMJc6iGX2`]:

| Stripe object type | Count | Detail |
|---|---|---|
| Subscriptions | **0** | none, ever |
| Charges | **0** | none, ever |
| Invoices | 1 | `in_1TvVUhRy5o5QDotAObfWWq2p`, `amount_paid: 0`, `billing_reason: "manual"` — a $0 Dashboard-created invoice, not a subscription charge |
| Checkout Sessions | 1 | `cs_live_a12jbxki...`, `status: "expired"`, `payment_status: "unpaid"`, `mode: "subscription"`, `subscription: null` — **this customer's only real checkout attempt was abandoned, never completed** |

**Whole-account cross-check — every real event Stripe has ever emitted on this LIVE account**
[VERIFIED — `GET /v1/events?type=...`, paginated, 2026-08-03T11:41Z]:

| Event type | Real Stripe events, ever | 
|---|---|
| `checkout.session.completed` | **0** |
| `customer.subscription.created` | **0** |
| `customer.subscription.updated` | **0** |
| `customer.subscription.deleted` | **0** |
| `checkout.session.expired` | 6+ (multiple abandoned real attempts, 07-22 through 08-01) |
| `invoice.paid` | 3 (all `billing_reason: manual`, `$0`, correctly no-op'd by `_handle_invoice_paid`'s `_RENEWAL_BILLING_REASONS` filter) |
| `charge.refunded` | 1 real (`evt_3TvVW5Ry5o5QDotA1kUC8kto`, tied to the disconnected `cus_UvMEA0Z5XD9uzy` — see §5, not this row) |

**So how did the `pro`/`active` row get created?** The production `StripeEvent` idempotency ledger
(`SELECT id,type,status FROM "StripeEvent"`) [VERIFIED, `psql`] shows the row was touched by events
named `evt_test_1784623191107` (`customer.subscription.updated`), `evt_test_1784623190767` /
`evt_test_1784623190383` (`invoice.paid`), `evt_test_1784623189848` (`charge.dispute.created`), and
`evt_test_1784623189532` / `evt_test_1784623188699` (`charge.refunded`) — all received within one
second of each other, 2026-07-21T08:39:5{0,1,2}Z. The `evt_test_*` id prefix does not match any real
Stripe object id format (`evt_<random>`), and **none of these event types appear anywhere in Stripe's
own real event log for this account**. The webhook handler verifies signatures via HMAC using
`STRIPE_WEBHOOK_SECRET` — that check would pass for *any* payload correctly signed with that secret,
whether or not Stripe itself sent it. **[INFERRED]**: these were locally-crafted, validly-signed test
payloads POSTed straight at `/api/billing/webhooks/stripe` (consistent with the prior payment-pipeline
hardening run recorded 2026-07-21, which is known to have used both a real $0.50 charge and synthetic
event injection to exercise handler branches that don't require real money). This explains the data
but is not itself proof of intent — flagged as inferred, not observed.

**Why this matters regardless of intent:** every plan/status combination currently sitting in
production came from either (a) the default Free backfill, or (b) a manually-crafted webhook call —
**never from a real, Stripe-delivered `checkout.session.completed` or `customer.subscription.*`
event**. The code path that a **real paying customer will actually trigger** — Stripe completing a
real card charge, then POSTing a real `checkout.session.completed` webhook with Stripe's real object
shapes — has **zero first-hand evidence** it works. Code review (`_handle_checkout_completed`,
`_subscription_price_id`'s shape-tolerant parsing) suggests it should; but "should, by inspection" is
exactly the standard this audit is required not to accept as proof. The 6+ real
`checkout.session.expired` events show **every genuine purchase attempt on this account has been
abandoned before payment**, so this has never been proven end-to-end with real money either.

**Verdict: UNVERIFIED** (the exact claim the task flags as most important — "prove it from a real
production DB row" — the row exists, but it disproves clean provenance rather than confirming it).
Additionally, **BROKEN as a reconciliation property**: nothing in the code or any job compares
`Subscription.status`/`planId` against Stripe's live subscription object, so a hand-set or
corrupted DB row is entitled forever with no alarm.

**User impact if a real customer paid today:** Cannot be fully bounded without either (a) completing
one real Stripe payment and watching the real webhook land (out of this audit's authorized scope —
would cost real money and is exactly the kind of action the task told me to stop and flag rather than
do), or (b) an operator/dev re-running the payment-pipeline verification with a real card and
confirming `stripeSubscriptionId` populates from the **real** `checkout.session.completed` payload
this time. Until one of those happens, "a customer's card is charged and they get nothing" is a live,
untested possibility, not a refuted one. **This is the one item I recommend the orchestrator treat as
blocking** — it is cheap to close (one real subscription purchase + immediate refund/cancel, exactly
the pattern already used safely on 2026-07-21) and currently has zero evidence either way for the
actual code path a customer will hit.

---

### 3. [OPEN, MODERATE — reconfirmed] Advertised price/currency/GST is never reconciled against the Stripe Price objects that actually charge

**Claim:** `ML-adv-CUR-001` (filed 2026-07-31, `STRIPE-CURRENCY-VERIFICATION.md`). Still true?

**Evidence, read fresh today** [VERIFIED — `Read`, 2026-08-03T11:34Z]: `apps/api/app/routers/
billing.py:102`:
```python
return {"currency": "AUD", "gstIncluded": True, "plans": plans}
```
Still a bare literal — grep confirms no `Price.retrieve` call anywhere in `apps/api` outside
`stripe_gateway.py`'s own session/subscription calls. Cross-checked today: DB `Plan.stripePriceId*`
→ live Stripe `Price` objects for all 3 purchasable plans still agree exactly (`aud`, `1900`/`3900`/
`6900`, `tax_behavior: inclusive`, `active: true`, `livemode: true`) — [VERIFIED, `GET /v1/prices/
{id}` × 3, 2026-08-03T11:42Z]. Today's numbers are correct; they are still correct **by coincidence**,
not by any code-enforced invariant. Unchanged since the prior finding — no new evidence to raise or
lower severity, re-confirming rather than re-raising per the task's own instruction on this exact
finding.

**Verdict: OPEN, unchanged, MODERATE, latent.** No customer harm today.

---

### 4. [REFUTED, unchanged — do not re-raise] USD-by-default at Stripe Checkout is geolocation presentment, not a currency defect

Re-ran the exact scenario live today rather than trusting the July 31 write-up. Created a real
Checkout Session as the audit test user (`POST /api/billing/checkout {"planId":"pro","interval":
"month"}` → `200`), then:

- Read the session straight back from Stripe: `mode: "subscription"`, `currency: "aud"`,
  `amount_total: 3900`, `metadata: {user_id, plan_id: "pro", interval: "month"}`,
  `client_reference_id` = my test user id, `success_url`/`cancel_url` both point at the real app,
  `livemode: true`. [VERIFIED, `GET /v1/checkout/sessions/{id}` + `/line_items`, 2026-08-03T11:40Z]
- Loaded the actual `checkoutUrl` in headless Chromium: default view showed **USD $28.39** (this VM's
  egress IP is `208.122.8.11`, San Francisco, CA — reconfirmed via `ipinfo.io`, same city as the
  July 31 finding). Clicking the **AUD** toggle switched the displayed price to **A$39.00** exactly,
  matching the advertised price to the cent, with no fee/markup line beyond "Exchange rate and fees
  of your bank may apply" (a card-network disclosure, not an app charge).
  → `04-stripe-checkout-default.png`, `05-stripe-checkout-aud-toggle.png` [VERIFIED, Playwright,
  2026-08-03T11:44Z]

**Verdict: REFUTED, reconfirmed.** No card data entered, no session completed. Consistent with the
existing ruling — this is Stripe Adaptive Pricing presenting a US-geolocated browser its local-
currency equivalent; the underlying Price, Session, and settlement currency are AUD throughout.

---

### 5. [NO DEFECT, contextual] The A$0.50 payment/refund and the second Stripe customer are historical noise, not a live issue

Re-verified per the task's own instruction not to mistake this for a current defect:
`cus_UvMEA0Z5XD9uzy` (metadata `{}` — created directly in the Stripe Dashboard, never through the
app's `create_customer`, which always stamps `metadata.user_id`) shows one real charge
`py_...1J7HeRvV`, `amount: 50`, `currency: aud`, `status: succeeded`, `paid: true`, `refunded: true`,
`amount_refunded: 50` — fully refunded, and a second charge attempt on the same customer that
`status: failed`. **This customer has no `subscription`, no `checkout session`, and no `user_id`
metadata — it is entirely disconnected from the app's own `Subscription` table**, which points at the
*other* customer (`cus_UvLRWZMJc6iGX2`, §2). [VERIFIED, 2026-08-03T11:33Z] No current-state action
needed here; recorded for completeness only.

---

### 6. [WORKS] GST handling matches what Stripe actually collects

- `GET /api/billing/plans` GST math: Pro `{"total":39.0,"gst":3.55,"net":35.45}` — `gst_breakdown()`
  computes `gst = round(total/11, 2)` (GST backed out of a GST-inclusive price), `39/11 = 3.5454 →
  3.55`. [VERIFIED, arithmetic + curl, 2026-08-03T11:35Z]
- Stripe account tax posture, read fresh: `GET /v1/tax/settings` → `status: "active"`, head office
  `AU`; `GET /v1/tax/registrations` → 1 active AU registration (`active_from` 2026-07-21). All 3
  purchasable Prices carry `tax_behavior: "inclusive"` (confirmed live today, §3) — so Stripe backs
  GST **out of** the advertised total rather than adding it on top, exactly matching the app's own
  math. [VERIFIED, 2026-08-03T11:42Z] Not re-run as a live non-charging tax-calculation preview this
  session (already proven to the cent on 2026-07-31 with fresh `tax/calculations` previews on the
  identical, unchanged Price objects) — re-deriving it today would add no new information.

**Verdict: WORKS**, unchanged.

---

### 7. [WORKS] Webhook endpoint configuration matches the code's own event coverage

`GET /v1/webhook_endpoints` [VERIFIED, 2026-08-03T11:41Z]: one endpoint,
`url: "https://5cb5f0620.abacusai.cloud/api/billing/webhooks/stripe"` (exact production URL),
`status: "enabled"`, `livemode: true`, `enabled_events`:
```
charge.dispute.created, charge.refunded, checkout.session.completed,
customer.subscription.deleted, customer.subscription.trial_will_end,
customer.subscription.updated, invoice.paid, invoice.payment_failed
```
This is an **exact match** to every branch in `_dispatch_stripe_event()` — no gap, no dead
subscription. Handler enforces raw-body-first signature verification before any parsing (`billing.py`
`stripe_webhook()` reads `request.body()` before touching Pydantic, verifies via
`stripe.Webhook.construct_event`), and idempotency via a `StripeEvent` row inserted in the *same*
transaction as the side effects it guards (`INSERT ... ON CONFLICT DO NOTHING` then `_dispatch`, all
rolled back together on any failure). **Verdict: WORKS** as configured. (Its two most consequential
event types have never actually fired for real — see §2.)

---

### 8. [WORKS] Cancel / manage-subscription path is reachable and creates a real session

`POST /api/billing/portal` as the audit test user (who now has a real Stripe customer from the §4
checkout attempt) → `200`, `{"portalUrl":"https://billing.stripe.com/p/session/live_..."}` — a real,
live Billing Portal session. [VERIFIED, curl, 2026-08-03T11:43Z] Refund/dispute revoke
(`_handle_charge_refunded`, `_handle_dispute_created` → `_revoke_to_free`) and admin refund
(`POST /billing/admin/refund`) are code-reviewed only this session (not re-exercised with real money,
to avoid an unnecessary live charge) — a prior session's memory records these as verified end-to-end
with a real charge + refund on 2026-07-21; **not independently re-verified by this audit**, tagged
**[INFERRED-FROM-PROMPT / historical, not re-tested]**.

---

### 9. [CONTEXT — not a defect] The Free-tier quota machinery is real; it is switched off by policy, not broken

`apps/api/app/routers/agents.py::_require_active_subscription()`: *"Gated behind
`AETHER_REQUIRE_PAID_SUBSCRIPTION` (default ON) — when the operator sets it 'false' the freemium
Free-tier path applies."* The `UsageQuotaRepository.reserve()` atomic increment-or-reject logic that
would serve those 5 runs is implemented, tested (`test_adv_ent_001_refine_entitlement_gate.py`,
`test_gap_p6_billing.py`), and currently sitting idle behind the flag — it is not vaporware. **This
is the fix surface for Finding #1**: either the copy must stop promising "5 tailored agent runs /
month" as a `CURRENT PLAN` benefit while the gate is on, or the gate must be turned off. Both are
one-line changes; this audit does not recommend which (business decision, unchanged from the
2026-07-31 framing). **[INFERRED FROM CODE — not executed, would change live prod behavior, out of
this audit's scope.]**

---

## Evidence index

| # | Artifact | What it proves | Method / timestamp |
|---|---|---|---|
| 1 | `uat/reports/evidence/subscription-audit-2026-08-03/01-pricing-page.png` | Free tier sold as "CURRENT PLAN, 5 agent runs/month, no card required" | Playwright, 2026-08-03T11:36Z |
| 2 | `.../02-dashboard-gated-free-user.png` + `02-dashboard-text-extract.txt` | Same session, same load: paywall + "0/5 runs" sidebar contradiction | Playwright, 11:37Z |
| 3 | `.../03-dashboard-settings-billing.png` | Settings shows "Agent runs this period 0/5" | Playwright, 11:37Z |
| 4 | `.../04-stripe-checkout-default.png` | Real live Checkout Session, USD presentment (geolocation) | Playwright, 11:44Z |
| 5 | `.../05-stripe-checkout-aud-toggle.png` | Same session, AUD toggle → exact A$39.00 | Playwright, 11:44Z |
| 6 | `/tmp/.../scratchpad/stripe/{customer,subscriptions,charges,invoices,sessions}.json` | Raw Stripe reads for `cus_UvLRWZMJc6iGX2` | curl + `sk_live_*`, 11:32Z |
| 7 | `/tmp/.../scratchpad/checkout_session_live.json`, `checkout_response_clean.json` | Raw session object for the audit's own Checkout Session | curl, 11:40Z |
| 8 | `/tmp/.../scratchpad/webhook_endpoints.json` | Live webhook endpoint config | curl, 11:41Z |
| 9 | psql `SELECT` transcripts (this document, §2) | `Subscription`, `UsageQuota`, `StripeEvent`, `AdminAuditLog` production rows | `psql` against `DATABASE_URL` from live `.env`, 11:31–11:33Z |
| 10 | `register_response.json`, `login_response.json`, `entitlement_response.json`, `subscription_response.json`, `scout_run_response.json` | Fresh signup → entitlement → 402 sequence | curl, 11:35–11:39Z |

---

## Summary for the orchestrator

- **Ship-blocking, cheap to close:** §2 — no real Stripe-delivered `checkout.session.completed` or
  `customer.subscription.*` event has ever landed on this account; the only paid DB row was set by a
  locally-crafted, HMAC-valid but non-Stripe-originated webhook call. The real-money write path is
  code-reviewed-only. Closing this needs one real subscription purchase (a few dollars, refundable
  exactly as done 2026-07-21) with the resulting webhook watched live.
- **Product-honesty issue, zero engineering cost either way:** §1/§9 — the Free tier is sold on 3
  screens as a working $0 allowance and is actually a universal, immediate 402 for every visitor.
  The fix is a business decision (advertise honestly vs. turn the gate off), already escalated in
  prior audits and still unresolved.
- **Confirmed working, unchanged:** currency correctness (§4), GST (§6), webhook config (§7), cancel/
  portal reachability (§8).
- **Confirmed still-latent, low urgency:** the hardcoded `"AUD"` literal with no Stripe reconciliation
  (§3).
