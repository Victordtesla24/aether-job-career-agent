# MANUAL-VERIFICATION — admin-audit-log

**Screen id:** admin-audit-log | **Route:** `/admin/audit-log` | **Backing endpoint:** `GET /admin/audit-log`
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
| Route-surface probes: `DELETE /admin/audit-log`, `DELETE /admin/audit-log/1`, `PATCH /admin/audit-log/1` | Yes | 405 / 404 / 404 respectively — no mutate route exists |
| Audit-log table render, pagination | **No — HUMAN-GATED** | Never rendered |

## Findings

See `findings.json`. One finding filed:

| id | severity | category | summary |
|---|---|---|---|
| MV-admin-audit-log-001 | LOW | coverage-gap | No wireframe for `/admin/audit-log`. |

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| CLM-044 — admin flows verified live via temp admin account; formal closure pending | **PARTIALLY-TRUE** (see admin-root report §7) | `../admin-root/test-artifacts/login-response-redacted.json` |
| CLM-089 — 401 unauth / 403 non-admin | **CONFIRMED** for `GET /admin/audit-log` (401×2/403×2). | `../admin-root/test-artifacts/run1-api-transcript.txt`, `run2-api-transcript.txt` |
| CLM-100 — signup toggle exists; audit log entries cannot be edited/deleted | **PARTIALLY-TRUE.** Immutability half — **CONFIRMED** [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-17T15:4x–15:5xZ, two independent passes]: `DELETE /admin/audit-log` → 405 Method Not Allowed (only GET registered); `DELETE`/`PATCH /admin/audit-log/1` → 404 Not Found (no id-scoped mutate route exists at all). This directly demonstrates the "append-only" design — there is no code path by which an audit row could be edited or deleted via the API. Signup-toggle half — UNVERIFIABLE-FROM-UI (owned by admin-settings, requires admin access). | `test-artifacts/pass1-audit-export-checks.txt`, `test-artifacts/verify-twice-audit-export-checks.txt` |

## UNSURE items

None specific to this screen — the immutability half of CLM-100 was cleanly confirmed with fresh, reproducible, non-ambiguous evidence.

## Screenshots index

- `test-artifacts/passA-unauth-admin-audit-log-fullpage.png` / `passB-unauth-admin-audit-log-fullpage.png` — unauthenticated
- `test-artifacts/passA-authed-admin-audit-log-fullpage.png` / `passB-authed-admin-audit-log-fullpage.png` — demoted-authenticated

## Console / network / server-log summary

0 console errors, 0 failed requests across both Playwright passes. 0 occurrences of `admin/audit-log` returning 5xx anywhere in `/var/log/aether/api.log` history. The two mutate-route probes (405/404) were themselves clean, expected framework responses, not errors.

## NOT-TESTED (HUMAN-GATED)

- `/admin/audit-log` table rendering, pagination (`limit`/`offset`) as a real operator-admin.
- Confirming that admin mutations performed by a real admin actually produce new audit rows with correct `actor`/`action`/`target`/`detail`/`ip` fields populated (would require performing an actual admin mutation, which needs the human-gated credential).

**Reason:** HUMAN-GATED — no operator-admin credential configured in production. See admin-root report §0/§9.

## Sign-off

Tester: screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1, admin cluster. All checks reproduced in a fresh session (§3.2 point 9); no FLAKY items. Session 2026-07-17T15:36:55Z – 15:51:13Z UTC.
