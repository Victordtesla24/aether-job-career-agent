# MANUAL-VERIFICATION — admin-settings

**Screen id:** admin-settings | **Route:** `/admin/settings` | **Backing endpoints:** `GET /admin/settings`, `POST /admin/settings`
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
| Throttled reload (50kbps/400ms), unauthenticated | Yes | Still redirects cleanly to `/login` in ~40s, 0 console errors, no broken/stuck state |
| Signup-enabled toggle, email-verification-enabled toggle, save action | **No — HUMAN-GATED** | Never rendered |

## Findings

See `findings.json`. Two findings filed:

| id | severity | category | summary |
|---|---|---|---|
| MV-admin-settings-001 | LOW | coverage-gap | No wireframe for `/admin/settings`. |
| MV-admin-settings-002 | LOW | validation | `POST /api/admin/settings` with a syntactically-invalid JSON body (unauthenticated) returns 422 before the 401 auth check fires; well-formed-but-wrong-type bodies correctly 401 first. No data disclosure. Reproduced twice. |

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| CLM-044 — admin flows verified live via temp admin account; formal closure pending | **PARTIALLY-TRUE** (see admin-root report §7 for full reasoning) | `../admin-root/test-artifacts/login-response-redacted.json` |
| CLM-089 — 401 unauth / 403 non-admin | **CONFIRMED** for `GET /admin/settings` (401×2/403×2) and `POST /admin/settings` (401×2/403×2 for well-formed bodies; see MV-admin-settings-002 for the malformed-JSON edge case). | `../admin-root/test-artifacts/run1-api-transcript.txt`, `run2-api-transcript.txt` |
| CLM-100 — signup toggle exists; audit log entries cannot be edited/deleted | **PARTIALLY-TRUE.** Audit-log immutability half — CONFIRMED live (405/404 on every mutate-shaped audit path, see admin-audit-log report). Signup-toggle functional effect — UNVERIFIABLE-FROM-UI (requires admin access to flip `signupEnabled` and observe signup behavior). | `../admin-audit-log/test-artifacts/verify-twice-audit-export-checks.txt` |
| CLM-101 — data export/delete capability | **UNSURE, leaning REFUTED** (full detail in admin-users report; no `/admin/settings`-specific export/delete route exists either). | `../admin-users/test-artifacts/verify-twice-audit-export-checks.txt` |

## UNSURE items

1. **CLM-100 (signup toggle functional effect)** — HUMAN-GATED, cannot be tested without admin access to flip the setting.
2. **MV-admin-settings-002 (422-before-401 ordering)** — genuinely minor, flagging for orchestrator triage on whether it's worth a fix.

## Screenshots index

- `test-artifacts/passA-unauth-admin-settings-fullpage.png` / `passB-unauth-admin-settings-fullpage.png` — unauthenticated
- `test-artifacts/passA-authed-admin-settings-fullpage.png` / `passB-authed-admin-settings-fullpage.png` — demoted-authenticated
- `test-artifacts/throttled-reload-admin-settings.png` — throttled unauthenticated reload

## Console / network / server-log summary

0 console errors, 0 failed requests across unauth ×2, authed ×2, and throttled reload runs. 0 occurrences of `admin/settings` returning 5xx anywhere in `/var/log/aether/api.log` history.

## NOT-TESTED (HUMAN-GATED)

- `/admin/settings` rendering (signup-enabled toggle, email-verification-enabled toggle) and their save behavior as a real operator-admin.
- Functional confirmation that flipping `signupEnabled` actually blocks/allows new signups (CLM-100 second half).

**Reason:** HUMAN-GATED — no operator-admin credential configured in production. See admin-root report §0/§9.

## Sign-off

Tester: screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1, admin cluster. All checks reproduced in a fresh session (§3.2 point 9); no FLAKY items. Session 2026-07-17T15:36:55Z – 15:51:13Z UTC.
