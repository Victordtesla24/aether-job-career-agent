# Aether Admin Panel — Operator Guide

**Status:** Built and deployed. Live-verified in production (temp-QA-admin, 2026-07-16 — see
`uat/reports/evidence/phase6/qa-prod-console-admin.json`, `gate17-admin-verification-raw.json`,
`gate31-admin123-recheck-20260716T114522Z.json`). Formal closure of GATE-17 (the operator using
their *own* permanent admin credential) is **BLOCKED-ON-HUMAN** — see the "Provisioning your admin
credential" section below.

**Production:** https://5cb5f0620.abacusai.cloud
**Repo:** `apps/api/app/routers/admin.py`, `apps/api/app/repositories/admin.py`,
`apps/web/src/app/admin/*`, `apps/web/src/components/admin/*`.

---

## 1. What the admin panel is

A privileged, `isAdmin`-gated set of routes (backend `/api/admin/*`, frontend `/admin/*`) for
operating the platform: health monitoring, user/subscription/spend visibility, per-user spend-cap
and suspension control, a signup kill-switch, and an append-only audit trail. There is no separate
"admin app" — it is the same Next.js app and FastAPI service, gated by a boolean column.

There is currently **no self-service admin sign-up**. Admin access is granted exclusively by
setting the `AETHER_ADMIN_EMAIL` / `AETHER_ADMIN_PASSWORD_HASH` environment variables described
below. Nothing in the product UI lets a regular user become an admin.

---

## 2. Provisioning your admin credential (do this first)

The database ships with **zero real admins**. A demo credential (`admin` / `admin123`,
`admin@aether.local`) exists from earlier development seeding, but on every API boot the app
**unconditionally demotes it to `isAdmin=false`** (`apps/api/app/repositories/admin.py::apply_admin_rotation`,
wired into the FastAPI `lifespan` in `apps/api/app/main.py`). This is not configurable — it happens
whether or not you have set your own admin yet, so the seeded credential can never hold privileges
(GAP-P6-SEC-001 / GATE-31, verified live: `admin`/`admin123` login returns `isAdmin=false` and
`GET /api/admin/users` returns 403 for that account).

To provision **your own** admin account:

1. Generate a bcrypt hash of your chosen password (the app hashes with `passlib`'s
   `CryptContext(schemes=["bcrypt"])` — any bcrypt-compatible hash works):
   ```bash
   python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('YOUR_PASSWORD_HERE'))"
   ```
2. Set two environment variables on the API service:
   - `AETHER_ADMIN_EMAIL` — the email address for your admin account.
   - `AETHER_ADMIN_PASSWORD_HASH` — the bcrypt hash from step 1 (never the plaintext password).
3. Restart the API service. On next boot, `apply_admin_rotation()`:
   - demotes the seeded `admin`/`admin123` account (always, regardless of the env vars), then
   - inserts-or-updates a `User` row for `AETHER_ADMIN_EMAIL` with `isAdmin=true`,
     `suspended=false`, and the password hash you supplied, and gives it a Free-tier
     subscription + quota row so it behaves like any other account for billing purposes.
4. Log in at `/login` (or `/dashboard`) with that email + your plaintext password; you should land
   with `isAdmin=true` and see `/admin` in the UI.

**If `AETHER_ADMIN_EMAIL` happens to equal the seeded address (`admin@aether.local`):** the env
admin write runs *after* the demotion, so your explicit configuration wins and that account becomes
admin again. Absent the env vars entirely, the panel has zero admins by design — this is the
intended "secure by default" state until you configure it.

There is no in-app UI to change these values; they are process environment variables only.
Rotating them (e.g. changing password) means re-running step 1–2 and restarting the API.

---

## 3. Routes and what each does

All routes below require a valid Bearer JWT for a user with `isAdmin=true`
(`apps/api/app/middleware/auth.py::AdminUser`). An anonymous caller gets **401**; an authenticated
non-admin gets **403**. Nothing here is reachable without a real admin login.

| Route | Method | Purpose |
|---|---|---|
| `/api/admin/health` | GET | Service/agent-run health snapshot: `AgentRun` status counts (completed/failed/running/queued), computed success rate, and configured LLM model tiers. No fabricated metrics — an empty `AgentRun` table yields `success_rate: null`, not a made-up number. |
| `/api/admin/users` | GET | Paginated user list (`q`, `plan`, `suspended`, `limit`, `offset` filters) — email, name, admin/suspended flags, current plan, subscription status, signup date, last login, and **LLM spend in US$** (`SUM(AgentRun.costUsd)`) + run count. |
| `/api/admin/users/{user_id}` | GET | Full detail for one user: profile, subscription, quota, recent runs, spend (US$). 404 if the user doesn't exist. |
| `/api/admin/users/{user_id}/spend-cap` | POST | Set that user's per-period **USD** spend cap (`{"spendCapUsd": <number>}`). Writes an `AdminAuditLog` row. Flows directly into the pre-run quota reserve (§4 below) — take effect on the user's *next* agent run. |
| `/api/admin/users/{user_id}/suspend` | POST | Suspend the user: every one of their authenticated routes (including agent runs) now returns 403 (`apps/api/app/middleware/auth.py::get_current_user`) until lifted. Writes an audit row. |
| `/api/admin/users/{user_id}/unsuspend` | POST | Lift a suspension. Writes an audit row. |
| `/api/admin/spend` | GET | Platform-wide total LLM spend (US$) plus a per-user breakdown, both derived from `SUM(AgentRun.costUsd)` — genuine, not estimated. |
| `/api/admin/settings` | GET | Current values of the signup toggle and the (not-yet-enforced) email-verification toggle. |
| `/api/admin/settings` | POST | Update `signupEnabled` and/or `emailVerificationEnabled`. Flipping `signupEnabled` to `false` makes `POST /auth/register` return 403 immediately (verified live). Writes an audit row per call. |
| `/api/admin/audit-log` | GET | Paginated, newest-first, **append-only** log of every admin mutation above (actor, action, target type/id, before/after detail, caller IP). There is no delete or edit endpoint for this log — the only supported operation is insert. |

Frontend pages mirror this 1:1 under `/admin` (overview), `/admin/users`, `/admin/users/[id]`,
`/admin/spend`, `/admin/settings`, `/admin/audit-log`, plus `/admin/health` — all gated client-side
by `apps/web/src/components/admin/admin-guard.tsx` (which itself trusts the backend's `isAdmin`
check, not the other way around).

---

## 4. Spend-cap-before-LLM behavior

Every **metered** agent run (`tailor`, `coverLetter`, `storyExtractor`, `emailAgent` — the four
agents that actually call an LLM; `scout`, `fitScorer`, `matcher`, `supervisor` make zero LLM calls
and are never metered) goes through a single chokepoint, `_record_run()` in
`apps/api/app/routers/agents.py`. Before the LLM is invoked:

1. `UsageQuotaRepository.reserve(user_id)` runs one atomic `UPDATE ... WHERE runsUsed < runsAllowed
   AND spendUsedUsd < spendCapUsd` (rolling the billing period over if it has expired). If the row
   comes back, the run proceeds. If not, the caller gets **HTTP 429** — `quota_exceeded` if the
   monthly run count is exhausted, `spend_cap_exceeded` if the USD spend cap is hit — **before any
   LLM call is made**.
2. This was verified live: a temporary QA admin set a real user's `spendCapUsd` to `$0`, then that
   user's next agent-run request returned 429 `spend_cap_exceeded` with **zero** new `AgentRun` rows
   created — i.e., the LLM was never invoked (`qa-prod-console-admin.json`).
3. On a completed (200) run, the actual cost is added to `spendUsedUsd` after the fact (LLM cost is
   only known post-hoc). On any failure, the reserved run slot is refunded (`runsUsed` decremented)
   so a failed run never counts against the user's quota.

**Honest caveat:** because true per-run cost is unknowable until the run finishes, the cap is a
pre-run gate on *accumulated* spend, not a mid-run kill switch — a single run can still push
`spendUsedUsd` slightly over `spendCapUsd`, but the *next* reserve then fails. Default USD caps by
plan (admin-adjustable per user): Free $1, Starter $5, Pro $15, Power $40 — sized several times the
representative real cost per plan to absorb normal variance while still capping abuse.

---

## 5. Currency: spend is US$, prices are A$

**All spend figures in the admin panel (`/admin/users`, `/admin/users/{id}`, `/admin/spend`, and the
spend-cap-set endpoint) are US dollars**, because the LLM provider (OpenRouter, billed per
`AgentRun.costUsd`) invoices in USD. This is a deliberate split from the **subscription prices**,
which are always AUD, GST-inclusive (see `docs/subscription/terms-of-service.md`). Do not confuse
the two: setting a user's spend cap to `15` means US$15/month of LLM cost headroom, not A$15.

---

## 6. What is NOT built yet (be honest about this)

- **Per-user data export/delete from the admin panel** (§15 Tier 2) is deferred — `AdminAuditLog`
  and suspend/spend-cap/settings mutations exist and are audited, but there is no admin-facing
  "export this user's data" or "delete this user" button yet (GAP-P6-ADMIN-003, Tier 2 backlog).
- **Role granularity** — there is exactly one privilege level (`isAdmin: true/false`). There is no
  "read-only admin" or "support agent" tier.
- **In-app credential rotation UI** — rotating the admin password today means generating a new
  bcrypt hash and updating the environment variable + restart, not a settings-page flow.
- **Email-verification enforcement** — the `emailVerificationEnabled` toggle exists and is
  readable/settable, but no code path currently blocks registration or login on it; it is a
  placeholder switch for a future enforcement pass.
