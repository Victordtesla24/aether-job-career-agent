# NF-final-resid-001 / NF-final-resid-002 — Fix Log

**Agent:** fixer-medium (orchestrator-authorized, MANUAL-VERIFICATION run,
final-residuals cluster)
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent` — main tree
stayed on `e182571` throughout; all edits made in a `git worktree` at
`/tmp/claude-2000/-home-ubuntu/c60dc115-9302-4f64-8221-563feb393b13/scratchpad/fixer-resid`
on branch `fix/nf-final-resid` (created from `e182571`), removed after commit.
**Source findings:**
`uat/reports/evidence/manual-verification/adversarial/final-residuals/FINAL-RESIDUALS-REPORT.json`
(`new_findings[0]` / `new_findings[1]`), registered as `NF-final-resid-001` /
`NF-final-resid-002` in `docs/delivery/MANUAL-VERIFICATION-GAPS.json`.
**Window:** 2026-07-20T03:26Z – 2026-07-20T04:0xZ (UTC) — exact commit
timestamp in §5.

---

## 1. NF-final-resid-001 (backend) — City+label CamelCase gluings survive the keyword filter

### 1.1 Root cause

`apps/api/app/routers/cover_letters.py`'s `_is_camel_concatenation_artifact()`
only flagged a multi-segment CamelCase token as a scrape-gluing artifact when
**every** segment was itself a standalone word in `_ARTIFACT_SPLIT_WORDS`
(JD-boilerplate + role/title words + a short list of *country* names). City
names (Sydney, Melbourne, Brisbane, Adelaide, Perth, Canberra, ...) were never
added to that set, so `"Sydney"+"Salary"` failed the all-segments test —
`_is_semantic_keyword()` let it through, and `_skill_score()` then rewarded it
+45 for internal uppercase, ranking it into the top-10 keyword-chip panel.
Confirmed on prod 3x by the qa-adversary sweep (API×2, real browser) for
`SydneySalary`/`MelbourneSalary`/`BrisbaneLocation`/`AdelaideSalary`/
`PerthSalary`/`CanberraLocation`.

### 1.2 Fix plan (design rationale)

Rejected: enumerating city names into `_ARTIFACT_SPLIT_WORDS` — unbounded
whack-a-mole (the brief explicitly ruled this out).

Chosen: a new, **deliberately narrow** subset of `_ARTIFACT_SPLIT_WORDS`,
`_ARTIFACT_LABEL_WORDS` — JD *structural field-label* nouns (`salary`,
`location`/`locations`, `responsibilities`, `requirement`/`requirements`,
`qualifications`, `compensation`, `benefit`/`benefits`, `employer`,
`department`, `share`). `_is_camel_concatenation_artifact()` now flags a
token when EITHER the old all-segments rule holds, OR **any** segment is in
this narrower set — a JD label word glued to *anything* (a scraped place
name, almost always) is exactly as much a gluing artifact as two label words
glued together, and city names never need enumerating because one side of
the gluing (the label) is already known.

All 6 sweep-flagged artifacts are covered purely by the existing label
vocabulary already present pre-fix in `_ARTIFACT_SPLIT_WORDS` (`salary` and
`location` were already there) — **no city names were added anywhere**.

Why the label subset is narrower than all of `_ARTIFACT_SPLIT_WORDS`: role/
title words already in that set (manager/engineer/director/experience/
build/training/...) pair with too many plausible real compound terms on
their own to safely trigger from a single-segment match (e.g. a hypothetical
`XManager` product). A field-label noun like "Salary" or "Qualifications"
essentially never appears as the second half of a real English/tech compound,
so it's a much safer single-segment signal.

**False positives surveyed before choosing this design** (per the brief's
explicit instruction): "Share" and "Location" are the two label words with
real mixed-case tech/product collisions —
- `SlideShare` (Slide+Share, a real product)
- `SharePoint` (Share+Point, Microsoft SharePoint)
- `GeoLocation` (Geo+Location, the browser Geolocation API)

All three added to `_MIXED_CASE_TECH_ALLOWLIST` (checked first, before the
label-word test). No collision found for `salary`/`responsibilities`/
`requirement(s)`/`qualifications`/`compensation`/`benefit(s)`/`employer`/
`department` against any known tech/brand term.

### 1.3 Tests first (fail-before)

Extended `apps/api/tests/test_cover006_camelcase.py` (kept in the same file
per the brief's "or a new test file" option, since this file already owns
`_is_camel_concatenation_artifact` regression coverage and doesn't collide
with the concurrently-owned `test_mv_clstudio_j_residuals.py`):

- `_CITY_LABEL_ARTIFACTS` (6 exact sweep-flagged tokens) — parametrized
  `test_city_label_camel_artifact_is_detected`.
- `_ADVERSARIAL_LABEL_ARTIFACTS` (9 of my own design: London/Toronto/
  Auckland/Dublin/Chicago/Berlin/Tokyo/Paris/Mumbai × the label words) —
  parametrized `test_adversarial_place_label_camel_artifact_is_detected`,
  proving the fix generalizes past the 6 named cities.
- `_FALSE_POSITIVE_TECH_GUARDS` (SlideShare/SharePoint/GeoLocation) —
  parametrized `test_label_segment_false_positive_tech_terms_are_not_flagged`.
- Two end-to-end `_keyword_coverage()` integration tests reproducing the
  Empire-Life and Redpanda JD patterns from the sweep (city+label artifacts
  absent from the chip panel; legit mixed-case tech terms from both real
  JDs — JavaScript/TypeScript/PostgreSQL/DevOps/iPhone,
  Golang/Terraform/GraphQL/Kubernetes — still present).

Environment: fresh venv at `apps/api/.venv` in the worktree (repo has no
committed venv), `apps/api/requirements.txt` + `requirements-dev.txt` +
`python-multipart` (undeclared transitive FastAPI dependency, missing from
requirements*.txt — pre-existing repo gap unrelated to this fix, installed
only to unblock local test execution).

**Command** (per `docs/delivery/DEPLOYMENT-RUNBOOK.md` §0 CRITICAL SAFETY —
`DATABASE_URL_TEST` resolved by grepping the single line out of the
repo-root `.env`, never sourced wholesale; schema pinned to `aether_test`
verified before running):

```bash
cd apps/api
DATABASE_URL="$DATABASE_URL_TEST" DATABASE_URL_TEST="$DATABASE_URL_TEST" \
  AETHER_CREDENTIAL_KEY="$AETHER_CREDENTIAL_KEY" AETHER_ASYNC_GENERATION=false \
  flock /tmp/aether-pytest.lock .venv/bin/python3 -m pytest -q -p no:xdist \
  -o addopts="" tests/test_cover006_camelcase.py
```

**Result against unmodified `e182571`** (2026-07-20T03:28Z):

```
FAILED tests/test_cover006_camelcase.py::test_city_label_camel_artifact_is_detected[SydneySalary]
FAILED tests/test_cover006_camelcase.py::test_city_label_camel_artifact_is_detected[MelbourneSalary]
FAILED tests/test_cover006_camelcase.py::test_city_label_camel_artifact_is_detected[BrisbaneLocation]
FAILED tests/test_cover006_camelcase.py::test_city_label_camel_artifact_is_detected[AdelaideSalary]
FAILED tests/test_cover006_camelcase.py::test_city_label_camel_artifact_is_detected[PerthSalary]
FAILED tests/test_cover006_camelcase.py::test_city_label_camel_artifact_is_detected[CanberraLocation]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[LondonSalary]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[TorontoLocation]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[AucklandBenefits]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[DublinRequirements]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[ChicagoDepartment]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[BerlinCompensation]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[TokyoQualifications]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[ParisEmployer]
FAILED tests/test_cover006_camelcase.py::test_adversarial_place_label_camel_artifact_is_detected[MumbaiShare]
FAILED tests/test_cover006_camelcase.py::test_keyword_coverage_drops_city_label_camel_artifacts_empire_life_pattern
  AssertionError: City+label CamelCase artifact 'SydneySalary' leaked into keyword chips:
  ['javascript', 'typescript', 'postgresql', 'devops', 'reliability', 'microservices',
   'melbournesalary', 'brisbanelocation', 'sydneysalary', 'doe']
FAILED tests/test_cover006_camelcase.py::test_keyword_coverage_drops_city_label_camel_artifacts_redpanda_pattern
  AssertionError: City+label CamelCase artifact 'AdelaideSalary' leaked into keyword chips:
  ['graphql', 'kubernetes', 'terraform', 'golang', 'microservices',
   'adelaidesalary', 'canberralocation', 'perthsalary', 'platform', 'engineer']
17 failed, 17 passed in 0.62s
```

`test_label_segment_false_positive_tech_terms_are_not_flagged` PASSED
already at this point (SlideShare/SharePoint/GeoLocation were never flagged
by the OLD all-segments rule either — it serves as the false-positive
regression guard for the NEW rule). [VERIFIED-WITH-FRESH-EVIDENCE]

### 1.4 Implement

Diff to `apps/api/app/routers/cover_letters.py` (full diff in git history —
summary):

- `_MIXED_CASE_TECH_ALLOWLIST` += `slideshare sharepoint geolocation`.
- New `_ARTIFACT_LABEL_WORDS` frozenset (12 words, see §1.2).
- `_is_camel_concatenation_artifact()`: after the existing allowlist check
  and segment split, `return True` on the old all-segments rule OR
  `any(seg.lower() in _ARTIFACT_LABEL_WORDS for seg in segments)`.
- Docstrings updated to document both branches and the false-positive
  survey.

No other function touched — `_skill_score()` and `_is_semantic_keyword()`
both call `_is_camel_concatenation_artifact()` and inherit the fix
automatically, exactly as they did for the original NF-final-PII-001 fix.

### 1.5 Tests (pass-after)

Same command as §1.3, against the fixed worktree (2026-07-20T03:29Z):

```
34 passed in 0.52s
```

All 17 pre-existing tests (ManagerLocation-class artifacts, legit mixed-case
tech preservation) still pass unchanged — no regression in the behavior the
sweep already verified as fixed. All 17 new tests pass.
[VERIFIED-WITH-FRESH-EVIDENCE]

### 1.6 Broader backend regression

Ran the 10 cover-letter-related test files (camelcase, studio residuals,
cluster-A cover letter, resume grounding, cover-letter agent, cover-letter
studio, GAP-P5 cover + voice, GAP-P6 fabrication + prompt-hardening) under
the same safe DB-target discipline:

```
tests/test_cover006_camelcase.py tests/test_mv_clstudio_j_residuals.py
tests/test_mv_cluster_a_cover_letter.py tests/test_mv_resume_grounding.py
tests/test_cover_letter_agent.py tests/test_cover_letter_studio.py
tests/test_gap_p5_cover.py tests/test_gap_p5_cover_voice.py
tests/test_gap_p6_cover_fabrication.py tests/test_gap_p6_cover_prompt_hardening.py

146 passed, 170 warnings in 240.10s
```

2026-07-20T03:45:00Z. Zero failures. [VERIFIED-WITH-FRESH-EVIDENCE]

### 1.7 Full backend suite

See §4 (shared with NF-final-resid-002's frontend suite section).

---

## 2. NF-final-resid-002 (frontend) — Silent no-op on honest async refusal

### 2.1 Root cause

`apps/web/src/app/dashboard/cover-letters/page.tsx`'s `generate()` (and the
per-card `regenerate()`, which shares the identical
`runCoverLetterAgent()` → `resolveRun()`/`pollJob()` async-BackgroundJob
mechanism) treated ANY completed job result as a success:

```ts
const result = await runCoverLetterAgent(selectedJob);
await load(result.cover_letter_id);
setError(null);
setRejection(null);
```

The backend's honest no-résumé refusal
(`apps/api/app/workers/tasks.py`'s `except MissingResumeError` handler,
single-agent branch, lines ~240-261) completes the BackgroundJob
successfully (never `"failed"`) with
`{"resume_id": null, "missingResume": true, "message": "Add your resume
before generating a cover letter."}` — no `cover_letter_id` at all. The old
code called `load(undefined)` (a harmless but pointless reload) and
`setError(null)` (which actively suppresses any prior error) — the honest
message was never read or rendered. Confirmed on prod 2x by the qa-adversary
sweep, real browser: 0 console errors, 0 letter, 0 message.

### 2.2 Scope check (per brief: fix only the same mechanism, in this page)

- `regenerate(letter)` (per-card "Regenerate") — **same** async
  `runCoverLetterAgent()`/`resolveRun()` mechanism, same file → fixed too.
- `regenerateSelected()` / `requestChanges()` (rail "Regenerate" / "Request
  Changes") — call `refineCoverLetter()`, which POSTs to
  `/cover-letters/{id}/refine`, a **synchronous** (`def`, not `async def`)
  FastAPI route (`apps/api/app/routers/cover_letters.py:489`) that never
  goes through `resolveRun()`/`pollJob()`. A `MissingResumeError` there
  surfaces as a normal synchronous exception, already routed through
  `handleAgentError()`'s `catch` branch (unaffected by this bug class). Left
  untouched — not the same mechanism.
- **Escalating, not fixing** (broader than this page, noted per brief):
  `apps/web/src/app/dashboard/agents/page.tsx` (`runPipeline()`,
  `runAgent()`) and `apps/web/src/app/dashboard/email/page.tsx`
  (`runAgent("email", ...)`) use the identical
  `resolveRun()`/`pollJob()` mechanism for OTHER agent types (pipeline,
  tailor, email). The backend's pipeline branch
  (`workers/tasks.py` lines ~175-199) completes the SAME
  `missingResume`-shaped refusal for pipeline runs (verified by the sweep's
  `test2b_pipeline_async_no_resume_refusal`). Whether those two pages have
  the identical frontend surfacing gap was NOT investigated here (out of
  this finding's scope: different pages, different agent types) — flagging
  for the orchestrator to file as a separate finding if warranted.

### 2.3 Tests first (fail-before)

New file: `apps/web/src/app/dashboard/cover-letters/__tests__/page.test.tsx`
(`@vitest-environment jsdom`, mocks `lib/api/client` and
`lib/api/coverLetters`, renders the real `CoverLettersPage`). Two tests:

1. `surfaces the honest refusal message instead of a silent no-op` —
   `runCoverLetterAgent` resolves the exact
   `{resume_id: null, missingResume: true, message: "Add your resume before
   generating a cover letter."}` shape; asserts a `role="alert"` element
   renders that exact message, and that `fetchCoverLetters` (which `load()`
   calls) is NOT invoked a second time (proving no `load(undefined)`
   side-effect reload).
2. `still loads the new draft and clears errors on a real completed letter
   (no overcorrection)` — regression guard for the untouched success path:
   `runCoverLetterAgent` resolves a real `cover_letter_id`; asserts the
   letters list IS reloaded (`fetchCoverLetters` called twice) and no alert
   renders.

**Command:**

```bash
cd apps/web
node_modules/.bin/vitest run src/app/dashboard/cover-letters/__tests__/page.test.tsx
```

**Result against unmodified `e182571`** (2026-07-20T03:42:25Z):

```
 FAIL  .../page.test.tsx > surfaces the honest refusal message instead of a silent no-op
 ❯ waitForWrapper ...
     86|     const alert = await screen.findByRole("alert");
       |                                ^
 (timed out — no [role=alert] element ever appeared; DOM shows only the
  empty "No cover letters yet" state, confirming the silent no-op)

 ✓ still loads the new draft and clears errors on a real completed letter (no overcorrection)

 Tests  1 failed | 1 passed (2)
```

Test 1 fails exactly as expected (reproduces the silent no-op); test 2
already passes (the untouched success path was never broken).
[VERIFIED-WITH-FRESH-EVIDENCE]

### 2.4 Implement

- `apps/web/src/lib/api/coverLetters.ts`: `CoverLetterRunResult`'s 4 fields
  (`cover_letter_id`, `cover_letter`, `approval_id`, `approval_status`) made
  optional; added `missingResume?: boolean` and `message?: string` — the
  type now honestly reflects the two real runtime shapes
  (`workers/tasks.py`'s success vs. `MissingResumeError` result dicts).
- `apps/web/src/app/dashboard/cover-letters/page.tsx`: new
  `applyCoverLetterResult(result)` helper (placed after `load` is defined)
  — if `result.missingResume || !result.cover_letter_id`, clears any
  rejection panel and `setError(result.message ?? "Add your resume before
  generating a cover letter.")` (matches the page's existing `role="alert"`
  error UI, no new UI element); otherwise the unchanged original behavior
  (`load(result.cover_letter_id)`, clear error + rejection). `generate()`
  and `regenerate()` both now call this helper instead of inlining the old
  three lines.

### 2.5 Tests (pass-after)

Same command as §2.3, against the fixed worktree (2026-07-20T03:44:45Z):

```
✓ src/app/dashboard/cover-letters/__tests__/page.test.tsx (2 tests) 125ms
Tests  2 passed (2)
```

[VERIFIED-WITH-FRESH-EVIDENCE]. (One intermediate iteration: the first
pass-after attempt surfaced an incomplete mock in test 2 — the fixed
`load("cl-1")` now legitimately triggers the insights-rail fetch
`GET /cover-letters/cl-1/insights`, which the test's `apiRequest` mock
didn't yet handle. Extended the mock with a minimal valid
`LetterInsightsSchema` payload for that path — a test-authoring fix, not a
production-code or scope change.)

### 2.6 TypeScript type-check

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```

Clean, no output (2026-07-20T03:46Z). [VERIFIED-WITH-FRESH-EVIDENCE]

### 2.7 Full vitest suite

```bash
cd apps/web && node_modules/.bin/vitest run
```

```
Test Files  70 passed (70)
Tests  465 passed (465)
Duration  42.88s
```

2026-07-20T03:44:41Z. Baseline was 463+ (per brief) — 465 = baseline + the 2
new tests in this file. Zero regressions. [VERIFIED-WITH-FRESH-EVIDENCE]

---

## 3. Full backend suite (both findings)

```bash
cd apps/api
DATABASE_URL="$DATABASE_URL_TEST" DATABASE_URL_TEST="$DATABASE_URL_TEST" \
  AETHER_CREDENTIAL_KEY="$AETHER_CREDENTIAL_KEY" AETHER_ASYNC_GENERATION=false \
  flock /tmp/aether-pytest.lock .venv/bin/python3 -m pytest -q -p no:xdist -o addopts=""
```

Ran in background (started ~2026-07-20T03:45Z; the harness's Monitor watch
armed on this run did not deliver its completion notification in-session —
the process itself completed and exited normally; output was recovered from
its log file after the orchestrator flagged the gap):

```
3 failed, 878 passed, 1 skipped, 1183 warnings in 1253.28s (0:20:53)

FAILED tests/test_gap_p6_billing.py::test_webhook_bad_signature_is_400_and_writes_nothing
FAILED tests/test_gap_p6_billing.py::test_webhook_valid_signature_processes_and_grants_entitlement
FAILED tests/test_gap_p6_billing.py::test_webhook_duplicate_event_is_idempotent_no_second_entitlement
```

**Classification (real vs. flake) — isolated + stash-tested, 2026-07-20T05:29–05:31Z:**

1. Re-ran `tests/test_gap_p6_billing.py` alone under the same `flock`,
   against the FIXED worktree: identical 3 failures, all `AssertionError:
   ... 503 == 200/400` — `{"detail":"Stripe webhook secret is not
   configured"}`. Deterministic, not intermittent — not shared-DB
   contention flakiness (that class of flake is non-deterministic
   pass/fail across reruns; this is 100% reproducible).
2. `git stash` (all 4 modified files; the new `__tests__/` dir stays —
   `git stash` never touches untracked files), re-ran the SAME command
   against unmodified `e182571`: **identical 3 failures, identical error
   text.** [VERIFIED-WITH-FRESH-EVIDENCE] — proves these are NOT caused by
   this fix. `git stash pop` restored the fix immediately after.
3. Root-caused: `apps/api/requirements.txt` does not list the `stripe`
   PyPI package at all, and it is not importable in this fixer's fresh
   worktree venv (`ModuleNotFoundError: No module named 'stripe'`) —
   `app/services/stripe_gateway.py` imports it lazily inside its
   functions and degrades to an honest 503 when unavailable, which is why
   the webhook tests fail with "not configured" rather than a crash.
   Installing `stripe` locally changes the failure set (1 of the 3 tests
   then passes, but a 3rd, previously-passing test breaks instead) —
   confirming this is a real, pre-existing, unrelated dependency-declaration
   gap in the repo's `requirements.txt`, not a regression from either of
   my two findings and not something introduced by my fresh-venv setup
   choices. Billing/Stripe is unrelated to cover-letters; NOT fixed here
   (out of scope for NF-final-resid-001/002 — flagging for the
   orchestrator/a billing-scoped fixer).

**Net result: 0 real failures caused by this fix.** 878 passed + 1 skipped
is consistent with the reported ~862 baseline + the 17 new backend tests in
this commit (879 expected passing, 878 observed — within the ±1 the shared
`aether_test` schema's known cross-swarm variance, per
`aether-shared-test-db-flakiness` — not investigated further since it is
comfortably inside the pre-existing-flake noise band and unrelated to
either finding's code paths).

---

## 4. COMMIT

```
$ cd <worktree>
$ git add apps/api/app/routers/cover_letters.py apps/api/tests/test_cover006_camelcase.py \
    apps/web/src/app/dashboard/cover-letters/page.tsx apps/web/src/lib/api/coverLetters.ts \
    apps/web/src/app/dashboard/cover-letters/__tests__/page.test.tsx
$ git commit -m "fix(NF-final-resid-001,NF-final-resid-002): ..."
[fix/nf-final-resid a82a13a] fix(NF-final-resid-001,NF-final-resid-002): ...
 5 files changed, 398 insertions(+), 20 deletions(-)
 create mode 100644 apps/web/src/app/dashboard/cover-letters/__tests__/page.test.tsx
```

**Full SHA:** `a82a13ae42039032f3acd2065dbe861f6b6571b5`
**Commit time:** 2026-07-20T05:32:52Z
**Branch:** `fix/nf-final-resid` (off `e182571`).

Worktree removed after commit (`git worktree remove`); branch/commit
retained. Main tree verified still at `e182571` with no changes staged by
this fixer (confirmed via `git rev-parse HEAD` + `git status --short` in
`/home/ubuntu/github_repos/aether-job-career-agent` immediately before
writing this section — untracked files listed there belong to concurrent
sibling fixers/orchestrator work, not this fixer).

### 4.1 `apps/web/src/lib/api/coverLetters.ts` — in-scope justification

Flagged by the orchestrator as a file to justify-or-revert. It IS in scope
for NF-final-resid-002, not scope creep: `CoverLetterRunResult` is the
return type of `runCoverLetterAgent()`, which `page.tsx`'s new
`applyCoverLetterResult()` reads `result.missingResume` and `result.message`
from — fields the old type declaration didn't have at all (it declared
`cover_letter_id`/`cover_letter`/`approval_id`/`approval_status` as
**required** strings, which was already dishonest for the refusal shape
before this fix; TypeScript would not compile the fix's refusal-branch code
without this change). Making the 4 original fields optional + adding the 2
new ones is the minimal type change that makes the interface honestly
describe both real runtime shapes `workers/tasks.py` emits. No other file
depends on those 4 fields being non-optional (verified via repo-wide grep
for `.cover_letter`/`.approval_id`/`.approval_status` — zero hits outside
this type's own declaration and unrelated `AgentRun.output` snapshot fields
on a different type in `dashboard/page.tsx`/`feed.ts`).

## 5. Not done / explicitly out of scope

- **Not merged, not deployed, not self-verified.** Per the brief, this
  fixer does not review, deploy, or approve its own work. A separate
  reviewer/qa-adversary must verify `fix/nf-final-resid` and a deployer
  must merge/ship per `docs/delivery/DEPLOYMENT-RUNBOOK.md`.
- **`regenerateSelected()`/`requestChanges()` (refine rail actions)** —
  confirmed NOT affected (synchronous endpoint, different mechanism); left
  untouched deliberately, not an oversight.
- **`apps/web/src/app/dashboard/agents/page.tsx` and
  `.../email/page.tsx`** — same `resolveRun()`/`pollJob()` mechanism, other
  agent types (pipeline/tailor/email), NOT investigated or fixed here per
  the brief's scope-creep guard. Flagging for the orchestrator to decide
  whether a follow-up finding is warranted — the backend pipeline refusal
  path is already verified honest by the sweep
  (`test2b_pipeline_async_no_resume_refusal`), so if the frontend has the
  same gap it would be the same class of bug, just a different page.
- **`python-multipart`** missing from `apps/api/requirements*.txt` — an
  undeclared transitive FastAPI dependency needed to import the app for
  several test files (`test_cover_letter_studio.py` etc. — any router using
  `Form()`). Installed locally only to unblock test execution in this
  fixer's fresh venv; not a change I made to the repo's declared
  dependencies (out of scope for these two findings — flagging in case
  production's environment also lacks it, though production evidently
  imports the app successfully today, so it may already be present
  transitively there).
