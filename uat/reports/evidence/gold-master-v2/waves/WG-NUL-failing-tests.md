# WG-NUL-failing-tests — GOLD-MASTER-V2 §9.4 + NUL-scope-extension

Test-author brief: write FAILING tests for the W-G admin entry points
(§9.2.1/§9.2.2/§9.2.3) and the ML-admin-003 query-param NUL gap. **No
implementation code was touched** — this session wrote tests only, per
§0.4.

All timestamps UTC. Repo: `/home/ubuntu/github_repos/aether-job-career-agent`
(no remote — local checkout only). All commands run from the repo root
unless noted.

---

## Defect 1 — ML-admin-003 (NUL byte in GET query params)

### Headline finding: the described defect does NOT reproduce against current repo HEAD

[VERIFIED-WITH-FRESH-EVIDENCE, this file + timestamps below] I probed the
exact repro from the assignment brief (`GET /admin/users?q=<NUL>` /
`?plan=<NUL>`) against the current checked-out code (no commits made) and
it returns a clean **422**, not a 500:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_ml_admin_003_nul_query_param.py -v"
...
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_q_nul_byte_returns_422_not_500 PASSED [  4%]
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_plan_nul_byte_returns_422_not_500 PASSED [  9%]
```
Run at 2026-07-31T07:51Z (see `pytest-final.txt` captured alongside this
report in the same evidence run — reproduced below).

**RCA**: `apps/api/app/db.py`'s `_NulByteGuardCursor` is installed as the
`cursor_factory` on *every* connection `get_connection()` yields (line
~150) — this is a blanket interception at the psycopg2-cursor layer, not
scoped to write paths. `apps/api/app/repositories/admin.py::list_users`
opens its connection via that same `get_connection()` (verified: the only
`psycopg2.connect(` call site in the whole app is inside `get_connection`
itself — `grep -rn "psycopg2.connect(" apps/api/app` returns exactly one
hit). So a NUL byte in `q`/`plan` already hits the shared guard.

Cross-referencing `git log --oneline`: the shared guard commit
(`e78f51d`, "shared NUL-byte guard, admin/billing hardening") predates the
docs commit that recorded ML-admin-003 as OPEN (`16b04ad`, "admin sweep
complete... ML-admin-003 NUL query-param gap"). The screen-test evidence
(`uat/reports/evidence/gold-master-v2/screens/admin-portal-screen-test.md`)
that produced the two live 500s ran against the **deployed production
build**, which had not yet picked up `e78f51d` — its own text says so:
*"consistent with — and extending — the platform's already-known,
fix-verified-but-undeployed NUL-byte defect class."*

**Conclusion**: ML-admin-003 as literally described (a code-level gap) is
already closed in the repository; what remains open is a **deployment
lag** (the fix exists in git, prod hasn't been redeployed since). This is
not a defect in my test — it is the correct, honest result of running the
test against the actual current code, as instructed. Per my brief's own
anticipated outcome, I report this as an **unexpected pass with a
documented reason**, not a silently-accepted green.

### What I did instead (useful, non-fake deliverable)

Since a literal "expect 500, prove it fails" test would be dishonest
against current code, I wrote the tests as the **regression-locking
contract** (422, honest message, no traceback, filtering still works) and
ran a **sweep** of every other GET endpoint in the codebase taking a
free-form user-supplied filter string, to find out whether the shared
guard's coverage is actually as comprehensive as `db.py`'s docstring
claims, or whether some OTHER endpoint has a genuine, currently-reproducible
gap. It does not — every endpoint checked is already safe (either via the
same shared cursor guard, or via a pre-existing allowlist check identical
in spirit to `analytics.py`'s `_period_clause` pattern the brief pointed
to as "the correct pattern").

### Endpoint coverage (exact)

**Covered — FREE-TEXT filters (unvalidated, reach SQL via `%s`, exercise
the shared cursor guard); each has a NUL-byte case + a non-NUL sanity
case:**

| Endpoint | File |
|---|---|
| `GET /admin/users?q=` | `apps/api/app/repositories/admin.py` |
| `GET /admin/users?plan=` | `apps/api/app/repositories/admin.py` |
| `GET /networking/contacts?company=` | `apps/api/app/routers/networking.py` |
| `GET /networking/outreach?contact_id=` | `apps/api/app/routers/networking.py` |
| `GET /workspaces/emails/inbox?thread_id=` | `apps/api/app/routers/workspaces.py` |
| `GET /interviews?application_id=` | `apps/api/app/routers/interviews.py` |

**Covered — ENUM-VALIDATED filters** (rejected by an application-level
allowlist check *before* reaching SQL — a NUL byte just fails "not in
{allowed values}" like any other bad value; one confirmatory test each,
no separate sanity case needed since normal-filter coverage already
exists elsewhere in the suite):

| Endpoint | File |
|---|---|
| `GET /jobs?status=` | `apps/api/app/routers/jobs.py` |
| `GET /jobs?source=` | `apps/api/app/routers/jobs.py` |
| `GET /applications?app_status=` | `apps/api/app/routers/applications.py` |
| `GET /interviews?app_status=` | `apps/api/app/routers/interviews.py` |
| `GET /approvals?status=` | `apps/api/app/routers/approvals.py` |
| `GET /networking/contacts?stage=` | `apps/api/app/routers/networking.py` |
| `GET /networking/outreach?task_status=` | `apps/api/app/routers/networking.py` |

**NOT covered (explicit, not silently assumed closed):**

- `apps/api/app/routers/stories.py`, `cover_letters.py`, `agents.py`,
  `analytics.py` — all on this assignment's explicit "stay out, other
  agents active" list. Not touched, not exercised, not probed.
  `analytics.py`'s `?period=` was already independently verified correct
  by the assignment brief itself (422, honest message) and is not
  re-tested here.
- Any GET endpoint whose query params are `int`/`bool`-typed only
  (`/admin/audit-log?limit=&offset=`, `/admin/health`, `/admin/spend`) — a
  NUL byte there is rejected by FastAPI's own request validation before
  any application code runs; no code path to test.
- POST/PATCH/DELETE body fields (write paths) — out of scope for this
  GET-query-param finding; already covered by the pre-existing
  ML-settings-006 / ML-RESUME-001 tests referenced in `db.py`'s docstring.
- I did not attempt a raw/non-percent-encoded NUL byte directly in the URL
  path (as opposed to the query string) — out of scope (the finding and
  brief are both specifically about query params).

### Discovery method

`grep -rn "Query(" apps/api/app/routers/*.py` plus a manual regex sweep
for bare `str | None = None` GET parameters, then read each matching
handler's body to classify it free-text vs. enum-validated (see the test
file's own module docstring for the full discovery trail, which is
reproduced in this report).

### Empirical probe transcript (before finalizing the test file)

Isolated a genuine ground-truth check to make sure the "guard is
comprehensive" theory wasn't a misreading — ran a raw-cursor probe
directly against `get_connection()` with the exact WHERE-clause shape used
by `workspaces.py`'s email-inbox lookup:

```
EXCEPTION TYPE: <class 'fastapi.exceptions.HTTPException'> MSG: 422: Invalid input: a field contains an unsupported NUL (0x00) character.
```

(This also caught and corrected my own initial test-authoring mistake: I
first hit `GET /emails/inbox` — which is NOT the workspaces email-center
endpoint at all, but matches `emails.py`'s `GET /{thread_id}` path
parameter with `thread_id="inbox"`, a 404 unrelated to NUL handling. The
real path, confirmed via `grep -n "@router.get(\"/emails" workspaces.py`
combined with its `/workspaces` mount prefix in `main.py`, is
`/workspaces/emails/inbox`. Fixed in the final test file.)

### Full pytest transcript

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_ml_admin_003_nul_query_param.py -v"
[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=aether_test — safe to proceed.
============================= test session starts ==============================
...
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_q_nul_byte_returns_422_not_500 PASSED [  4%]
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_plan_nul_byte_returns_422_not_500 PASSED [  9%]
tests/test_ml_admin_003_nul_query_param.py::test_networking_contacts_company_nul_byte_returns_422_not_500 PASSED [ 14%]
tests/test_ml_admin_003_nul_query_param.py::test_networking_outreach_contact_id_nul_byte_returns_422_not_500 PASSED [ 19%]
tests/test_ml_admin_003_nul_query_param.py::test_workspaces_emails_inbox_thread_id_nul_byte_returns_422_not_500 PASSED [ 23%]
tests/test_ml_admin_003_nul_query_param.py::test_interviews_application_id_nul_byte_returns_422_not_500 PASSED [ 28%]
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_q_sanity_normal_filter_still_works PASSED [ 33%]
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_plan_sanity_normal_filter_still_works PASSED [ 38%]
tests/test_ml_admin_003_nul_query_param.py::test_networking_contacts_company_sanity_normal_filter_still_works PASSED [ 42%]
tests/test_ml_admin_003_nul_query_param.py::test_networking_outreach_contact_id_sanity_normal_filter_still_works PASSED [ 47%]
tests/test_ml_admin_003_nul_query_param.py::test_workspaces_emails_inbox_thread_id_sanity_normal_filter_still_works PASSED [ 52%]
tests/test_ml_admin_003_nul_query_param.py::test_interviews_application_id_sanity_normal_filter_still_works PASSED [ 57%]
tests/test_ml_admin_003_nul_query_param.py::test_jobs_status_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 61%]
tests/test_ml_admin_003_nul_query_param.py::test_jobs_source_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 66%]
tests/test_ml_admin_003_nul_query_param.py::test_applications_app_status_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 71%]
tests/test_ml_admin_003_nul_query_param.py::test_interviews_app_status_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 76%]
tests/test_ml_admin_003_nul_query_param.py::test_approvals_status_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 80%]
tests/test_ml_admin_003_nul_query_param.py::test_networking_contacts_stage_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 85%]
tests/test_ml_admin_003_nul_query_param.py::test_networking_outreach_task_status_nul_byte_returns_422_via_allowlist_not_500 PASSED [ 90%]
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_nul_byte_recovers_for_next_normal_request[q] PASSED [ 95%]
tests/test_ml_admin_003_nul_query_param.py::test_admin_users_nul_byte_recovers_for_next_normal_request[plan] PASSED [100%]
======================= 21 passed, 19 warnings in 33.61s =======================
```
[VERIFIED-WITH-FRESH-EVIDENCE, run at 2026-07-31T07:51Z]

### Unexpected passes (all 21 — documented, not silently accepted)

Every test in `apps/api/tests/test_ml_admin_003_nul_query_param.py`
"unexpectedly" passes relative to the brief's framing of ML-admin-003 as a
still-open code defect. Meaning, per test group:

- The 6 free-text NUL-byte cases + `test_admin_users_nul_byte_recovers_...`
  (8 total): PASS because the shared `_NulByteGuardCursor` in `db.py`
  already covers this exact path (see RCA above) — the code fix already
  shipped to the repo, just not to production.
- The 6 non-NUL sanity cases: PASS as *designed* — these were never meant
  to fail; they exist to prove a future fix can't over-broadly break real
  filtering. Their passing is expected and correct.
- The 7 enum-validated confirmatory cases: PASS because they were never at
  risk (allowlist check runs before any SQL) — included to make the sweep
  boundary explicit rather than assumed.

**Recommendation for the orchestrator**: ML-admin-003 should be
re-classified from "OPEN, code gap" to "OPEN, deploy gap only" — the fix
is sitting in git (`e78f51d`) and this test file now locks it in as a
regression guard for when it does deploy.

---

## Defect 2 — W-G §9.2 admin entry points

### Test 4 — §9.2.1: `/login` has no admin entry point

File: `apps/web/src/app/login/__tests__/wg-admin-entry-004.test.tsx`
(vitest + RTL, renders the real `LoginPage` component — no server needed).

```
$ cd apps/web && npx vitest run src/app/login/__tests__/wg-admin-entry-004.test.tsx
 FAIL  src/app/login/__tests__/wg-admin-entry-004.test.tsx > W-G §9.2.1: /login admin entry point > exposes a clearly-labelled "Admin" entry point linking to an admin login path
TestingLibraryElementError: Unable to find an accessible element with the role "link" and name `/admin/i`
...
 ❯ src/app/login/__tests__/wg-admin-entry-004.test.tsx:49:30
     47|     render(<LoginPage />);
     48|
     49|     const adminLink = screen.getByRole("link", { name: /admin/i });
       |                              ^
 Test Files  1 failed (1)
      Tests  1 failed (1)
```
[VERIFIED-WITH-FRESH-EVIDENCE, run at 2026-07-31T07:48Z, full transcript in
`vitest-output.txt` captured alongside this evidence session]

Fails for the right reason: `LoginPage.tsx`'s rendered tree (read in full)
has exactly logo, sign-in form, "Create account" link, "Forgot password?"
link, and the privacy/terms footer — no link with an accessible name
matching "admin" anywhere. Confirmed the pre-existing suite
(`page.test.tsx`, 10 tests) and `topbar.test.tsx` (5 tests) both still pass
unmodified/unaffected by this addition (`npx vitest run
src/app/login/__tests__/ src/components/__tests__/topbar.test.tsx` — 1
failed | 15 passed).

### Test 6 — §9.2.3: no persistent Admin indicator outside `/admin/*`

File: `apps/web/src/components/__tests__/wg-admin-indicator-006.test.tsx`
(vitest + RTL, renders the real `Topbar` component, mocking `fetchMe` from
`lib/api/admin.ts` — the same, already-existing isAdmin source
`admin-guard.tsx` uses today — as the natural minimal integration point).

```
$ cd apps/web && npx vitest run src/components/__tests__/wg-admin-indicator-006.test.tsx
 × W-G §9.2.3: persistent Admin indicator outside /admin/* > shows a persistent Admin indicator in the shell for a logged-in admin
AssertionError: logged-in admin: expected a persistent 'Admin' indicator somewhere in the Topbar/UserMenu shell (outside /admin/*); none was rendered: expected null not to be null
 ✓ W-G §9.2.3: persistent Admin indicator outside /admin/* > shows NOTHING admin-related for a standard (non-admin) user
 Test Files  1 failed (1)
      Tests  1 failed | 1 passed (1)
```
[VERIFIED-WITH-FRESH-EVIDENCE, run at 2026-07-31T07:48Z]

Both halves asserted as instructed: the POSITIVE case (admin sees an
indicator) fails for the right reason — `Topbar.tsx`/`UserMenu.tsx` (read
in full) have zero `isAdmin` awareness today, no import of `fetchMe` or
anything from `lib/api/admin`. The NEGATIVE case (standard user sees
nothing admin-related) correctly PASSES as a sanity guard against an
over-broad fix that labels every user "Admin".

### Tests 5 & 7 — §9.2.2 admin login reaches `/admin`; non-admin refused honestly

File: `apps/web/e2e/wg-admin-login-path.spec.ts` (Playwright, real browser,
real HTTP, real Postgres — no mocks). Both tests start from `/login` and
look for the §9.2.1 entry link (rather than hard-coding an unbuilt page
name), then assert the FINAL observable outcome, so they hold regardless
of exactly how the fixer implements the entry point.

**Isolated test environment** (mirrors the existing convention in
`apps/web/e2e/ml-admin-002-mobile-overflow.spec.ts` — own ports, own
`aether_test`-schema fixture users; the shared "chromium" project's
`setup` dependency logs into the LIVE PRODUCTION-pointed default `.env`
credential (`LOGIN_EMAIL=sarkar.vikram@gmail.com`), which per this
assignment's own CRITICAL warning is about to be de-privileged by
BLOCKER-001 — never used here):

1. Isolated API: `uvicorn app.main:app --host 127.0.0.1 --port 8090`,
   env = `DATABASE_URL`/`DATABASE_URL_TEST` pointed at the
   `aether_test` schema (same DSN `scripts/run-tests.sh` uses, read
   directly from `.env`'s `DATABASE_URL_TEST` line — never sourced the
   whole `.env`, never touched `DATABASE_URL`'s production value),
   `AETHER_LLM_MODE=replay`, `AETHER_REQUIRE_PAID_SUBSCRIPTION=false`,
   `AETHER_ASYNC_GENERATION=false`, a deterministic
   `AETHER_CREDENTIAL_KEY` (same one `conftest.py` defaults to).
2. Isolated web: `next dev -p 3095` with `AETHER_API_PROXY=http://127.0.0.1:8090`
   (the same rewrite hook `next.config.js` documents for exactly this
   purpose) so the browser's same-origin `/api/*` calls proxy to the
   isolated API, never to the production `aether-api.service` on :8000.
3. Fixture users created via `POST /auth/register` against the isolated
   API (random-uuid emails `wg-admin-<hex>@example.com` /
   `wg-user-<hex>@example.com`), the admin promoted via one direct
   `UPDATE "User" SET "isAdmin"=true` against the `aether_test` schema
   (same pattern as `test_ml_admin_001.py::_promote`) — never the seeded
   `admin` identifier.
4. `npx playwright test wg-admin-login-path.spec.ts --project=chromium
   --no-deps` (`--no-deps` skips the shared config's `setup` project,
   which would otherwise try to log into production first).
5. Torn down immediately after the run (`kill` both processes; confirmed
   via `ss -ltnp | grep -E "8090|3095"` returning nothing).

```
$ cd apps/web && WG_E2E_BASE_URL=http://127.0.0.1:3095 \
  WG_E2E_ADMIN_EMAIL=wg-admin-68075c7601@example.com \
  WG_E2E_USER_EMAIL=wg-user-519a113ab2@example.com \
  WG_E2E_PASSWORD=WgE2eTest1 \
  npx playwright test wg-admin-login-path.spec.ts --project=chromium --no-deps --reporter=list

Running 2 tests using 1 worker

  ✘  1 [chromium] › ... an admin login reaches /admin (the real admin portal), not /dashboard (5.8s)
  ✘  2 [chromium] › ... a non-admin hitting the admin login path is refused honestly, with no user-enumeration signal (5.8s)

  1) ...
    Error: §9.2.1: no 'Admin' entry link found on /login — the admin login path is unreachable from the public sign-in screen
    expect(locator).toBeVisible() failed
    Locator: getByRole('link', { name: /admin/i })
    Expected: visible
    Timeout: 5000ms
    Error: element(s) not found

  2) ...
    Error: §9.2.1: no 'Admin' entry link found on /login — cannot exercise the refusal contract without the entry point existing
    expect(locator).toBeVisible() failed
    Locator: getByRole('link', { name: /admin/i })
    Expected: visible
    Timeout: 5000ms
    Error: element(s) not found

  2 failed
```
[VERIFIED-WITH-FRESH-EVIDENCE, run at 2026-07-31T07:50:59Z, full transcript
captured to `playwright-output.txt` in this evidence session]

Both fail at the identical, correct root cause — the missing §9.2.1 entry
link — proven against the REAL running app (real browser navigation, real
backend, real Postgres), not a mock. This honestly demonstrates that tests
5 and 7's downstream contracts (land on `/admin`; refuse a non-admin
without an enumeration-adjacent message) cannot even be exercised yet,
because the chain starts with an element that does not exist. Once the
entry link is built, these tests will proceed past `findAdminEntryLink`
and exercise their real downstream assertions (URL === `/admin`; no
admin-specific denial text) for the first time.

Preflight sanity of the isolated environment itself (proving the harness,
not the app, is sound):
```
$ curl -s http://127.0.0.1:8090/auth/me -H "Authorization: Bearer $TOKEN"
{"id":"c54f149b1b70363ea562b7596","email":"wg-admin-68075c7601@example.com","name":"","targetRole":"","location":"","isAdmin":true}
$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/admin/users -H "Authorization: Bearer $TOKEN"
200
$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3095/api/health
200
```

---

## Files delivered

- `apps/api/tests/test_ml_admin_003_nul_query_param.py` (backend, 21 tests
  — all PASS, documented as an unexpected-pass/deploy-gap finding above)
- `apps/web/src/app/login/__tests__/wg-admin-entry-004.test.tsx` (vitest,
  1 test — FAILS)
- `apps/web/src/components/__tests__/wg-admin-indicator-006.test.tsx`
  (vitest, 2 tests — 1 FAILS / 1 PASSES by design)
- `apps/web/e2e/wg-admin-login-path.spec.ts` (Playwright, 2 tests — both
  FAIL)

## Not implemented

No production/implementation code was changed by this session. §9.2.1,
§9.2.2, §9.2.3 (the admin entry point) and the production→repo deploy lag
for ML-admin-003 remain for a fixer + deployer respectively.
