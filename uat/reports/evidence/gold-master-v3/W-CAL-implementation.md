# W-CAL — Google Calendar: OAuth scope expansion + interview event creation

**Workstream**: GOLD-MASTER V4 §10 / W-CAL
**Agent**: fixer-hard
**Date**: 2026-08-01 (UTC)
**Repo**: `/home/ubuntu/github_repos/aether-job-career-agent`
**ADR**: `docs/delivery/ADR-CALENDAR-V4.md`
**Method**: tests first (§15) — red proven before any production line was written.

Every claim below is tagged `[VERIFIED]` with the command that produced it. Nothing here
is asserted from reading code alone.

---

## 1. Starting state (confirmed independently, not taken on trust)

`[VERIFIED 2026-08-01T22:32Z — apps/api/app/services/google_oauth.py:54-61 read directly]`

`GOOGLE_SCOPES` contained six scopes: `gmail.modify`, `gmail.send`, `gmail.labels`,
`openid`, `userinfo.email`, `userinfo.profile`. `calendar.events` was **absent**.
`build_consent_url` already passed `include_granted_scopes: "true"` (line 205 pre-change).
`apps/api/app/agents/scheduling_agent.py` documented and enforced "no calendar" throughout.

---

## 2. Tests first — RED before the fix

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wcal_google_calendar.py -q"
```

`[VERIFIED 2026-08-01T22:32:25Z]` — verbatim:

```
==================================== ERRORS ====================================
=================================== FAILURES ===================================
=========================== short test summary info ============================
FAILED tests/test_wcal_google_calendar.py::test_google_scopes_include_calendar_events
FAILED tests/test_wcal_google_calendar.py::test_consent_url_requests_calendar_with_incremental_authorization
FAILED tests/test_wcal_google_calendar.py::test_exchange_persists_scopes_google_actually_granted
FAILED tests/test_wcal_google_calendar.py::test_partial_grant_still_completes_so_the_gmail_connection_survives
FAILED tests/test_wcal_google_calendar.py::test_full_grant_records_calendar_scope
FAILED tests/test_wcal_google_calendar.py::test_relax_env_flag_is_not_left_set_after_exchange
FAILED tests/test_wcal_google_calendar.py::test_calendar_scope_granted_helper
FAILED tests/test_wcal_google_calendar.py::test_create_event_refuses_when_no_google_account
FAILED tests/test_wcal_google_calendar.py::test_scheduling_agent_reports_no_calendar_when_not_connected
FAILED tests/test_wcal_google_calendar.py::test_scheduling_agent_derives_windows_from_real_freebusy
FAILED tests/test_wcal_google_calendar.py::test_scheduling_result_reports_calendar_status_honestly
FAILED tests/test_wcal_google_calendar.py::test_settings_reports_calendar_scope_missing_truthfully
FAILED tests/test_wcal_google_calendar.py::test_settings_reports_needs_reauth_when_the_live_probe_fails_auth
ERROR tests/test_wcal_google_calendar.py::test_create_event_refuses_honestly_when_calendar_scope_absent
ERROR tests/test_wcal_google_calendar.py::test_event_payload_carries_title_company_time_and_job_link
ERROR tests/test_wcal_google_calendar.py::test_create_interview_writes_a_real_calendar_event
ERROR tests/test_wcal_google_calendar.py::test_create_interview_without_calendar_scope_is_honest_not_fabricated
ERROR tests/test_wcal_google_calendar.py::test_create_interview_without_google_account_reports_not_connected
ERROR tests/test_wcal_google_calendar.py::test_settings_reports_calendar_connected_when_a_live_probe_succeeds
13 failed, 2 passed, 6 warnings, 6 errors in 19.49s
```

**The 2 that passed at RED are deliberate and are not a defect.** They assert
*preserved* behaviour, so they must be green in both directions:
`test_existing_gmail_scopes_are_all_still_requested` (no Gmail scope may be dropped) and
`test_settings_has_no_calendar_row_without_a_google_account` (no calendar row is invented
for a user with no Google account).

### 2.1 Honest note — one RED was red for the wrong reason

Four token-exchange tests initially failed with
`'_FakeTokenResponse' object has no attribute 'request'`. That was a **defect in my own
test harness** (a hand-rolled stub response), not the production behaviour under test. It
was fixed by using a real `requests.Response` so oauthlib's genuine parsing path — the
thing the tests exist to pin — actually runs. Recording it because a "red" that is red for
the wrong reason is not evidence.

To close that gap properly, an adversarial self-check was run with `_relaxed_token_scope`
neutered, proving the relaxation is load-bearing rather than decorative:

`[VERIFIED 2026-08-01T22:43Z — temporary probe file, removed after the run]`

```
WITHOUT RELAX: Token exchange failed: Scope has changed from
"…/gmail.labels …/calendar.events …/gmail.modify openid …/userinfo.email …/userinfo.profile …/gmail.send"
to
"…/gmail.labels …/gmail.modify openid …/userinfo.email …/userinfo.profile …/gmail.send".
```

That is exactly the "user ticked Gmail, unticked Calendar" case — and without the fix the
whole exchange fails, so the user loses **Gmail**.

---

## 3. GREEN after the fix

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wcal_google_calendar.py -q"
```

`[VERIFIED 2026-08-01T22:50:04Z]` — verbatim:

```
21 passed, 10 warnings in 19.89s
```

Per-test (`-v`), `[VERIFIED 2026-08-01T22:47Z]`:

```
test_google_scopes_include_calendar_events PASSED
test_existing_gmail_scopes_are_all_still_requested PASSED
test_consent_url_requests_calendar_with_incremental_authorization PASSED
test_exchange_persists_scopes_google_actually_granted PASSED
test_partial_grant_still_completes_so_the_gmail_connection_survives PASSED
test_full_grant_records_calendar_scope PASSED
test_relax_env_flag_is_not_left_set_after_exchange PASSED
test_calendar_scope_granted_helper PASSED
test_create_event_refuses_when_no_google_account PASSED
test_create_event_refuses_honestly_when_calendar_scope_absent PASSED
test_event_payload_carries_title_company_time_and_job_link PASSED
test_create_interview_writes_a_real_calendar_event PASSED
test_create_interview_without_calendar_scope_is_honest_not_fabricated PASSED
test_create_interview_without_google_account_reports_not_connected PASSED
test_scheduling_agent_reports_no_calendar_when_not_connected PASSED
test_scheduling_agent_derives_windows_from_real_freebusy PASSED
test_scheduling_result_reports_calendar_status_honestly PASSED
test_settings_reports_calendar_scope_missing_truthfully PASSED
test_settings_reports_calendar_connected_when_a_live_probe_succeeds PASSED
test_settings_reports_needs_reauth_when_the_live_probe_fails_auth PASSED
test_settings_has_no_calendar_row_without_a_google_account PASSED
======================= 21 passed, 10 warnings in 21.24s =======================
```

### Frontend — red before, green after

`[VERIFIED 2026-08-01T22:52Z]` RED, with `settings-client.tsx` reverted to `HEAD` and
restored immediately afterwards (no `git stash` used):

```
× shows an unconnected Google Calendar as NOT connected
  → Unable to find an element by: [data-testid="account-status-scope_missing"]
× shows a revoked Google Calendar grant as needing reconnection
  → Unable to find an element by: [data-testid="account-status-needs_reauth"]
× does not fall back to green for an unrecognised status
  → Unable to find an element by: [data-testid="account-status-unavailable"]
 Test Files  1 failed (1)
      Tests  3 failed (3)
```

GREEN, together with the existing settings + interviews suites
`[VERIFIED 2026-08-01T22:47:09Z]`:

```
 ✓ src/app/dashboard/settings/__tests__/page.test.tsx (21 tests) 635ms
 ✓ src/app/dashboard/interviews/__tests__/page.test.tsx (8 tests) 230ms
 ✓ src/app/dashboard/settings/__tests__/notifications-jobboard.test.tsx (7 tests) 352ms
 ✓ src/app/dashboard/settings/__tests__/ML-settings-001.test.tsx (1 test) 120ms
 ✓ src/app/dashboard/settings/__tests__/W-CAL-calendar-status.test.tsx (3 tests) 159ms

 Test Files  5 passed (5)
      Tests  40 passed (40)
```

---

## 4. Regression suites — all green

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_google_oauth.py \
    tests/test_gmail_service.py tests/test_interviews.py tests/test_wave4c_thread_agents.py \
    tests/test_gm2_email_agents_findings.py -q"
```

`[VERIFIED 2026-08-01T22:37Z]`:

```
72 passed, 16 warnings in 105.94s (0:01:45)
```

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_agents_screen.py \
    tests/test_gap_p7_def_b_persist.py tests/test_wave4a_catalog_wiring.py \
    tests/test_ml_f1_f3_run_route_and_agent_list.py tests/test_wb1_ml_settings_006_nul_byte.py -q"
```

`[VERIFIED 2026-08-01T22:45Z]`:

```
76 passed, 1 skipped, 13 warnings in 156.13s (0:02:36)
```

### 4.1 HONEST NOTE — one RED appeared in a late run, and it was my fault, not a regression

A late consolidated run reported:

```
FAILED tests/test_ml_f1_f3_run_route_and_agent_list.py::test_no_run_route_leaves_a_guard_rejection_unhandled
1 failed, 139 passed, 1 skipped, 18 warnings in 246.98s (0:04:06)
```

`[VERIFIED 2026-08-01T22:59:42Z]` — recording it rather than quietly re-running until green.

**Root cause: I edited `app/routers/agents.py` at ~22:57 while that run (started 22:54:58)
was in flight.** That test is a pure source-inspection pin — it calls
`inspect.getsource(agents_router.run_named_agent)` with no DB and no fixtures. `inspect`
resolves the body through `linecache` against the code object's `co_firstlineno`, so a
file edited on disk after import shifts the line numbers and `getsource` returns a
mis-aligned slice. Nothing in the running code changed; the *reader* was pointed at the
wrong lines.

Evidence it is not a real regression, with files stable
`[VERIFIED 2026-08-01T23:03Z]`:

```
$ python3 -c "import inspect; from app.routers import agents as a; \
    src = inspect.getsource(a.run_named_agent); ..."
FabricationError in source: True
_guard_rejection_http_error in source: True
first line: @router.post("/{name}/run")
```

and the test in isolation:

```
tests/test_ml_f1_f3_run_route_and_agent_list.py::test_no_run_route_leaves_a_guard_rejection_unhandled PASSED [100%]
======================== 1 passed, 6 warnings in 0.63s =========================
```

The same file also passed inside the full batch twice earlier (22:45 and 22:52), before the
mid-run edit existed. A clean re-run of the identical batch with the files frozen is
recorded in §4.2. **Lesson recorded rather than hidden: never edit source while a pytest
batch is running — the failure it produces is indistinguishable at a glance from a real one.**

### 4.2 Clean re-run, files frozen

The identical batch, re-run with every source file frozen (md5sums recorded before and
after the run to prove no edit landed mid-flight) `[VERIFIED 2026-08-01T23:04:46Z]`:

```
$ md5sum apps/api/app/routers/agents.py apps/api/app/routers/interviews.py \
         apps/api/app/agents/scheduling_agent.py
d985120fa5240de62683ee4e518ae3c5  apps/api/app/routers/agents.py
5687291bcb4992a4886ca5a8d958369b  apps/api/app/routers/interviews.py
6e2295a9897f336c378b942cf9a61794  apps/api/app/agents/scheduling_agent.py

$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wcal_google_calendar.py \
    tests/test_agents_screen.py tests/test_gap_p7_def_b_persist.py tests/test_wave4a_catalog_wiring.py \
    tests/test_ml_f1_f3_run_route_and_agent_list.py tests/test_wb1_ml_settings_006_nul_byte.py \
    tests/test_google_oauth.py tests/test_gmail_service.py tests/test_interviews.py \
    tests/test_wave4c_thread_agents.py tests/test_gm2_email_agents_findings.py -q"

170 passed, 1 skipped, 27 warnings in 255.54s (0:04:15)
```

Zero failures. `test_no_run_route_leaves_a_guard_rejection_unhandled` is green here.

### 4.3 Post-review self-correction (found by me, fixed with a test)

Re-reading my own diff, `calendarIntegration` was documented as "True only when this run
genuinely read the user's calendar" but was set `True` on the branch where the caller
supplies their own windows — a branch that never touches the calendar. Small, but it is
exactly the kind of claim-without-a-read this codebase forbids. It now stays `False` there
(with `calendarStatus == "connected"` conveying that the integration is available), pinned
by `test_caller_supplied_windows_do_not_claim_a_calendar_read`, which also asserts
`freebusy_queries == []`.

Final green after that change `[VERIFIED 2026-08-01T23:08Z]`:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wcal_google_calendar.py \
    tests/test_wave4c_thread_agents.py -q"
48 passed, 10 warnings in 80.71s (0:01:20)
```

**No existing test was modified, weakened or deleted.** In particular
`test_scheduling_copy_makes_no_calendar_claim` (which requires the Scheduling Agent card
to state that Aether reads no calendar) still passes **unmodified**: the new card copy
states both branches — "With Google Calendar connected it proposes windows your real
free/busy shows as free; without it Aether **reads no calendar** for you…" — so the
assertion holds and the copy became *more* accurate rather than less.

---

## 5. Lint

```
$ python3 -m ruff check app/services/calendar_service.py app/services/google_oauth.py \
    app/routers/interviews.py app/agents/scheduling_agent.py app/routers/agents.py \
    app/routers/workspaces.py tests/test_wcal_google_calendar.py
All checks passed!
```

`[VERIFIED 2026-08-01T22:36Z, ruff 0.15.21]` — every file W-CAL touched is clean.

```
$ python3 -m mypy app/
Success: no issues found in 119 source files
```
`[VERIFIED 2026-08-01T22:56Z]`

```
$ npx next lint --dir src
✔ No ESLint warnings or errors

$ npx tsc --noEmit -p tsconfig.json   # exit 0
```
`[VERIFIED 2026-08-01T22:54Z]`

### HONEST EXCEPTION — `ruff check app/ tests/` is NOT clean, and was not clean before W-CAL

```
$ python3 -m ruff check app/ tests/
E501 Line too long (105 > 100)  --> app/repositories/job.py:305:101
I001 Import block is un-sorted   --> tests/test_ats_semantic_path_propagation.py:34:1
Found 2 errors.
```

`[VERIFIED 2026-08-01T22:35Z]` Both are **pre-existing on HEAD** in files W-CAL never
touched. Proof: `git status --short apps/api/app/repositories/job.py
apps/api/tests/test_ats_semantic_path_propagation.py` returns **empty** — both files are
byte-identical to commit `2ecbdb0`, so the errors exist at HEAD independently of this work.

I deliberately did **not** fix them: they are outside W-CAL's scope, and
`app/repositories/job.py` sits adjacent to the concurrent session's active job/story work.
Flagging it rather than silently absorbing it, and rather than reporting "ruff clean" when
the literal command in the brief does not pass.

#### RESOLVED after W-CAL was committed — and the attribution held up

The concurrent session fixed both in `c9e45d6` ("style: restore ruff-clean — 2 CI-blocking
errors, one of them mine"), touching only `app/repositories/job.py` and
`tests/test_ats_semantic_path_propagation.py` — neither a W-CAL file.

Because that commit message attributes one error to an author, I re-checked my own
attribution rather than let it stand unexamined `[VERIFIED 2026-08-01T23:15Z]`:

```
$ git log -L 305,305:apps/api/app/repositories/job.py
c9e45d6 style: restore ruff-clean …                    <- the fix
0ed302a fix(BLOCKER-006): job feed hid every live listing …   <- the origin
```

The E501 was introduced by `0ed302a` (BLOCKER-006), **two commits before W-CAL's starting
HEAD `2ecbdb0`**. So "pre-existing, not W-CAL's" is confirmed by provenance, not just by a
clean `git status`. The other session's "one of them mine" refers to their own BLOCKER-006
commit — which agrees with this finding rather than contradicting it.

Current state `[VERIFIED 2026-08-01T23:15Z]`:

```
$ python3 -m ruff check app/ tests/
All checks passed!
```

`ruff check app/ tests/` is now **clean on HEAD**, so the CI gate is unblocked. W-CAL's own
files were clean throughout.

**Does `c9e45d6` invalidate W-CAL's green?** No — W-CAL's suites were measured at `b85914c`
and HEAD moved, so I checked rather than assumed. The entire commit is cosmetic
`[VERIFIED 2026-08-01T23:16Z]`:

```
- from app.services.ats_engine import ATSScore, _DEGRADED_SEMANTIC_SCORE
+ from app.services.ats_engine import _DEGRADED_SEMANTIC_SCORE, ATSScore

- VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
+ VALUES (
+     %s, %s, %s, %s, %s, %s, %s, %s,
+     %s, %s, %s, %s, %s, %s, %s, %s,
+     NOW(), NOW()
+ )
```

An import reorder, and a SQL `VALUES` clause wrapped across lines with the **identical 16
placeholders in the identical order** (SQL is whitespace-insensitive). Neither file is
imported or exercised by any W-CAL test.

Confirmed empirically, not just by construction — re-run on HEAD `ce489b4` (which contains
`c9e45d6`) `[VERIFIED 2026-08-01T23:26Z]`:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wcal_google_calendar.py \
    tests/test_interviews.py tests/test_google_oauth.py tests/test_wave4c_thread_agents.py -q"
66 passed, 11 warnings in 93.17s (0:01:33)
```

Zero failures. W-CAL's green holds on the post-`c9e45d6` tree.

---

## 6. What shipped

### 6.1 Scope + incremental authorization

`apps/api/app/services/google_oauth.py`

- `CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"` added to
  `GOOGLE_SCOPES`. All six pre-existing scopes retained (pinned by a test).
- `include_granted_scopes: "true"` was **already present and is preserved unchanged**. Its
  docstring now records it as a do-not-remove invariant with the reason.

### 6.2 How existing Gmail grants are preserved — the three mechanisms

1. **Incremental authorization** (`include_granted_scopes=true`). Adding a scope does not
   retroactively grant it, and *without* this flag Google issues a token carrying only the
   newly-consented scopes — which would silently break email sync for every existing user
   at their next reconnect. With it, Google adds `calendar.events` to the account's
   existing authorization and returns a token covering Gmail **and** Calendar.
2. **The partial-grant survival path.** Google's granular consent lets a user tick Gmail
   and untick Calendar. oauthlib **raises** when the granted scope set differs from the
   requested set, so without intervention that user's token exchange would fail outright
   and take their Gmail connection down with it (proven verbatim in §2.1).
   `_relaxed_token_scope()` — a lock-serialized context manager that sets
   `OAUTHLIB_RELAX_TOKEN_SCOPE`, wraps `flow.fetch_token` only, and restores the previous
   value in a `finally` — lets that exchange complete. A test asserts the flag does not
   leak past the exchange.
3. **Granted-scope truth.** `exchange_code` now persists `granted_scope_string(creds)`,
   which prefers `credentials.granted_scopes` (parsed from Google's own token response)
   over `credentials.scopes` (what we *asked* for). Without this, adding the scope would
   have recorded a Calendar grant for every user including those who declined it —
   a fabricated capability the whole product would then have repeated.

An account that consented to Gmail but **not** Calendar therefore keeps working for email
and gets an honest, actionable "not connected" everywhere calendar is surfaced. That exact
scenario is pinned by `test_create_interview_without_calendar_scope_is_honest_not_fabricated`
and `test_settings_reports_calendar_scope_missing_truthfully`.

### 6.3 Real interview events

`apps/api/app/services/calendar_service.py` (new) + `apps/api/app/routers/interviews.py`

- `POST /interviews` creates the row, then attempts a real
  `events().insert(calendarId="primary", …)`, then reports the outcome.
- Event payload: `summary` = `Interview — {role} @ {company}` (degrading to the interview
  type rather than inventing a role/company), `description` carrying company, role,
  contact, meeting link and **the job link**, `location`, and RFC-3339 `start`/`end`
  derived from `scheduled_at` + `duration_minutes`.
- Additive lazy DDL (ADR-TR-1) adds `calendarEventId`, `calendarHtmlLink`,
  `calendarSyncStatus`, `calendarSyncedAt` via `ADD COLUMN IF NOT EXISTS` under advisory
  lock `7420240719`. No DROP, no rename, no type change.
- `status: "created"` is emitted **only** when Google returned a real event id. A response
  without an id is reported as `failed`, never as success.

### 6.4 The honest-refusal copy shipped

Verbatim, from `apps/api/app/services/calendar_service.py`:

| status | copy |
|---|---|
| `not_connected` | "Google Calendar is not connected — connect your Google account from Settings to have interviews written to your calendar. Nothing was added to any calendar." |
| `scope_missing` | "Google Calendar access was not granted for this account — Gmail still works, but no calendar event was created. Reconnect your Google account from Settings and tick the calendar permission to enable this." |
| `needs_reauth` | "Google Calendar authorization expired or was revoked, so no calendar event was created. Reconnect your Google account from Settings and tick the calendar permission to enable this." |
| `failed` (no id returned) | "Google Calendar accepted the request but returned no event id, so the event could not be confirmed. Check your calendar before relying on it." |
| `unavailable` (status check only) | "Google Calendar could not be reached just now, so its connection could not be verified: {error}" |

The Interview Center renders this verbatim in a banner
(`data-testid="interview-calendar-notice-{status}"`) that is **amber for every non-created
status** and green only for `created`, where it also links to Google's own `htmlLink`.
There is no code path that produces a success toast without an event id.

### 6.5 Free/busy in the Scheduling Agent

`apps/api/app/agents/scheduling_agent.py`

Availability precedence, with no fourth branch:

1. windows the **caller** supplied → used verbatim (a human overrules the calendar);
2. else, when Calendar is genuinely connected → up to 3 windows from real
   `freebusy().query()`, business hours, weekdays, next 14 days, each verified not to
   overlap a busy block, in the calendar's **own** timezone (read from
   `calendars.get('primary')`, not guessed);
3. else → today's pre-W-CAL behaviour verbatim: propose nothing, ask the sender, and say
   why.

New reported fields: `calendarStatus`, `calendarMessage`, `calendarProposedTimes`,
`freeBusyChecked`. `calendarIntegration` is no longer hardcoded `False` — it is `True`
only when the run really read the calendar.

Each failure mode on the live free/busy call is reported as **itself**, not collapsed:
a revoked token gives `needs_reauth` (with "reconnect"), a narrowed grant gives
`scope_missing`, and only genuine transport trouble gives `unavailable`. Collapsing the
first into the last would leave the user with no action to take; pinned by
`test_scheduling_agent_reports_a_revoked_grant_as_needing_reauth`.

**The fabrication rail is not weakened.** `unsupported_time_expressions` is untouched.
Calendar-derived windows join the *evidence corpus* exactly as the caller's own windows
do, because they are read facts, not model output. To stop the rail false-positiving on
formatting, each label carries several renderings of the same real fact:
`Tuesday 5 August, morning — 10:00 AM to 11:00 AM (10am to 11am), Australia/Sydney`.
`test_invented_availability_is_withheld` and
`test_a_time_the_sender_proposed_is_not_treated_as_invented` both still pass unmodified.

### 6.6 Truthful settings status (mirrors GM2-EMAIL-001)

- Backend (`workspaces.py` `GET /workspaces/settings`): adds a `Google Calendar` row —
  **only** for a user who has a Google account at all — whose status comes from
  `connection_status()`. No network call when there is no account or when the stored
  *granted* scopes already settle it; otherwise one live
  `calendarList.list(maxResults=1)` decides `connected` / `needs_reauth` / `unavailable`.
  `unavailable` exists so "could not check" is never rounded up to "connected". The call
  is exception-guarded so settings can never 500 on it.
- Frontend (`settings-client.tsx`): **the badge was a hardcoded green "Connected" for
  every row.** It now renders the real status, and an unrecognised status falls through to
  neutral "Unverified" styling rather than to green. This was a latent lie waiting for the
  first non-connected row; Calendar is that row.

---

## 7. Files changed

**New**
- `apps/api/app/services/calendar_service.py`
- `apps/api/tests/test_wcal_google_calendar.py` (23 tests)
- `apps/web/src/app/dashboard/settings/__tests__/W-CAL-calendar-status.test.tsx` (3 tests)
- `docs/delivery/ADR-CALENDAR-V4.md`
- `uat/reports/evidence/gold-master-v3/W-CAL-implementation.md` (this file)

**Modified**
- `apps/api/app/services/google_oauth.py` — scope, incremental-auth docs, relax context
  manager, granted-scope persistence
- `apps/api/app/routers/interviews.py` — additive DDL, calendar write, honest reporting
- `apps/api/app/agents/scheduling_agent.py` — free/busy, calendar status fields, copy
- `apps/api/app/routers/agents.py` — Scheduling Agent card copy (both branches)
- `apps/api/app/routers/workspaces.py` — truthful Google Calendar settings row
- `apps/web/src/lib/api/interviews.ts` — calendar result + linkage schema
- `apps/web/src/app/dashboard/interviews/page.tsx` — honest calendar banner
- `apps/web/src/app/dashboard/settings/settings-client.tsx` — real status badge

---

## 8. Files declined due to the concurrent session

A concurrent session held uncommitted production changes in this working tree. Every file
was `git status --short`-checked before editing. **Not touched, not staged, not committed:**

- `apps/api/app/db.py`
- `apps/api/app/repositories/story.py`
- `apps/api/app/routers/jobs.py`
- `apps/api/app/services/story_dedup_migration.py`
- `apps/api/app/services/story_paraphrase.py`
- `apps/api/scripts/story_dedup_sweep.py` (untracked, theirs)
- `apps/web/src/app/dashboard/jobs/page.tsx`
- `apps/web/src/app/dashboard/resume/page.tsx`
- `apps/web/src/lib/api/resumes.ts`
- `apps/web/src/__tests__/dashboard/resume-conversion-tooltip.test.tsx`
- `apps/web/src/__tests__/dashboard/resume-tailor-score-warning.test.tsx`
- `apps/web/src/app/dashboard/jobs/__tests__/tailor-score-refresh.test.tsx`
- `apps/web/src/app/dashboard/resume/__tests__/conversion-banner.test.tsx`
- `apps/web/src/app/dashboard/resume/__tests__/degraded-scoring.test.tsx`
- `uat/reports/evidence/gold-master-v2/runtime/monitor-errors-CORRECTED.log`

**Appeared mid-run** (the concurrent session's footprint grew while W-CAL was in progress);
also declined, and confirmed as theirs by inspecting the diff (`GMV4-email-001`):

- `apps/web/src/lib/api/workspaces.ts`
- `apps/web/src/app/dashboard/email/page.tsx`
- `apps/web/src/app/dashboard/analytics/__tests__/interview-conversion-rate.test.tsx` (deleted by them)

`git stash` was never used. Only W-CAL's own files were staged.

---

## 9. Residual risks

1. **Every existing user must reconnect Google once.** Until they do, `calendar.events` is
   not in their granted scopes and all calendar surfaces report `scope_missing`. Gmail is
   unaffected. This is unavoidable for any scope addition and is why the refusal copy is
   actionable rather than generic — but it is a real migration cost and users should be
   told, not left to discover it. **No in-product prompt to reconnect exists yet**; the
   only signal is the Settings badge and the per-interview banner.
2. **Google Cloud console consent screen must list `calendar.events`.** Code alone is not
   sufficient: if the OAuth client's configured scopes do not include it, Google will
   refuse the consent request at runtime. **This is an operator action, unverified by this
   agent** — I have no console access and did not deploy.
3. **No production verification.** Nothing was deployed and no live Google API call was
   made. All evidence here is local test evidence. Live behaviour against real Google
   consent (especially granular consent ordering) remains unproven in production.
4. **`ruff check app/ tests/` fails on two pre-existing errors** in files W-CAL did not
   touch (§5). CI gates on ruff before tests, so this blocks the pipeline for reasons
   unrelated to W-CAL and needs an owner.
5. **Settings adds one Google API round-trip** for users whose stored grant includes
   `calendar.events`. Bounded to one call and fully exception-guarded, but it is new
   latency on a page that previously made none. If it proves slow, the correct fix is
   caching the probe result with a short TTL — *not* dropping the probe, which would
   reintroduce GM2-EMAIL-001.
6. **Rescheduling does not update the calendar event.** `PATCH /interviews` changes
   `scheduledAt` in the database but does not call `events().patch()`, so a rescheduled
   interview leaves a stale event on the calendar. Deliberately out of scope for §10
   (which specifies creation), but it is a genuine divergence a user will hit and should
   be the next W-CAL increment. Likewise `DELETE`/cancel does not remove the event.
7. **`OAUTHLIB_RELAX_TOKEN_SCOPE` is briefly process-global** during a token exchange.
   Lock-serialized and restored in a `finally`; worst case on overlap is that a concurrent
   exchange is also relaxed, which is the desired behaviour. Noted for completeness.
8. **Free/busy reads only the `primary` calendar.** A user whose interviews live on a
   secondary calendar will see availability that ignores it. Honest (it never claims
   otherwise) but incomplete.
9. **Multi-account nuance**: with two Google accounts linked, the service prefers whichever
   one actually granted `calendar.events`. If both did, it uses the first. There is no UI
   to choose which calendar receives interview events.
10. **Free/busy reads the `primary` calendar only**, in that calendar's own timezone. A
    business-hours slot generated across a DST transition resolves via Python's default
    `fold` rules rather than an explicit policy. Low impact (the label always states the
    timezone) but not explicitly handled.
11. **Historical docs still carry the pre-W-CAL "no calendar" claim**:
    `docs/delivery/GOLD-MASTER-V3-FEATURE-COMPLETENESS-MATRIX.md`,
    `AGENTS-IMPLEMENTATION-MATRIX-2026-07-29.md`, `GOLD-MASTER-V3-ADVERSARIAL-REVIEW.md`
    and `GMV2-CLAIM-LEDGER.md`. Those are records of prior runs, so I did not rewrite them
    (that is doc-updater's call, and editing another run's ledger is not mine to make) —
    but they now describe superseded behaviour and should be reconciled against
    `ADR-CALENDAR-V4`.

---

## 10. Self-assessment — what I did NOT verify

- I did **not** verify against the live Google API. Every Google call in these tests is
  mocked at the client boundary (`GoogleCalendarService._client`) or the HTTP boundary
  (`requests.Session.request`), per the brief.
- I did **not** deploy, and did **not** push.
- I did **not** verify the Google Cloud console consent-screen configuration.
- I did **not** run the full pytest suite (the brief forbids it); only the files W-CAL
  touches plus the named regression suites.
- I have **not** approved this work. It requires independent review.
