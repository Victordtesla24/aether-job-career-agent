# MANUAL-VERIFICATION — admin-health

**Screen id:** admin-health | **Route:** `/admin/health` | **Backing endpoint:** `GET /admin/health`
**Wireframe:** none (`coverage_gap: "route-without-wireframe"`)
**Full cluster methodology, shared evidence, and consolidated claim table:** see [`screens/admin-root/TESTING-OUTCOME-REPORT.md`](../admin-root/TESTING-OUTCOME-REPORT.md) — this document scopes that same session to this one screen.
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616` | **Session (UTC):** 2026-07-17T15:36:55Z – 15:51:13Z
**Production URL:** https://5cb5f0620.abacusai.cloud

## Element inventory

| Element | Tested | Result |
|---|---|---|
| `AdminGuard` interstitial ("Verifying admin access…") | Yes | Renders, then redirects; no admin data present |
| Redirect target, unauthenticated | Yes | `/login`, clean, 0 console errors |
| Redirect target, authenticated as demoted `admin`/`admin123` | Yes | `/dashboard`, clean, 0 console errors |
| Service/agent-success-rate/cron/provider status detail widgets (the actual screen content) | **No — HUMAN-GATED** | Never rendered; no admin credential available |

## Findings

See `findings.json` in this folder. One finding filed:

| id | severity | category | summary |
|---|---|---|---|
| MV-admin-health-001 | LOW | coverage-gap | No wireframe exists for `/admin/health`; visual conformance could not be checked against a design spec (pre-existing, documented gap). |

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| CLM-089 — all 10 `/admin/*` routes gated server-side (401 unauth / 403 non-admin) | **CONFIRMED** for `GET /admin/health` specifically: unauth → 401 `Not authenticated` (×2 passes); demoted user → 403 `Admin privileges required` (×2 passes). Full 10-endpoint table in the admin-root report §4. | `../admin-root/test-artifacts/run1-api-transcript.txt`, `run2-api-transcript.txt` |

## UNSURE items

None specific to this screen.

## Screenshots index

- `test-artifacts/passA-unauth-admin-health-fullpage.png` / `passB-unauth-admin-health-fullpage.png` — unauthenticated, redirected to `/login`
- `test-artifacts/passA-authed-admin-health-fullpage.png` / `passB-authed-admin-health-fullpage.png` — demoted-authenticated, redirected to `/dashboard`

## Console / network / server-log summary

0 console errors, 0 failed requests across both Playwright passes (unauth + authed). 0 occurrences of `admin/health` returning a 5xx anywhere in `/var/log/aether/api.log` history. Full detail in the admin-root report §6.

## NOT-TESTED (HUMAN-GATED)

- The actual `/admin/health` content (service status, agent success-rate, cron status, provider status cards) as a real operator-admin. **Reason:** no operator-admin credential is configured in production (`AETHER_ADMIN_EMAIL`/`AETHER_ADMIN_PASSWORD_HASH` absent; `admin`/`admin123` confirmed `isAdmin:false` live). See admin-root report §0 and §9.

## Sign-off

Tester: screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1, admin cluster. Both checks reproduced in a fresh session (§3.2 point 9); no FLAKY items. Session 2026-07-17T15:36:55Z – 15:51:13Z UTC.
