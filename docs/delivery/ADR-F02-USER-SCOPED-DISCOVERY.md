# ADR-F02 — User-scoped job discovery

**Status:** Implemented (frontend + backend). The §6 residual was ruled and closed — see §8.
**Date:** 2026-08-04
**Finding:** F-02 (MAJOR) — `docs/delivery/PROD-UAT-2026-08-03.md`
**Scope:** `/dashboard/jobs` "Sync Now", `/dashboard/agents` Scout "Run", results labelling

---

## 1. The defect

`apps/web/src/app/dashboard/jobs/page.tsx:616` posted a literal body for **every** user:

```ts
body: { query: "delivery lead, product owner, program manager, business analyst",
        location: "Australia" }
```

It never read the signed-in user's target role, location, or résumé. A NEW-FREE persona with a
Senior *Data Scientist* résumé and `targetRole: ""` received 1,621 project-management postings —
none scored, none filtered — under a heading that called them "matches".

Two independent failures, both of the same kind:

1. **A search that is not the customer's.** The headline feature of a job-search product ran
   somebody else's query.
2. **A label the system could not justify.** `stats.matches = all.length` counted every discovered
   row as a "match" regardless of whether anything had been scored against the user's résumé. The
   product's core promise is that it does not fabricate; asserting relevance it never measured is
   that failure in miniature.

## 2. What the query is derived from

Enumerated **before** designing (nothing new was invented; every source below already existed):

| Source | Where | Verdict |
|---|---|---|
| `targetRole`, `location` | `GET /auth/me` → `apps/api/app/routers/auth.py:176-199` | **Used.** The user's own profile columns, the same ones Settings > Profile writes and the topbar chip renders. |
| Résumé text | `ScoutAgent.run` → `require_user_resume_text` + `ATSEngine` (`apps/api/app/agents/scout_agent.py:98-119`) | **Already consumed server-side.** Every discovered posting is qualified against the user's real résumé there. Re-deriving a role from résumé prose in the browser would be a second, weaker guess at something the server already knows — so the frontend deliberately does not parse résumés. |
| Role-family broadening | `app/services/discovery/query_builder.build_scout_query` | **Left server-side.** A recognised role is broadened to its family by the same module that owns the matching regex, so the query and the filter can never disagree. The frontend sends the user's own wording, unwidened. |
| `_user_search_defaults` | `apps/api/app/routers/agents.py:1676-1705` | **Already existed and was unreachable from the UI** — `ScoutRunRequest` requires `query`/`location` (`min_length=1`), so a frontend-supplied value always won. This is why the hardcode existed at all. |

Derivation now lives in one place: **`apps/web/src/lib/discovery/search-target.ts`**.

Its defining property is that **it owns no query of its own**. There is no constant in the module to
fall back to, so "the user told us nothing" can only resolve to `needs-input` — a question — never to
a search. Reintroducing a default requires adding the literal to that file, where
`search-target.test.ts` asserts against exactly that.

`fetchMe` (`apps/web/src/lib/api/admin.ts`) — already the app's canonical `/auth/me` client, used by
the topbar and the AdminGuard — now also parses `targetRole` and `location`. Additive and
backward-compatible (`.optional().default("")`); the API has always returned both fields, the client
simply discarded them.

## 3. The empty-profile decision

**Decision: ask the user. Never substitute, never run.**

When the profile carries no target role and/or no location, "Sync Now" opens an inline prompt
(`data-testid="discovery-target-prompt"`) that states plainly that nothing is configured, asks for a
role and a location, and links to Settings for a permanent answer. No request is issued until the
user supplies both. A half-filled prompt is refused with a message naming the missing half, not
completed with a guess.

A failed `/auth/me` lookup resolves to the **same** path — `deriveSearchTarget(null)` is
`needs-input`. Not knowing what the customer wants and guessing wrong are the same outcome for them,
so an infrastructure failure must not silently become a fabricated search.

Rejected alternatives:

- *Fall back to the role family (`ROLE_FAMILY_QUERY`).* This is precisely the defect — it is how a
  data scientist got project-management postings. It is also what the backend still does; see §6.
- *Fall back to a résumé-derived guess.* Better than a constant, but still an assertion the user
  never made, and it would duplicate server-side logic in a weaker form.
- *Disable "Sync Now" until Settings is filled in.* Honest but hostile: a new user's first click
  would do nothing with no route forward. The prompt keeps them moving while keeping the search
  theirs. (Settings' own "Sync All" already uses the disable-with-tooltip variant —
  `settings-client.tsx:405` — which is why that call site was never defective.)

Additionally, whenever the target *is* known the screen states it outright
(`data-testid="discovery-search-target"`): *"Sync Now searches for **X** in **Y** — from your
profile."* So the second option in the finding's remit ("state plainly what is being searched and
why") is satisfied in the normal case too, not only the empty one.

## 4. The labelling change

`stats.matches = all.length` → three separately-counted populations:

```
{total} discovered · {scored} scored against your résumé · {unscored} not yet scored
  · {newToday} new today · {sources} sources connected
```

A "match" claim requires a fit score behind it. The scored/unscored split uses `fitScore != null` —
the same test `apps/web/src/app/dashboard/page.tsx:194` already treats as "scored" — so the Jobs
screen now agrees with the dashboard, the "not measured" vocabulary in Resume Studio and the Cover
Letter quality panel, and the withheld-score handling already present on this page.

## 5. Other instances of the same hardcode

Item 4 of the remit. Findings, in order of severity:

| # | Site | Literal | Status |
|---|---|---|---|
| 1 | `apps/web/src/app/dashboard/jobs/page.tsx:616` | `"delivery lead, product owner, program manager, business analyst"` / `"Australia"` | **Fixed.** |
| 2 | `apps/web/src/app/dashboard/agents/page.tsx:83` (`RUN_PARAMS.scout`) | `"software engineer"` / `"Australia"` | **Fixed.** A *second, different* persona sent for every customer pressing Run on the Scout card. Fixing only the line the UAT happened to click would have left the product still searching for the wrong job. |
| 3 | `apps/api/app/routers/agents.py:2703-2704` (`PipelineRunRequest`) | `_DEFAULT_QUERY` (= `ROLE_FAMILY_QUERY`) / `"Melbourne, Australia"` | **Fixed — see §8.** |
| 4 | `apps/api/app/routers/agents.py:89-90` + `query_builder.ROLE_FAMILY_QUERY` | the 10-term PM/BA family / `"Melbourne, Australia"` | **Fixed — see §8.** Both constants deleted. |
| 5 | `scripts/discovery_cron.sh:105-106` | `"Senior Technical Program Manager"` / `"Melbourne, AU"` | **NOT fixed.** Reads `/auth/me` first and only falls back if the operator's own account has no target role. Single-account operator tooling, lower blast radius, but it is the same pattern. Verified unreached in production — §8.4. |
| — | `apps/web/src/app/dashboard/settings/settings-client.tsx:426` | none | **Already correct.** Sends `profile.targetRole` / `profile.location` and gates the button on both being non-empty with an honest tooltip (`:405`). Precedent for the design above. |

## 6. Residual escalated for an orchestrator ruling

> **RESOLVED 2026-08-04** — ruled reading **(a)**, implemented and verified in §8. This section is
> kept verbatim as the record of the escalation and of what was known at the time.

**The Agents console's "Run All" (pipeline) is still a live route to the original defect.**

`runPipeline()` posts `body: {}` (`apps/web/src/lib/api/agents.ts:128-135`). `PipelineRunRequest`
materialises its pydantic defaults, so `_pipeline_core` calls
`_dispatch(user_id, "scout", {"query": ROLE_FAMILY_QUERY, "location": "Melbourne, Australia"})`.
Because `params.get("query")` is then truthy, `_user_search_defaults` — the profile-derived helper
that already exists — is **never consulted**. Every user's "Run All" therefore scouts the hardcoded
PM/BA family in Melbourne, exactly as "Sync Now" used to.

Not fixed unilaterally, for two stated reasons:

- The hardcode is a **backend default**, not a frontend body. Patching only the frontend would paper
  over a default that the async worker enqueue path and any other API consumer still hit.
- `apps/api/app/routers/agents.py` carries another session's uncommitted work, and `_DEFAULT_QUERY` /
  `_user_search_defaults` also feed the discovery cron. Changing shared dispatch-default semantics is
  orchestrator territory under this run's standing rules.

Two defensible readings, both recorded:

- **(a) Same defect, fix it.** "Run All" is user-facing and pollutes the same `Job` table with the
  same junk rows. Recommended shape: make `PipelineRunRequest.query`/`.location` `None`-defaulted so
  `_user_search_defaults` runs, **and** decide what an empty profile should do there (today it would
  reach `ROLE_FAMILY_QUERY` and re-fabricate — the honest answer is a 422 naming the missing profile
  field, mirroring the frontend prompt).
- **(b) Out of scope for F-02.** The finding named the "Sync Now" call site; "Run All" is a separate
  feature whose refusal behaviour is a product decision.

Consequence of leaving it: the junk-row source is narrowed, not closed. A user pressing "Run All"
still gets unfiltered PM postings written to their account.

**Related, same ruling:** `_user_search_defaults` falls back to `ROLE_FAMILY_QUERY` for any user with
an empty `targetRole`. The frontend can no longer reach that path, but nothing else stops it. The
frontend and backend now disagree about what "no target role" means — the frontend asks, the backend
substitutes.

## 7. Tests

Fail-before / pass-after evidence: `uat/reports/evidence/models-live/F-02/`.

| Test | Proves |
|---|---|
| `apps/web/src/lib/discovery/__tests__/search-target.test.ts` (10) | Derivation is the user's own; two users differ; **every** empty-profile shape resolves to `needs-input` — the exhaustive case is the guard against a "sensible default" returning. |
| `apps/web/src/app/dashboard/jobs/__tests__/f02-user-scoped-discovery.test.tsx` (11) | Body derived from *this* user; the delivery-lead persona is never sent; two users produce two searches; empty profile issues **no** request and asks instead; a half-filled prompt does not run; a failed profile lookup asks rather than guesses; scored/unscored counted separately and never called "matches". |
| `apps/web/src/app/dashboard/agents/__tests__/f02-scout-run-params.test.tsx` (2) | Scout's Run uses the profile, not `"software engineer"`; an empty profile is refused honestly with a Settings CTA and `runAgent` is never called. |

23 targeted tests: **13 failed before / 23 pass after** (the 10 derivation tests could not collect
before — the module did not exist). Full web suite after: **117 files, 813 tests, 0 failures**.
`pnpm --dir apps/web lint` and `type-check` both clean. No backend files were changed, so no `ruff`
or `pytest` run was required.

## 8. Backend half — closed (orchestrator ruling, 2026-08-04)

The §6 residual was ruled **reading (a): same defect, fix it.** Implemented in the commit
`fix(F-02): derive backend discovery from the caller's profile or refuse`.

### 8.1 Every affected model and route

Enumerated by grepping every `BaseModel` in `apps/api/app/routers/` for a `query`/`location` field
and every caller of the scout dispatch seam. Exactly two request models carry discovery targets
(`interviews.py:184` is an interview venue, `workspaces.py:800` a profile column — neither is a search):

| # | Model / seam | Was | Now |
|---|---|---|---|
| 1 | `PipelineRunRequest` — `POST /agents/pipeline/run` ("Run All"), **sync AND async ARQ enqueue** | `query = _DEFAULT_QUERY`, `location = _DEFAULT_LOCATION` | `str \| None = Field(default=None, min_length=1)` |
| 2 | `ScoutRunRequest` — `POST /agents/scout/run` (Jobs "Sync Now", Settings "Sync All", the Scout card, `discovery_cron.sh`) | `Field(min_length=1)`, required | `str \| None = Field(default=None, min_length=1)` |
| 3 | `_agent_callable` / `_dispatch` — the seam the async worker (`workers.tasks._run_single_agent_body`, `_pipeline_core`) resolves scout through | `params.get("query") or _DEFAULT_QUERY` | `_resolve_scout_target(user_id, params)` |
| 4 | `_user_search_defaults` | fell back to the same two literals | returns `("", "")` — substitutes nothing |
| — | `_DEFAULT_QUERY` / `_DEFAULT_LOCATION` | module constants | **deleted** |

Two paths that could have reached the seam and do not: `POST /agents/{name}/run` cannot carry scout
(the dedicated `/agents/scout/run` route is declared first and always wins the match), and
`workers/board_sweep.py` dispatches only `tailor` and `coverLetter`.

An explicitly supplied value still wins everywhere, and an explicitly supplied *empty* one is still a
pydantic 422 — `min_length=1` applies to the non-`None` branch of the union (verified against
pydantic 2.13.4, the installed version).

### 8.2 Empty profile: refuse, and say what is missing

`POST /agents/scout/run` and `POST /agents/pipeline/run` return **422** with a detail naming the
missing profile field(s):

> Your profile has no target role and no location, so there is nothing to search for. Add them in
> Settings > Profile, or supply an explicit query and location with the run.

Resolved in `run_pipeline` and `run_scout` **before** anything is enqueued or recorded — so the async
path refuses at request time instead of failing a background job the user would discover much later —
and again (cheaply, with no second DB read) in `_agent_callable` **before** `_record_run`, so a
refused run reserves no quota, bills nothing and leaves no audit row (asserted), and so a non-HTTP
caller cannot walk around the guard.

Resolving at the route also makes the audit trail honest: `AgentRun.input` now records the search
that actually ran — the user's own profile values — instead of the two nulls the caller sent (and,
before this change, instead of the hardcoded persona, which was worse: an audit trail that agreed
with the fabrication).

`detail` is a plain **string**, not the structured object `_plan_quota_429` uses. The Agents console
renders a backend 422 through `agents-feedback.runErrorNotice`, whose `extractApiJsonDetail` surfaces
only a string detail; an object would fall through to that branch's hardcoded *"run Scout to discover
jobs"* copy — which for this refusal is both wrong and misdirecting, since running Scout is refused
for the same reason. Honest copy today beat a machine-readable shape no frontend reads yet; a
structured detail is worth introducing only together with the frontend change that consumes it.

### 8.3 `build_scout_query(None)` — made honest

**Ruling: raise `ValueError`.** No caller legitimately needs a role-family broadening for a role
nobody has. The only production caller is `_agent_callable`, and it now resolves the target (or
refuses) first, so an empty role reaching the builder is a programming error, not a user state. The
legitimate half of the module — broadening a role the user *does* have, GAP-SRC-001 — is untouched
and still asserted, including on the cron's real live query.

`ROLE_FAMILY_QUERY` remains as the joined form of `ROLE_FAMILY_TERMS` (it is what a fully-broadened
query looks like, and `test_gap6_sourcing_volume` uses it as an already-broad input), but it is no
longer anybody's fallback.

`test_gap6_sourcing_volume.py::TestBuildScoutQuery`'s two "no target role -> full role family" tests
were **superseded**, not deleted: they now assert the refusal, with the reason recorded in-place.

### 8.4 The discovery cron: verified, not assumed

`scripts/discovery_cron.sh:90-92` reads `/auth/me` and posts an **explicit** query + location, so it
never reaches the profile-derived path — and `_resolve_scout_target` does not even open a DB
connection when both are supplied.

Verified three ways, not assumed:

1. **Live log** (`/var/log/aether/discovery.log`, captured 2026-08-04T03:54Z, filed at
   `uat/reports/evidence/models-live/F-02/cron-live-evidence.log`): eight consecutive 30-minute
   cycles send `query='Business Analyst/Project Manager/Scrum Master' location='Melbourne'`. That is
   the operator's own `targetRole`, **not** the script's fallback literal
   (`"Senior Technical Program Manager"`), so the profile read is working and the empty-profile
   branch is not in play. Latest cycle at the time of the change: scout 03:30 → fit-scorer 03:38,
   `{"status":"completed","scored":8,"errors":[]}`.
2. **Static read**: both cron values pass through `... or "<literal>"`, so neither can ever be empty
   — there is no code path from that script to the `None` path.
3. **Tests**: `TestDiscoveryCronPathStillWorks` replays the exact sequence (login → `/auth/me` →
   `POST /agents/scout/run` with the values it read), for an operator *with* a profile and for one
   relying on the script's own fallback. Both 202, both before and after the change.

The cron was **not** modified: nothing in it breaks. Its own hardcoded fallback (§5 row 5) is
unreached today and remains an open, lower-severity residual.

### 8.5 Tests

`apps/api/tests/test_f02_backend_user_scoped_discovery.py` (14). Fail-before/pass-after logs:
`uat/reports/evidence/models-live/F-02/`.

| Test | Proves |
|---|---|
| `..._empty_body_scouts_the_users_own_role_not_the_hardcoded_persona` | "Run All" with `{}` reaches `ScoutAgent` with THIS user's role and location. The 10 persona terms are asserted absent **by name**. |
| `..._two_users_get_two_different_searches` | Two users, two searches — derivation is per-caller, not global. |
| `..._empty_profile_is_refused_by_name_not_substituted` | 422 whose detail names both missing fields and where to fix them; the scout never ran. |
| `..._a_refused_pipeline_records_and_bills_nothing` | The refusal precedes `_record_run`: no `AgentRun` row, no quota reserve. |
| `..._half_a_profile_is_refused_naming_only_the_missing_half` | Names only what is actually missing. |
| `..._omitted_query_and_location_fall_back_to_the_users_profile` | `/agents/scout/run` with `{}` → 202 on the user's own target. |
| `..._the_audit_row_records_the_search_that_actually_ran` | `AgentRun.input` carries the resolved search, not the nulls the caller sent. |
| `..._empty_profile_is_refused_by_name` | The same refusal on the scout route. |
| `..._the_shared_dispatch_seam_refuses_too` | `_dispatch` — the async worker's own seam — refuses too, so the guard cannot be walked around by a non-HTTP caller. |
| `..._cron_sequence_with_a_configured_operator_profile` | The cron's exact sequence still 202s, still broadened (GAP-SRC-001). |
| `..._cron_own_fallback_still_runs_for_an_operator_with_no_profile` | An explicit query is honoured even with an empty profile — the 422 is for callers who supply nothing, not callers we disagree with. |
| `..._no_target_role_is_a_programming_error_not_a_persona` | `build_scout_query(None/"   ")` raises. |
| `..._a_real_role_is_still_broadened_to_its_family` | The GAP-SRC-001 half is intact. |
| `..._no_module_level_query_or_location_default_remains` | No constant is left to fall back to. |

**Fail-before / pass-after.** Both halves were run under one `flock /tmp/aether-pytest.lock` hold, by
restoring the pre-fix sources, running, then restoring the fixed ones — so the "before" is this exact
test file against the unfixed code, not an earlier draft.

- **Before** (`backend-pytest-FAIL-BEFORE-final.log`, pre-fix sources): **13 failed / 24 passed** —
  11 of the 14 new tests plus the 2 superseded `test_gap6` tests. The 3 new tests that passed are the
  deliberate regression guards (both cron replays + the broadening check), and `test_pipeline.py` /
  `test_rt_005_board_stage_sync.py` passed unchanged, proving the seeding added to them is a
  precondition rather than a weakened assertion. The headline red is literal: the first failure reads
  `assert 'business analyst, product owner, … transformation manager' == 'Senior Data Scientist'`.
- **After** (`backend-pytest-PASS-AFTER.log`, 12 targeted modules: the new file, `test_gap6_sourcing_volume`,
  `test_pipeline`, `test_rt_005_board_stage_sync`, `test_mv_resume_studio`, `test_gap_p7_async_001`,
  `test_gap_p7_discovery_001`, `test_job_discovery`, `test_scout_live_sources`, `test_agents_screen`,
  `test_gap_p6_paywall`, `test_ml_f1_f3_run_route_and_agent_list`): **154 passed, 1 skipped, 0
  failed** in 10m00s. The skip is `test_agents_screen.py:419`'s pre-existing conditional
  ("no planned cards remain in the catalog"), unrelated.

`ruff check` clean on every changed file and on `app/` as a whole (`backend-ruff.log`).

### 8.6 Residuals

1. **`scripts/discovery_cron.sh:91-92` still carries its own two literals** (§5 row 5). Unreached
   today (§8.4) and unchanged by ruling item 3, which asked for a cron fix only if the change would
   break it. If the operator ever clears their profile, the cron would search that stale persona
   instead of failing honestly.
2. **"Run All" has no client-side pre-check.** The Scout card asks before calling; the pipeline
   button learns from the 422 toast. Honest, but one round-trip worse than the Scout card. A
   frontend follow-up could reuse `deriveSearchTarget` there — and only then is a structured `detail`
   (see §8.2) worth introducing.
3. **`settings-client.tsx:403`'s comment is now stale** — it reasons about "the honest fallback [that]
   would have to guess". There is no fallback any more; the button gating it describes is *more*
   correct than the comment. Frontend file, deliberately not touched by this backend change.
4. **`apps/api/tests/_rt005_original_assertions_probe.py`** (another session's untracked probe) posts
   `{}` to `/agents/pipeline/run` and will now 422. One `seed_search_target(...)` line fixes it. Not
   touched — it is not this session's file.
5. **Production still runs the pre-fix code.** This change is committed, not deployed; no service was
   restarted (GOV-019).
6. **Refusal order vs. the paywall.** An unpaid user with no profile now sees the 422 before the 402
   (`_resolve_scout_target` runs before `_record_run`'s entitlement gate). Both are honest refusals
   and neither runs an agent; refusing an unanswerable request before charging for it is the
   defensible order, but it is a deliberate choice, not an accident. Every real caller sends an
   explicit query, so the 402 path is unchanged for them.
7. **Shared-tree incident (disclosed).** While this change was in flight, another session's commit
   `52fc727` swept up this session's uncommitted hunk in
   `apps/api/tests/test_rt_005_board_stage_sync.py` (the `seed_search_target` precondition + its
   `F-02:` comment) — the `git add` hazard the shared-tree rule exists to prevent, in the opposite
   direction. Consequence: between `52fc727` and this commit, HEAD imported
   `conftest.seed_search_target`, which did not exist in HEAD's `conftest.py` until now; this commit
   repairs that. Nothing was lost, but it is a governance event worth recording.
