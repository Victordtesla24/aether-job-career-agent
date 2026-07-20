# MANUAL-VERIFICATION — admin-spend

**Screen id:** admin-spend | **Route:** `/admin/spend` | **Backing endpoint:** `GET /admin/spend`
**Wireframe:** none (`coverage_gap: "route-without-wireframe"`)
**Full cluster methodology, shared evidence, and consolidated claim table:** see [`screens/admin-root/TESTING-OUTCOME-REPORT.md`](../admin-root/TESTING-OUTCOME-REPORT.md)
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616` | **Session (UTC):** 2026-07-17T15:36:55Z – 15:51:13Z
**Production URL:** https://5cb5f0620.abacusai.cloud

## Element inventory

| Element | Tested | Result |
|---|---|---|
| `AdminGuard` interstitial | Yes | Renders, then redirects; no admin data present |
| Redirect, unauthenticated | Yes | `/login`, clean, 0 console errors |
| Redirect, demoted user | Yes | `/dashboard`, clean, 0 console errors |
| Spend totals / per-user spend table (the actual screen content) | **No — HUMAN-GATED** | Never rendered |

## Findings

See `findings.json`. One finding filed:

| id | severity | category | summary |
|---|---|---|---|
| MV-admin-spend-001 | LOW | coverage-gap | No wireframe for `/admin/spend`. |

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| CLM-044 — admin flows verified live via temp admin account; formal closure pending | **PARTIALLY-TRUE** (see admin-root report §7) | `../admin-root/test-artifacts/login-response-redacted.json` |
| CLM-088 — $0 spend cap blocks agent run before LLM dispatch (429, AgentRun count unchanged) | **UNVERIFIABLE-FROM-UI / HUMAN-GATED.** Requires `POST /admin/users/{id}/spend-cap` as an admin, which returned 403 for the only credential available to this tester. As a negative control, confirmed the endpoint itself is correctly gated (cannot be bypassed to attempt this flow). | `../admin-root/test-artifacts/run1-api-transcript.txt` row 4 |
| CLM-089 — 401 unauth / 403 non-admin | **CONFIRMED** for `GET /admin/spend` (401×2/403×2). | `../admin-root/test-artifacts/run1-api-transcript.txt`, `run2-api-transcript.txt` |

## UNSURE items

None specific to this screen — CLM-088 is a clean HUMAN-GATED item, not an ambiguous one.

## Screenshots index

- `test-artifacts/passA-unauth-admin-spend-fullpage.png` / `passB-unauth-admin-spend-fullpage.png` — unauthenticated
- `test-artifacts/passA-authed-admin-spend-fullpage.png` / `passB-authed-admin-spend-fullpage.png` — demoted-authenticated

## Console / network / server-log summary

0 console errors, 0 failed requests across both Playwright passes. 0 occurrences of `admin/spend` returning 5xx anywhere in `/var/log/aether/api.log` history.

## NOT-TESTED (HUMAN-GATED)

- `/admin/spend` total + per-user USD spend table rendering as a real operator-admin.
- CLM-088's full flow: set a $0 spend cap on a test user as admin, trigger an agent run as that user, confirm HTTP 429 and that `AgentRun` count stays at zero.

**Reason:** HUMAN-GATED — no operator-admin credential configured in production. See admin-root report §0/§9.

## Sign-off

Tester: screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1, admin cluster. All checks reproduced in a fresh session (§3.2 point 9); no FLAKY items. Session 2026-07-17T15:36:55Z – 15:51:13Z UTC.
