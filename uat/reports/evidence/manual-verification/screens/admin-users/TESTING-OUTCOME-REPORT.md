# MANUAL-VERIFICATION — admin-users

**Screen id:** admin-users | **Routes:** `/admin/users`, `/admin/users/[id]`
**Backing endpoints:** `GET /admin/users`, `GET /admin/users/{id}`, `POST /admin/users/{id}/spend-cap`, `POST /admin/users/{id}/suspend`, `POST /admin/users/{id}/unsuspend`
**Wireframe:** none (`coverage_gap: "route-without-wireframe"`)
**Full cluster methodology, shared evidence, and consolidated claim table:** see [`screens/admin-root/TESTING-OUTCOME-REPORT.md`](../admin-root/TESTING-OUTCOME-REPORT.md)
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616` | **Session (UTC):** 2026-07-17T15:36:55Z – 15:51:13Z
**Production URL:** https://5cb5f0620.abacusai.cloud

## Element inventory

| Element | Tested | Result |
|---|---|---|
| `AdminGuard` interstitial | Yes | Renders, then redirects; no admin data present |
| `/admin/users` redirect, unauthenticated | Yes | `/login`, clean, 0 console errors |
| `/admin/users` redirect, demoted user | Yes | `/dashboard`, clean, 0 console errors |
| `/admin/users/[id]` redirect, unauthenticated (fake id `test-fake-id-mv-admin-userdetail`) | Yes | `/login`, clean, 0 console errors |
| `/admin/users/[id]` redirect, demoted user | Yes | `/dashboard`, clean, 0 console errors |
| Users list (search, plan filter, suspended filter, pagination) | **No — HUMAN-GATED** | Never rendered |
| User detail panel, spend-cap input + save, suspend/unsuspend toggle | **No — HUMAN-GATED** | Never rendered |

## Findings

See `findings.json`. Two findings filed:

| id | severity | category | summary |
|---|---|---|---|
| MV-admin-users-001 | LOW | coverage-gap | No wireframe for `/admin/users` / `/admin/users/[id]`. |
| MV-admin-users-002 | LOW | coverage-gap | CLM-101's claimed data export/delete capability has no backing API endpoint anywhere (`GET .../export` → 404, `DELETE /admin/users/{id}` → 405), live-probed twice and source-confirmed. Filed as UNSURE (not flat refuted) since the real admin UI is human-gated. |

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| CLM-044 — admin flows verified live via temporary admin account; formal closure needs operator-rotated credential | **PARTIALLY-TRUE.** "Formal closure blocked" — CONFIRMED (credentials still absent, live-reconfirmed). "Verified via temp admin account" — UNVERIFIABLE-FROM-UI (no credential to reproduce). | `../admin-root/test-artifacts/login-response-redacted.json` |
| CLM-089 — 401 unauth / 403 non-admin on all 10 routes | **CONFIRMED** for the 5 admin-users-owned endpoints specifically: `GET /admin/users` (401×2/403×2), `GET /admin/users/{id}` (401×2/403×2), `POST .../spend-cap` (401×2/403×2), `POST .../suspend` (401×2/403×2), `POST .../unsuspend` (401×2/403×2). | `../admin-root/test-artifacts/run1-api-transcript.txt`, `run2-api-transcript.txt` |
| CLM-101 — admin panel provides data export/delete capability for user data | **UNSURE, leaning REFUTED.** No backing endpoint found anywhere in the API (live-probed twice + full source review of `admin.py`/`main.py`); real admin UI un-inspectable (human-gated) so a dead button can't be formally ruled out. | `test-artifacts/verify-twice-audit-export-checks.txt`, `test-artifacts/pass1-audit-export-checks.txt` |

## UNSURE items

1. **CLM-101** — see above. Recommend orchestrator treat as REFUTED-pending-operator-confirmation.

## Screenshots index

- `test-artifacts/passA-unauth-admin-users-fullpage.png` / `passB-unauth-admin-users-fullpage.png` — unauthenticated `/admin/users`
- `test-artifacts/passA-authed-admin-users-fullpage.png` / `passB-authed-admin-users-fullpage.png` — demoted-authenticated `/admin/users`
- `test-artifacts/passB-unauth-admin-users-detail-fullpage.png` / `passB-authed-admin-users-detail-fullpage.png` — `/admin/users/[id]` dynamic route (both phases; pass A produced byte-identical outcomes per `sweep-userid-result-passA.json`, screenshot overwritten by pass B's run — outcome data preserved in both JSON files)

## Console / network / server-log summary

0 console errors, 0 failed requests across all passes (list route ×4, detail route ×2). 0 occurrences of any `admin/users*` path returning 5xx anywhere in `/var/log/aether/api.log` history.

## NOT-TESTED (HUMAN-GATED)

- `/admin/users` list rendering, search (`q`), plan filter, suspended filter, pagination (`limit`/`offset`) as a real operator-admin.
- `/admin/users/[id]` detail rendering: activity, subscription, quota, recent runs, spend (US$) panels.
- Spend-cap input + save button functional test (would exercise `POST /admin/users/{id}/spend-cap` with a real 200).
- Suspend/unsuspend toggle button functional test (would exercise `POST /admin/users/{id}/suspend` and `/unsuspend` with real 200s) and confirming a suspended user actually gets 403 on their own authenticated routes.
- CLM-101's UI-layer confirmation (whether a dead button exists despite no backend).

**Reason for all items above:** HUMAN-GATED — no operator-admin credential configured in production. See admin-root report §0/§9.

## Sign-off

Tester: screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1, admin cluster. All checks reproduced in a fresh session (§3.2 point 9); no FLAKY items. Session 2026-07-17T15:36:55Z – 15:51:13Z UTC.
