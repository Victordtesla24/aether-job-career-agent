# Curl evidence — /billing/* and /agents/*/run endpoints (pricing screen backend wiring)

All calls production: https://5cb5f0620.abacusai.cloud/api
Login: canonical admin/admin123 (see canonical-login.md)

## Session A — 2026-07-17T13:39Z (initial)

### GET /billing/entitlement (fresh token)
```
{"active_paid": false, "plan": {"id": "free", "status": "active"}, "requiresSubscription": true}
```

### GET /billing/subscription
```
{"plan": {"id": "free", "name": "Free", "modelTier": "light"}, "status": "active", "interval": null,
 "currentPeriodEnd": null, "cancelAtPeriodEnd": false,
 "quota": {"runsUsed": 3, "runsAllowed": 5, "spendUsedUsd": 0.058292, "spendCapUsd": 1.0, "periodEnd": "2026-08-01T00:00:00+00:00"}}
```
CONFIRMS CLM-049: admin/admin123 is backfilled to Free plan with a real quota row (5 runs allowed).

### POST /agents/tailor/run {"job_id":"MV-pricing-nonexistent-job-id"}
HTTP 402
```
{"detail":{"error":"subscription_required","message":"An active subscription is required to use Aether. Subscribe to unlock.","upgradeUrl":"/pricing"}}
```

### POST /agents/scout/run {"query":"Software Engineer","location":"Melbourne"}
HTTP 402 — identical subscription_required body.

## Session B — VERIFY-TWICE — 2026-07-17T13:41Z (fresh login, new token)

### GET /billing/entitlement (fresh token #2)
```
{"active_paid":false,"plan":{"id":"free","status":"active"},"requiresSubscription":true}
```

### POST /agents/tailor/run {"job_id":"MV-pricing-verify2-fake-job"}
HTTP 402 — subscription_required (reproduced)

### POST /agents/cover-letter/run {"job_id":"MV-pricing-verify2-fake-job"}
HTTP 402 — subscription_required (reproduced)

=> CLM-053 CONFIRMED, reproduced in two independent fresh sessions.

## Checkout endpoint (POST /billing/checkout)

### {"planId":"starter","interval":"month"} (authenticated)
HTTP 400
```
{"detail":"This plan is not yet available for purchase (no Stripe price configured)"}
```

### {"planId":"pro","interval":"month"} (authenticated)
HTTP 400 — same "no Stripe price configured" message.

### {"planId":"power","interval":"month"} (authenticated) — 5th checkout call in the hour window
HTTP 429
```
{"detail":"Too many checkout attempts, retry later"}
```
(Confirms checkout_rate_limiter: max_calls=5, window_seconds=3600 — apps/api/app/main.py:169-170)

### unauthenticated
HTTP 401 {"detail":"Not authenticated"}

### {"planId":"free","interval":"month"} (authenticated)
HTTP 400 {"detail":"The Free plan does not require checkout"}

### {"planId":"MV-pricing-bogus-plan","interval":"month"} (authenticated)
HTTP 400 {"detail":"Unknown or inactive plan"}

### {"planId":"starter","interval":"MV-pricing-bogus-interval"} (authenticated)
HTTP 422 — clean Pydantic validation error, no stack trace leak.

### {"interval":"month"} (missing planId, authenticated)
HTTP 422 — clean Pydantic validation error.

=> CLM-068 CONFIRMED: checkout degrades honestly (400/503-class failures), never fabricates a Stripe URL.
Human-gate boundary = POST /billing/checkout: the exact point where a human must supply Stripe Price IDs.

## POST /billing/portal (authenticated, no existing Stripe customer)
HTTP 409 {"detail":"No billing account yet — subscribe first"}
