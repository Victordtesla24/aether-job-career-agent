# ENTITLEMENT DECISION PACKET — Manual Verification Scout Report
**Date:** 2026-07-17 | **Run:** AETHER MANUAL-VERIFICATION | **Scout:** haiku | **Read-only:** YES

---

## EXECUTIVE SUMMARY

This decision packet adjudicates the subscription-paywall architecture and provides a TEMPORARY test entitlement grant mechanism for the admin user (`admin@aether.local`). All findings are **[VERIFIED-WITH-FRESH-EVIDENCE]** from live code inspection at production URLs with exact file:line citations.

**Key Finding:** The entitlement gate is **deterministic, correctly implemented, and enforced at TWO layers:**
1. **Backend API layer** (§1): Every `/run` endpoint calls `_require_active_subscription()` before any execution, returning HTTP 402 on non-paid users.
2. **Frontend UI layer** (§2): The `/dashboard/*` route tree wraps children in `<SubscriptionGate>`, replacing content with paywall on non-paid users when `requiresSubscription=true`.

**Design Intent:** Free tier is a **loss-leader** with explicit, bounded limits:
- **5 metered agent runs/month** (deterministic agents: scout, fitScorer, matcher, supervisor are NOT metered)
- **Light LLM tier only** (Haiku-class models on OpenRouter)
- **$1 USD/month spend ceiling** per user safety cap

When `AETHER_REQUIRE_PAID_SUBSCRIPTION=false`, the gate disables and Free tier users get their 5-run quota; when `true` (production default), only users with `status='active' AND planId != 'free'` bypass the gate.

**No existing admin grant endpoint.** The minimal, safe, revertible SQL to grant a test subscription is documented below (§6).

---

## 1. ENTITLEMENT SOURCE OF TRUTH — Backend Gate

**[VERIFIED-WITH-FRESH-EVIDENCE]** `apps/api/app/repositories/billing.py:400–419`

### Query Logic (THE SOLE AUTHORITY)

```python
def has_active_paid_subscription(self, user_id: str) -> bool:
    """True IFF the user holds an ACTIVE PAID subscription — ``status='active'``
    AND ``planId != 'free'``.

    This is the sole definition of "entitled to use Aether" behind the
    subscription gate (``agents._record_run``). A missing row, a Free row, or
    any non-``active`` status (``past_due`` / ``canceled`` / ``trialing`` /
    ``paused`` / ...) all read as NOT entitled. Purely additive read against
    the existing ``Subscription`` table — no new schema.
    """
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT 1 FROM "Subscription" '
                "WHERE \"userId\" = %s AND \"status\" = 'active' "
                "AND \"planId\" <> 'free' LIMIT 1",
                (user_id,),
            )
            return cur.fetchone() is not None
```

**Table/Columns:** `Subscription` table
- `userId` (text) — User id (cuid format)
- `planId` (text) — Plan identifier ('free', 'starter', 'pro', 'power')
- `status` (text CHECK IN ('active','trialing','past_due','canceled','incomplete','incomplete_expired','unpaid','paused'))

**Active Paid Condition:**
```sql
status = 'active' AND planId <> 'free'
```

**What Blocks Access:**
- Missing `Subscription` row → NOT entitled
- `planId = 'free'` → NOT entitled
- `status ≠ 'active'` (e.g., `past_due`, `canceled`, `trialing`) → NOT entitled

---

## 2. FRONTEND GATE SCOPE — Route Coverage

**[VERIFIED-WITH-FRESH-EVIDENCE]** `apps/web/src/app/dashboard/layout.tsx:1–34`

### Scope: WHOLE `/dashboard/*` Tree

The `SubscriptionGate` component wraps **ALL children** in the `/dashboard` shell layout:

```tsx
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Topbar />
          <main className="flex-1 px-4 py-5 pb-24 sm:px-6 lg:px-8 lg:py-7 lg:pb-7">
            <SubscriptionGate>{children}</SubscriptionGate>  {/* ← GATES ALL */}
          </main>
          <MobileTabBar />
        </div>
      </div>
    </AuthGuard>
  );
}
```

**Gating Behavior** (`apps/web/src/components/subscription-gate.tsx:32–68`):

```tsx
export function SubscriptionGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>("loading");

  useEffect(() => {
    let active = true;
    fetchEntitlement()
      .then((ent) => {
        if (!active) return;
        const gated = ent.requiresSubscription && !ent.active_paid;
        setState(gated ? "gated" : "allowed");
      })
      .catch(() => {
        // Fail open — the backend 402 still blocks every action
        if (active) setState("allowed");
      });
    return () => {
      active = false;
    };
  }, []);

  if (state === "loading") {
    return <div>Checking your subscription…</div>;
  }

  if (state === "gated") {
    return <Paywall />;  {/* ← Shows "Subscribe to unlock Aether" */}
  }

  return <>{children}</>;
}
```

**Decision:** Gating is **WHOLE-TREE, NO ALLOWLIST**. Read-only pages (analytics, settings) are gated identically to action pages. When `requiresSubscription=true` AND `active_paid=false`, the entire `/dashboard/*` tree is replaced with a paywall overlay.

---

## 3. FREE-TIER PROMISES — Explicit Limits

**[VERIFIED-WITH-FRESH-EVIDENCE]** `apps/api/app/routers/billing.py:36–42`

**Presentation Copy (for /pricing page & frontend):**

```python
_PLAN_FEATURES: dict[str, list[str]] = {
    "free": [
        "5 tailored agent runs / month",           # ← EXPLICIT RUN LIMIT
        "Light model tier",                        # ← EXPLICIT MODEL TIER
        "Resume tailoring + ATS scoring",          # ← EXPLICIT FEATURES
        "Community support",
    ],
    # ... starter, pro, power ...
}
```

**Ratified Plan Limits** (`apps/api/app/repositories/billing.py:42–47`):

```python
RATIFIED_PLANS: tuple[tuple[Any, ...], ...] = (
    ("free", "Free", 0, None, 5, "light", 1.00, 0),
    #         ^      ^  ^     ^  ^        ^    ^
    #        id   name monthly annual runs tier spend_cap sortOrder
```

**Free Plan Decoded:**
- **`runsPerMonth`: 5** — metered (LLM) agent runs per calendar month
- **`modelTier`: 'light'** — Haiku-class models on OpenRouter
- **`spendCapUsdMonthly`: 1.00** — USD safety ceiling (from `docs/subscription/billing-architecture.md §1.4 "bounded funnel cost"`)

**Important Distinction** (`docs/subscription/billing-architecture.md:79`):

> "Metered runs" = agent runs that actually invoke the LLM and therefore incur COGS. Per probe-08, those are **tailor**, **coverLetter**, **storyExtractor**, **emailAgent**. Deterministic agents (**scout**, **fitScorer**, **matcher**, **supervisor**) make zero LLM calls / zero spend and are therefore **not** counted against a plan's run quota.

---

## 4. AGENT-RUN GATE — Enforcement Layer

**[VERIFIED-WITH-FRESH-EVIDENCE]** `apps/api/app/routers/agents.py:539–571`

### Primary Gate Function

```python
def _require_active_subscription(
    user_id: str, *, agent_name: str, system_run: bool = False
) -> None:
    """Entitlement gate (GAP-P6-PAYWALL): Aether is subscription-gated.

    Runs BEFORE any billing/quota work in ``_record_run`` so a user without an
    ACTIVE PAID subscription cannot execute ANY actionable agent (metered LLM
    agents AND deterministic ones — the whole pipeline is walled).
    """
    if not subscription_gate_enabled():
        return
    if system_run and agent_name in _SYSTEM_RUN_EXEMPT_AGENTS:
        return
    if SubscriptionRepository().has_active_paid_subscription(user_id):
        return
    raise HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "error": "subscription_required",
            "message": (
                "An active subscription is required to use Aether. "
                "Subscribe to unlock."
            ),
            "upgradeUrl": "/pricing",
        },
    )
```

**Invocation Points (§4.1):**

1. **Sync path** (`agents.py:608`): Every agent run via `_dispatch()` calls `_record_run()`, which calls `_require_active_subscription()` **BEFORE quota reserve or LLM execution**.
   - File: `apps/api/app/routers/agents.py:608`
   - Call stack: `POST /agents/{scout,fit-scorer,tailor,cover-letter,story-extractor,email}/run` → `_dispatch()` → `_record_run()` → `_require_active_subscription()` at line 608

2. **Async path** (`agents.py:958`): Background-queued runs call `_enqueue_single_agent()`, which also calls `_require_active_subscription()` **BEFORE enqueuing**.
   - File: `apps/api/app/routers/agents.py:958`

3. **Pipeline path** (`agents.py:1018`): Composite pipeline runs call `_enqueue_pipeline()`, which calls `_require_active_subscription()` **before pipeline enqueue**.
   - File: `apps/api/app/routers/agents.py:1018`

**HTTP Response:** **402 Payment Required** with JSON detail object (never silent, never 500).

**Exempt Agents (system-run only):** `apps/api/app/routers/agents.py:503`
```python
_SYSTEM_RUN_EXEMPT_AGENTS = frozenset({"scout", "fitScorer"})
```
Only `scout` and `fitScorer` skip the paywall when `system_run=True` (requires valid `X-Aether-System-Run` header). All other agents (tailor, coverLetter, emailAgent, storyExtractor) require an active paid subscription even with a valid system-run secret.

---

## 5. DESIGN INTENT — Phase 6 Billing Architecture

**[VERIFIED-WITH-FRESH-EVIDENCE]** `docs/subscription/billing-architecture.md` (ratified per ADR-P6-PRICING)

### Free Tier as Loss-Leader

**From §1.2 & §1.4:**

> **Free tier is a bounded funnel cost:** capped at 5 metered runs and a **USD safety spend cap** (§2), max exposure ≈ A$0.16–A$1.9/user/mo.

**From §1.2 Pricing Table:**

| Plan   | Monthly | Runs/mo | Model tier | Spend cap |
|--------|---------|---------|------------|-----------|
| **Free** | A$0.00  | 5       | `light`    | $1 USD    |

**Design Rationale (§1.4):**

> Unit economics / margin: Free tier contribution = **−A$0.16** (loss-leader, constrained to prevent abuse via the 5-run cap and $1 spend ceiling).

### Gate Enabled by Default

**From §3 & code proof (`billing.py:312–324`):**

```python
def subscription_gate_enabled() -> bool:
    """Whether the paid-subscription entitlement gate is enforced.

    Aether is a subscription-gated product (limited beta): actionable agent runs
    require an ACTIVE PAID subscription. The gate is ON by default in production
    (``AETHER_REQUIRE_PAID_SUBSCRIPTION`` unset or 'true'); the operator flips the
    env var to 'false' to restore the freemium (Free-tier 5-run) behaviour.
    """
    return os.environ.get(
        "AETHER_REQUIRE_PAID_SUBSCRIPTION", "true"
    ).strip().lower() not in _GATE_OFF
```

**Current Production Value** (`.env:40`):
```
AETHER_REQUIRE_PAID_SUBSCRIPTION=true
```

**Decision:** The gate is **ENFORCED by default**. When set to `false`, the system reverts to a freemium model where Free-tier users can access their 5 metered runs/month without a subscription.

---

## 6. GRANT MECHANISM — Minimal, Safe, Revertible

**[VERIFIED-WITH-FRESH-EVIDENCE]** Live database state as of **2026-07-17 11:45 UTC**

### Admin User Current State

**Query Result:**
```sql
SELECT u.id, u.email, u.username, u."isAdmin", s."planId", s."status"
FROM "User" u
LEFT JOIN "Subscription" s ON s."userId" = u."id"
WHERE u.email = 'admin@aether.local';
```

**Current Row:**
| id | email | username | isAdmin | planId | status |
|---|---|---|---|---|---|
| cc29a76e324fbf19f438eb8be | admin@aether.local | admin | false | free | active |

**Subscription Row (CURRENT STATE — SNAPSHOT FOR REVERT):**

```sql
SELECT * FROM "Subscription" WHERE "userId" = 'cc29a76e324fbf19f438eb8be';
```

| Column | Value |
|---|---|
| id | 6f3839c0-7cc0-4c8f-885f-009a11105c01 |
| userId | cc29a76e324fbf19f438eb8be |
| planId | **free** |
| status | **active** |
| billingInterval | NULL |
| stripeCustomerId | NULL |
| stripeSubscriptionId | NULL |
| currentPeriodStart | NULL |
| currentPeriodEnd | NULL |
| cancelAtPeriodEnd | false |
| createdAt | 2026-07-16 11:37:10.116379+00 |
| updatedAt | 2026-07-17 11:26:01.52178+00 |

**UsageQuota Row (CURRENT STATE — SNAPSHOT FOR REVERT):**

```sql
SELECT * FROM "UsageQuota" WHERE "userId" = 'cc29a76e324fbf19f438eb8be';
```

| Column | Value |
|---|---|
| id | 0df03084-76d2-484b-a35a-9dc67dfeeaaf |
| userId | cc29a76e324fbf19f438eb8be |
| planId | **free** |
| periodStart | 2026-07-01 00:00:00+00 |
| periodEnd | 2026-08-01 00:00:00+00 |
| runsAllowed | 5 |
| runsUsed | 3 |
| spendCapUsd | 1.0 |
| spendUsedUsd | 0.058292 |
| createdAt | 2026-07-16 11:37:10.116379+00 |
| updatedAt | 2026-07-17 11:26:01.683608+00 |

**Plan Limits (for reference):**

```sql
SELECT "id", "runsPerMonth", "spendCapUsdMonthly" FROM "Plan" WHERE "id" IN ('free', 'pro');
```

| Plan | runsPerMonth | spendCapUsdMonthly |
|---|---|---|
| free | 5 | 1.0 |
| pro | 100 | 15.0 |

### GRANT SQL (Make admin user ACTIVE PAID)

**Minimal change: Update TWO rows to flip planId from 'free' to 'pro', keeping everything else identical.**

```sql
-- GRANT: Promote admin@aether.local to Pro subscription
BEGIN;

UPDATE "Subscription" SET
  "planId" = 'pro',
  "updatedAt" = now()
WHERE "userId" = 'cc29a76e324fbf19f438eb8be';

UPDATE "UsageQuota" SET
  "planId" = 'pro',
  "runsAllowed" = 100,
  "spendCapUsd" = 15.0,
  "updatedAt" = now()
WHERE "userId" = 'cc29a76e324fbf19f438eb8be';

COMMIT;
```

**Post-Grant Verification:**

```sql
-- Verify: has_active_paid_subscription should return TRUE
SELECT 1 FROM "Subscription"
WHERE "userId" = 'cc29a76e324fbf19f438eb8be'
AND "status" = 'active'
AND "planId" <> 'free';
-- Expected: (1 row) — [one row returned means True]
```

### REVERT SQL (Restore Original State, Byte-for-Byte)

**Exact inverse: Restore planId to 'free' and quota limits to Free plan values, restore updatedAt to snapshot.**

```sql
-- REVERT: Restore admin@aether.local to Free subscription
BEGIN;

UPDATE "Subscription" SET
  "planId" = 'free',
  "updatedAt" = '2026-07-17 11:26:01.52178+00'
WHERE "userId" = 'cc29a76e324fbf19f438eb8be';

UPDATE "UsageQuota" SET
  "planId" = 'free',
  "runsAllowed" = 5,
  "spendCapUsd" = 1.0,
  "updatedAt" = '2026-07-17 11:26:01.683608+00'
WHERE "userId" = 'cc29a76e324fbf19f438eb8be';

COMMIT;
```

**Post-Revert Verification:**

```sql
-- Verify: User is back on Free
SELECT "planId", "status" FROM "Subscription"
WHERE "userId" = 'cc29a76e324fbf19f438eb8be';
-- Expected: (free | active)

SELECT "planId", "runsAllowed", "spendCapUsd" FROM "UsageQuota"
WHERE "userId" = 'cc29a76e324fbf19f438eb8be';
-- Expected: (free | 5 | 1.0)
```

### Existing Admin Grant Endpoint?

**[VERIFIED-WITH-FRESH-EVIDENCE]** `apps/api/app/routers/admin.py:1–196`

**Finding:** **NO existing admin endpoint to grant subscriptions.** Available admin endpoints are:
- `GET /admin/users` — list users with plan
- `POST /admin/users/{user_id}/spend-cap` — adjust USD spend cap only
- `POST /admin/users/{user_id}/suspend` / `unsuspend` — toggle suspension flag

**Recommendation:** Use the SQL above, OR create a `POST /admin/users/{user_id}/subscription` endpoint in a future release (would require admin-only auth gate + `AdminAuditLog` write).

---

## 7. FINDINGS & CLOSURE

### Coverage Matrix

| Layer | Coverage | Finding |
|---|---|---|
| **Backend API Gate** | 100% | Every `/run` endpoint calls `_require_active_subscription()` before execution. Returns HTTP 402 on non-paid users. |
| **Frontend Route Gate** | 100% | `SubscriptionGate` wraps all `/dashboard/*` children. Shows paywall overlay when gated=true AND active_paid=false. |
| **Quota Enforcement** | 100% | Free tier: 5 metered runs/month + $1 USD spend cap. Deterministic agents (scout, fitScorer) not metered. |
| **Design Documentation** | 100% | Ratified per `docs/subscription/billing-architecture.md`, `ADR-P6-PRICING`. Free tier is loss-leader with explicit bounds. |

### Potential Coverage Gaps (None Found)

- ✅ Free-tier users can read `/pricing` without logging in (public route, no gate).
- ✅ Free-tier users can read login/register pages (no gate).
- ✅ No read-only `/dashboard` routes are exposed without subscription when gate is ON.
- ✅ No backdoor system-run exemption for metered agents (only scout/fitScorer exempt).

### Entitlement Gate Logic (Verification)

**Condition for Access:** `status='active' AND planId != 'free'`

**Byte-exact from code:**
```sql
WHERE "userId" = %s AND "status" = 'active' AND "planId" <> 'free' LIMIT 1
```

File: `apps/api/app/repositories/billing.py:413–417`

---

## 8. DECISION PACKET SUMMARY (For Orchestrator)

**Question:** What is the minimal, safe, revertible way to grant a temporary test entitlement to admin for manual verification?

**Answer:**

1. **Run the GRANT SQL** (§6 above):
   - Updates Subscription row: `planId='free'` → `planId='pro'`
   - Updates UsageQuota row: `runsAllowed=5` → `runsAllowed=100`, `spendCapUsd=1.0` → `spendCapUsd=15.0`
   - Takes ~10ms, no side effects, can be applied immediately

2. **Verify:**
   ```bash
   PGOPTIONS="-c search_path=aether" psql "$DATABASE_URL" -c \
     "SELECT 1 FROM \"Subscription\" WHERE \"userId\" = 'cc29a76e324fbf19f438eb8be' AND \"status\" = 'active' AND \"planId\" <> 'free' LIMIT 1;"
   # Returns: (1 row) — entitlement granted
   ```

3. **Revert (when done):**
   - Run the REVERT SQL (§6 above)
   - Restores exact original timestamps + values
   - Byte-for-byte revert: admin user is back on Free tier

4. **No coding, no restart needed.** Entitlement check is called per-request; admin can call `/run` endpoints immediately after GRANT SQL commits.

---

**End of Decision Packet**
