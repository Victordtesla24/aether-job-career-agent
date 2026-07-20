# NF-final-closure-001 / NF-final-closure-002 — Fix Log

**Agent:** fixer-medium (orchestrator-authorized, MANUAL-VERIFICATION run,
final-closure cluster).
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent` — main tree
stayed on `99d1a34` throughout; all edits made in a `git worktree` at
`/tmp/claude-2000/-home-ubuntu/c60dc115-9302-4f64-8221-563feb393b13/scratchpad/fixer-closure`
on branch `fix/nf-final-closure` (created from `99d1a34`), removed after
commit.
**Source findings:**
`docs/delivery/MANUAL-VERIFICATION-GAPS.json` (`NF-final-closure-001`,
`NF-final-closure-002`) +
`uat/reports/evidence/manual-verification/adversarial/final-closure/FINAL-CLOSURE-REPORT.json`
(`new_findings[0]`/`new_findings[1]`).
**Window:** 2026-07-20T06:5x–07:24Z (UTC). Commit timestamps in §5.

Epistemic note: all test-execution claims below are
[VERIFIED-WITH-FRESH-EVIDENCE] from THIS run (fresh `apps/api/.venv`
built from `requirements.txt` + `requirements-dev.txt` + `python-multipart`;
`apps/web`/root `node_modules` symlinked, not copied, from the main tree —
main tree never written to; `DATABASE_URL`/`DATABASE_URL_TEST` resolved by
grepping the single line out of the repo-root `.env`, schema=`aether_test`
confirmed via substring match before every pytest run, never prod DSN;
`flock /tmp/aether-pytest.lock` held for every pytest invocation). Prior-run
reports (FINAL-CLOSURE-REPORT.json, the NF-final-resid fix-log/review) were
read as testimony/context only, then independently re-derived from the
current code before being relied on.

---

## 1. NF-final-closure-001 (backend) — Accented proper noun glued to a JD label leaks a fragment

### 1.1 Root cause [VERIFIED-WITH-FRESH-EVIDENCE, code + direct regex probes]

`apps/api/app/routers/cover_letters.py`'s tokenizer, `_WORD_RE =
re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")`, is ASCII-only. For a JD
containing `"MünchenLocation: hybrid"`, `_WORD_RE.findall` severs the token
at `"ü"`: `["M", "nchenLocation", "hybrid"]` (confirmed by direct regex
probe against the exact unfixed pattern). `_is_camel_concatenation_artifact`
then receives the surviving fragment `"nchenLocation"` — NOT the original
whole word — and `_CAMEL_HUMP_RE.findall("nchenLocation")` yields only
`["Location"]` (the lowercase `"nchen"` prefix starts no CamelCase segment
under `_CAMEL_HUMP_RE`'s own ASCII-only classes). `len(segments) < 2`
short-circuits `_is_camel_concatenation_artifact` to `False` **before** the
`any(seg.lower() in _ARTIFACT_LABEL_WORDS ...)` check (the exact rule that
already drops ASCII gluings like `SydneySalary`) ever runs — so
`"nchenlocation"` passes `_is_semantic_keyword` and is scored/surfaced as a
top keyword chip.

Direct regex probe (fresh Python3, this run) also confirmed the SAME root
cause produces a second, related leak the finding didn't name explicitly:
label-before-accent order (`"LocationMünchen"`) fragments into
`["LocationM", "nchen"]` — `"LocationM"` IS caught (segments
`["Location","M"]`, any-label rule fires), but the leftover `"nchen"`
(5 chars, no camel humps) independently survives `_is_semantic_keyword` as
a second garbage chip. Both directions share the identical root cause and
are both eliminated by the same fix (§1.2).

### 1.2 Fix (root cause, not the label-word gate)

Widened `_WORD_RE` to be Unicode-aware:

```python
_WORD_RE = re.compile(r"[^\W_](?:[^\W_]|[+#./-])*")
```

`[^\W_]` is any Unicode letter/digit (Python's `\w` minus underscore),
Unicode-aware by default (no `re.ASCII` flag was ever set). This keeps an
accented proper noun glued to anything as ONE whole token through
tokenization — `"MünchenLocation"` stays `"MünchenLocation"` — so it reaches
`_is_camel_concatenation_artifact` intact.
`_CAMEL_HUMP_RE.findall("MünchenLocation")` then yields `["M", "Location"]`
(2 segments — the leading `"M"` alone, since `_CAMEL_HUMP_RE`'s own
lowercase-run class is still ASCII-only and stops at `"ü"`, but that no
longer matters: `len(segments) >= 2` now, and `"location"` is a label word,
so the already-existing any-segment-is-a-label rule fires exactly as it
does for `SydneySalary`). **No change was needed to
`_is_camel_concatenation_artifact` or `_CAMEL_HUMP_RE`** — confirmed by a
dry-run probe of the fixed tokenizer + unmodified downstream functions
against 9 candidate strings (München/Zürich/Köln/Göteborg, both label
orders, plus `C++`/`Node.js`/`CI/CD` to confirm in-word punctuation
tokenizes identically to before) before touching the file.

The secondary "single-segment token whose one segment is a label word after
a lowercase fragment" guard suggested as a defense-in-depth option was
**not added**: the root-cause fix already makes that code path
unreachable for every case probed (the fragment that used to trigger it no
longer exists once the token stays whole), and adding an extra guard with
no known remaining trigger would only add unproven false-positive surface
— not "cheap and clearly safe" per the brief's own bar.

`_WORD_RE` is shared by `_tokens()`/`_meaningful()` (evidence-trace /
voice-metrics matching) in addition to `_jd_keywords()` — the wider
tokenization improves those call sites too (a legit accented résumé/JD word
no longer fragments into ASCII garbage there either; see §1.3's `résumé`
preserved-case test) and is exercised by the broader regression run (§1.4).

### 1.3 Tests first (fail-before) [VERIFIED-WITH-FRESH-EVIDENCE]

Extended `apps/api/tests/test_cover006_camelcase.py` (same file that already
owns this function's regression coverage, per precedent):

- `_ACCENTED_LABEL_ARTIFACTS` — 8 parametrized cases
  (`test_accented_label_camel_artifact_leaves_no_fragment`): the exact
  reported `MünchenLocation`, both gluing orders, 3 different accented
  letters (ü/ö), different label words, asserting BOTH the pre-fix garbage
  fragment and the whole glued token are absent from `_jd_keywords()`.
- `test_keyword_coverage_drops_muenchen_location_class_artifact_reported_pattern`
  — end-to-end `_keyword_coverage()` reproduction of the exact reported
  repro pattern, plus legit mixed-case tech term preservation.
- `test_unglued_accented_city_name_is_not_flagged_as_artifact` — preserved
  case: `Zürich`/`München` standing alone are not artifacts.
- `test_accented_word_survives_tokenization_intact_no_garbage_fragments` —
  preserved case: `résumé` in JD prose must not fragment into a spurious
  `"sum"` chip and must survive as itself.

**Command** (worktree venv, `aether_test` schema confirmed):

```bash
cd apps/api
DATABASE_URL="$DATABASE_URL_TEST" DATABASE_URL_TEST="$DATABASE_URL_TEST" \
  AETHER_CREDENTIAL_KEY="$AETHER_CREDENTIAL_KEY" AETHER_ASYNC_GENERATION=false \
  flock /tmp/aether-pytest.lock .venv/bin/python3 -m pytest -q -p no:xdist \
  -o addopts="" tests/test_cover006_camelcase.py
```

**Fail-before** (router `_WORD_RE` git-stashed back to the unfixed pattern,
new test file present, 2026-07-20T~07:05Z):

```
10 failed, 35 passed, 1 warning in 0.64s
```

10 failures = the 8 parametrized cases + the 2 new integration/preserved
tests that require the whole-word fix (`résumé` fragmenting into `"sum"`
and the reported `MünchenLocation` repro). The "unglued Zürich/München"
preserved-case test already passed pre-fix (correctly — it was never the
bug), confirming the test suite discriminates precisely.
[VERIFIED-WITH-FRESH-EVIDENCE]

### 1.4 Implement + pass-after [VERIFIED-WITH-FRESH-EVIDENCE]

`git stash pop` restored the one-line `_WORD_RE` change (§1.2). Same
command, 2026-07-20T~07:07Z:

```
45 passed, 1 warning in 0.52s
```

All 34 pre-existing tests (ManagerLocation-class, city+label, false-positive
tech guards, legit mixed-case preservation) still pass unchanged. All 11 new
tests pass.

### 1.5 Broader backend regression [VERIFIED-WITH-FRESH-EVIDENCE]

Ran the 11 cover-letter-related test files (camelcase + the 10 files the
prior NF-final-resid fix-log also regression-tested, plus
`test_mv_clstudio_003.py`) under the same discipline, backgrounded (~4 min):

```
tests/test_cover006_camelcase.py tests/test_mv_clstudio_j_residuals.py
tests/test_mv_cluster_a_cover_letter.py tests/test_mv_resume_grounding.py
tests/test_cover_letter_agent.py tests/test_cover_letter_studio.py
tests/test_gap_p5_cover.py tests/test_gap_p5_cover_voice.py
tests/test_gap_p6_cover_fabrication.py tests/test_gap_p6_cover_prompt_hardening.py
tests/test_mv_clstudio_003.py

162 passed, 179 warnings in 244.29s (0:04:04)
```

2026-07-20T~07:16Z. Zero failures.

### 1.6 Commit

`019a9e985c6c9ad6e90470e62df63036f795ed89` @ 2026-07-20T07:18:35Z, branch
`fix/nf-final-closure`. Files: `apps/api/app/routers/cover_letters.py`,
`apps/api/tests/test_cover006_camelcase.py` (2 files, 143 insertions, 1
deletion).

---

## 2. NF-final-closure-002 (frontend) — Agents console + pipeline mis-surface the honest no-résumé refusal as success

### 2.1 Root cause [VERIFIED-WITH-FRESH-EVIDENCE, code reading]

`apps/api/app/workers/tasks.py`'s `except MissingResumeError` handler
(BOTH the single-agent branch, lines ~240-261, and the pipeline branch,
lines ~175-199) completes the BackgroundJob — never `"failed"` — with
`{"resume_id": None, "missingResume": True, "message": honest_message}`.

`apps/web/src/app/dashboard/agents/page.tsx`'s `trigger()` and `pipeline()`
fed that result straight into `agentSuccessNotice(backend, output)` /
`pipelineCompletionNotice(result)` (`lib/agents-feedback.ts`) without
checking for the refusal shape first:

- `agentSuccessNotice("tailor", {missingResume:true, message:"..."})` reads
  `output.changes` (`undefined` → `Number(undefined ?? 0)` = `0`) →
  `"Tailor finished — resume tailored with 0 accepted changes."` (FALSE
  SUCCESS, CTA to a non-existent diff).
- `agentSuccessNotice("coverLetter", ...)` doesn't read `output` at all for
  this branch — hardcoded `"CoverLetter finished — a draft is awaiting your
  sign-off."` regardless of the refusal (FALSE SUCCESS, CTA to an empty
  Approvals queue).
- `pipelineCompletionNotice({missingResume:true, message:"..."})`: no
  `steps`/`approvalRequired` on a refusal → falls to the
  no-jobs-matched-yet else-branch → `"Pipeline complete — no jobs matched
  yet. Run Scout..."` (FALSE SUCCESS, wrong remediation — the blocker is a
  missing résumé, not missing jobs).
- fitScorer is **synchronous** (no BackgroundJob) — its honest 422
  `{"detail": "Add your resume before scoring jobs against it."}` throws an
  `ApiError`, caught by `runErrorNotice(e, "fitScorer")`, whose 422 branch
  was a HARDCODED string ("needs more data first — run Scout to discover
  jobs") that ignored the real `err` entirely — dropping the honest detail
  AND pointing at the wrong remediation (jobs already exist).

### 2.2 Fix

`apps/web/src/lib/agents-feedback.ts`:

- New `missingResumeNotice(output)`: returns `null` unless
  `output.missingResume === true`; otherwise an honest `kind:"error"`
  Notice carrying `output.message` (falling back to a generic honest string
  only if the backend ever omitted `message`), CTA → `/dashboard/resume`.
- `runErrorNotice`'s `422` branch now calls the pre-existing
  `extractApiDetail(err)` helper (already used by
  `providerCredentialErrorNotice`) and surfaces the real backend detail
  when extractable (`"${context} failed — ${detail}"`, no guessed href);
  falls back to the original hardcoded "run Scout" copy + Jobs link only
  when no detail can be extracted (preserves the existing
  `runErrorNotice({status:422}, "Tailor")` no-detail test case unchanged).

`apps/web/src/app/dashboard/agents/page.tsx`: `trigger()` and `pipeline()`
now call `missingResumeNotice(output/result) ?? agentSuccessNotice(...)` /
`?? pipelineCompletionNotice(...)` — a one-line guard at each of the two
call sites, mirroring `applyCoverLetterResult`'s pattern in
`dashboard/cover-letters/page.tsx` (NF-final-resid-002) exactly as the
finding's `fix_hint` requested. No other function touched;
`agentSuccessNotice`/`pipelineCompletionNotice` themselves are unchanged —
they still render the correct success text for every REAL completion
(verified by the 2 regression-guard tests in §2.3).

### 2.3 Tests first (fail-before) [VERIFIED-WITH-FRESH-EVIDENCE]

New `apps/web/src/app/dashboard/agents/__tests__/page.test.tsx` (6 tests,
DOM-level, mirrors the `cover-letters/__tests__/page.test.tsx` pattern:
mocks `lib/api/client`, `lib/api/agents`, `components/agents/api`; renders
the real `AgentsPage`):

1. tailor refusal → honest message renders, no "accepted changes" text, no
   green class.
2. coverLetter refusal → honest message renders, no "awaiting your
   sign-off" text, no green class.
3. pipeline ("Run All") refusal → honest message renders, no "Pipeline
   complete" text, no green class.
4. fitScorer refusal (sync 422, real `ApiError`-shaped rejection) → the
   real backend detail renders, not "run Scout to discover jobs".
5. regression guard: a REAL tailor completion (`changes:4`) still renders
   the original green "4 accepted changes" success notice.
6. regression guard: a REAL pipeline completion (`approvalRequired:true`,
   `matched:4`) still renders the original green "4 jobs matched" success
   notice.

Plus 5 new unit tests in `apps/web/src/__tests__/dashboard/agents-feedback.test.ts`
(`missingResumeNotice` positive/fallback/null cases incl. the unrelated
`NoChangesApplied` shape staying unaffected; `runErrorNotice`'s new
422-detail branch).

**Command:**

```bash
cd apps/web
node_modules/.bin/vitest run src/__tests__/dashboard/agents-feedback.test.ts \
  src/app/dashboard/agents/__tests__/page.test.tsx
```

**Fail-before** (`lib/agents-feedback.ts` + `agents/page.tsx` git-stashed
back to unfixed, new test files present, 2026-07-20T~07:21Z):

```
Test Files  2 failed (2)
     Tests  9 failed | 17 passed (26)
```

9 failures = the 4 DOM refusal tests + 5 unit tests (the `missingResumeNotice`
describe block's other cases also failed at this point because the import
itself doesn't exist pre-fix, cascading correctly). The 2 DOM
regression-guard tests and the pre-existing 503/401/generic-failure/
run-Scout-fallback `runErrorNotice` tests already passed pre-fix (correctly
— they cover behavior this fix does not change).
[VERIFIED-WITH-FRESH-EVIDENCE]

### 2.4 Pass-after [VERIFIED-WITH-FRESH-EVIDENCE]

`git stash pop` restored the fix. Same command, 2026-07-20T~07:21Z:

```
Test Files  2 passed (2)
     Tests  26 passed (26)
```

(6 in `page.test.tsx` + 20 in `agents-feedback.test.ts`.) Also re-ran
`src/__tests__/agents/agents-screen.test.ts` (unrelated pure-logic tests
for the same screen) — 21 passed, confirming no collateral regression in
the screen's other logic.

### 2.5 Full vitest suite + typecheck [VERIFIED-WITH-FRESH-EVIDENCE]

```bash
cd apps/web && node_modules/.bin/vitest run
```

```
Test Files  71 passed (71)
     Tests  476 passed (476)
Duration    85.04s
```

2026-07-20T07:21:44Z–07:23:09Z. Baseline was 465 (per brief) — 476 = 465 +
11 new tests in this commit (6 + 5). Zero regressions.

```bash
cd apps/web && node_modules/.bin/tsc --noEmit
```

Clean, no output, exit 0 (2026-07-20T~07:23Z).

### 2.6 Email page determination [VERIFIED-WITH-FRESH-EVIDENCE, code reading — NOT changed]

`apps/web/src/app/dashboard/email/page.tsx` calls `runAgent("email", ...)`
in 3 places: `mode:"triage"` (`runTriage`), `mode:"insights"`
(`analyzeThread`), `mode:"draft_reply"` (`generateDraft`). Investigated
whether any of these can produce the `missingResume:true` "completed"
refusal shape this finding is about:

- `_triage()` and `_insights()` in `apps/api/app/agents/email_agent.py`
  never call résumé grounding at all (confirmed by reading both method
  bodies in full) — structurally cannot hit this bug.
- `_compose_draft()` (used by `draft_reply`) DOES require a résumé
  (`self._resume_text(user_id)` →
  `resolve_user_resume_text(user_id, allow_operator_fallback=False)`), but
  `resolve_user_resume_text` (in `app/services/resume_grounding.py`) does
  **not** raise on empty — it returns `""`. `_compose_draft` then does its
  own manual check and raises `EmailAgentError("Add your resume before
  drafting a reply.")` — `EmailAgentError` is a `ValueError` subclass
  (`class EmailAgentError(ValueError)`), **not** `MissingResumeError`.
  `grep -n "EmailAgentError" apps/api/app/workers/tasks.py
  apps/api/app/routers/agents.py` → no matches: nothing in the async job
  pipeline special-cases it, so it falls through to `workers/tasks.py`'s
  generic `except Exception as exc` branch, which calls
  `repo.mark_failed(job_id, _honest_message(exc))` — the job is marked
  **"failed"**, not "completed" with `missingResume:true`. `resolveRun()`
  (`lib/api/agents.ts`) throws an `ApiError` on a `"failed"` job, which
  `generateDraft()`'s existing `catch (e) { setDraftError(e instanceof
  Error ? e.message : ...) }` already surfaces honestly (no false-success
  masking possible on this path).
- Structurally, `email/page.tsx` also does **not** import or call
  `agentSuccessNotice`/`pipelineCompletionNotice`/`runErrorNotice` from
  `lib/agents-feedback.ts` at all (confirmed by grep) — its 3 handlers
  build their own inline notices from checked, honest fields (e.g.
  `if (!text) { setDraftError("The AI returned an empty draft..."); }`),
  so there is no shared surfacing mechanism on this page to fix.

**Conclusion: email/page.tsx is NOT affected by NF-final-closure-002 and
was intentionally left unmodified.** One unrelated, out-of-scope
observation surfaced during this investigation: `_honest_message()` (the
shared exception-to-string formatter in `workers/tasks.py`) prefixes a
generic (non-`HTTPException`) exception's class name onto its message
(`f"{name}: {msg}"`), so a résumé-missing `draft_reply` failure's `error`
field reads `"EmailAgentError: Add your resume before drafting a reply."`
— a cosmetic class-name leak, not a false-success, and a cross-cutting
formatter shared by every single-agent/pipeline job (not scoped to email or
to this finding). Flagging for the orchestrator, not fixed here.

### 2.7 Commit

`87394555c53b4ec091fa9a05de232b7360134ae8` @ 2026-07-20T07:23:56Z, branch
`fix/nf-final-closure`. Files: `apps/web/src/lib/agents-feedback.ts`,
`apps/web/src/app/dashboard/agents/page.tsx`,
`apps/web/src/__tests__/dashboard/agents-feedback.test.ts`,
`apps/web/src/app/dashboard/agents/__tests__/page.test.tsx` (new) — 4
files, 351 insertions, 3 deletions.

---

## 3. Not done / explicitly out of scope

- **Not merged, not deployed, not self-verified.** A separate
  reviewer/qa-adversary must independently verify `fix/nf-final-closure`
  and a deployer must merge/ship per `docs/delivery/DEPLOYMENT-RUNBOOK.md`.
- **`email/page.tsx`** — investigated and determined unaffected (§2.6), left
  unmodified deliberately, not an oversight.
- **`_honest_message()`'s class-name-prefix leak** on generic (non-HTTPException)
  worker exceptions (§2.6) — pre-existing, cross-cutting, unrelated to
  either finding's own scope; not fixed here, flagged for the orchestrator.
- **The secondary "single-segment label-after-lowercase-fragment" defense-in-depth
  guard** suggested in NF-final-closure-001's fix_hint — not added; the
  root-cause fix already makes the trigger condition unreachable for every
  case probed (§1.2).

## 4. Summary (fail-before / pass-after)

| Finding | File(s) | Fail-before | Pass-after |
|---|---|---|---|
| NF-final-closure-001 | `tests/test_cover006_camelcase.py` | 10 failed, 35 passed | 45 passed |
| NF-final-closure-002 | `agents-feedback.test.ts` + `agents/__tests__/page.test.tsx` | 9 failed, 17 passed | 26 passed |

Broader backend regression (11 cover-letter files): 162 passed, 0 failed.
Full frontend suite: 476 passed (465 baseline + 11 new), 0 failed.
`tsc --noEmit`: clean.

Worktree removed after this log was written (`git worktree remove`);
branch/commits retained on `fix/nf-final-closure`. Main tree verified still
at `99d1a34` throughout (`git rev-parse HEAD` / `git status --short` in
`/home/ubuntu/github_repos/aether-job-career-agent` — untracked files
present there belong to concurrent sibling fixers/orchestrator artifacts,
not this fixer).

---

## 5. CORRECTION (2026-07-20T07:43Z) — review verdict FAIL on NF-final-closure-002, regression fixed

**Review:**
`uat/reports/evidence/manual-verification/reviews/review-nf-final-closure.json`
(reviewer, independent, 2026-07-20T07:37:32Z). Verdict: NF-final-closure-001
(commit `019a9e9`) **PASS**, unchanged, no action. NF-final-closure-002
(commit `8739455`) **FAIL** — one concrete, independently-reproduced
regression (check `2c-runErrorNotice-scout-hint-regression`).

### 5.1 The regression [reviewer-found, independently re-confirmed in this correction]

`apps/web/src/app/dashboard/agents/page.tsx`'s `resolveParams()` (unchanged
by either NF-final-closure-002 commit) throws a CLIENT-SIDE synthetic 422
for `trigger('tailor')`/`trigger('coverLetter')` whenever the user's jobs
list is empty: `Object.assign(new Error("No jobs discovered yet"), {status:
422})`. This is the ordinary, pre-existing "you have zero jobs, run Scout
first" scenario — not a genuine backend-returned 422.

§2 of this fix-log's original `runErrorNotice` 422 change (`const detail =
extractApiDetail(err); if (detail) {...}`) did not account for this shape:
`extractApiDetail` falls back to the raw `err.message` whenever the message
doesn't end in a JSON `{"detail":...}` blob — so for this synthetic error
`detail = "No jobs discovered yet"` (truthy, not null), and the 422 branch
took the "surface the detail" path, producing `{text:"Tailor failed — No
jobs discovered yet"}` with **no `href`/`hrefLabel`** — silently dropping
the original, purpose-built, actionable `/dashboard/jobs` navigation CTA
and the "run Scout to discover jobs, then try again" directive copy.
Neither of the original commit's own tests covered this exact runtime
shape: one used a bare non-`Error` `{status:422}` object with no message,
the other a genuine backend 422 with a real JSON body — the actual
`resolveParams()` shape (a real `Error`, plain non-JSON message, thrown
client-side) fell through untested.

Re-confirmed independently in this worktree before implementing the fix:
running the reviewer's exact input against `runErrorNotice` at `8739455`
reproduces `{text:"Tailor failed — No jobs discovered yet"}` with no href
(fail-before, §5.2).

### 5.2 Fix (minimal, per required_changes_for_pass)

New `extractApiJsonDetail(err)` in `apps/web/src/lib/agents-feedback.ts` —
a strict variant of `extractApiDetail` that returns the parsed JSON
`detail` ONLY when `err.message` genuinely ends in a `{...}` blob that
parses as JSON with a string `detail` field; returns `null` (never falls
back to the raw message) otherwise. `runErrorNotice`'s 422 branch now calls
`extractApiJsonDetail` instead of `extractApiDetail` — one line changed at
the call site, plus the new ~25-line helper function.
`extractApiDetail` itself and `providerCredentialErrorNotice`'s use of it
are **UNCHANGED** (per the review's explicit instruction) — that call
site's raw-message fallback remains correct, since every error reaching it
is a real backend response, never a client-side synthetic one.

New worktree for this correction: fresh `git worktree add
/tmp/claude-2000/-home-ubuntu/c60dc115-9302-4f64-8221-563feb393b13/scratchpad/fixer-closure-review
fix/nf-final-closure`, confirmed `HEAD == 8739455` before any edit
(`git rev-parse HEAD`).

**Test first** (new regression test in `agents-feedback.test.ts`, added
before any source change): asserts
`runErrorNotice(Object.assign(new Error("No jobs discovered yet"),
{status:422}), "Tailor")` returns `href:"/dashboard/jobs"`,
`hrefLabel:"open Jobs →"`, and text containing "run Scout to discover
jobs" / NOT containing "No jobs discovered yet".

**Fail-before** (@`8739455`, unmodified `agents-feedback.ts`, new test
present, 2026-07-20T07:41:06Z):

```
Test Files  1 failed (1)
     Tests  1 failed | 20 passed (21)
```

The 1 failure is exactly the new regression test
(`expected 'Tailor failed — No jobs discovered yet' to contain 'run Scout
to discover jobs'`) — reproduces the reviewer's finding precisely. The
other 20 pre-existing `runErrorNotice`/`missingResumeNotice` tests already
passed (unaffected by this bug).

**Pass-after** (fix applied, 2026-07-20T07:41:41Z):

```bash
cd apps/web
node_modules/.bin/vitest run src/__tests__/dashboard/agents-feedback.test.ts \
  src/app/dashboard/agents/__tests__/page.test.tsx
```

```
Test Files  2 passed (2)
     Tests  27 passed (27)
```

(21 in `agents-feedback.test.ts` [20 original + 1 new] + 6 in
`page.test.tsx`, unaffected.)

**Full vitest suite** (2026-07-20T07:41:49Z–07:43:10Z):

```
Test Files  71 passed (71)
     Tests  477 passed (477)
```

477 = 476 baseline (post §2.5) + 1 new regression test. Zero failures.

**`tsc --noEmit`** (2026-07-20T~07:43Z): clean, exit 0, no output.

### 5.3 Commit

`87590d9b32e7131573b51fbf609a747040ac4ea2` @ 2026-07-20T07:43Z, branch
`fix/nf-final-closure`, one commit: `fix(NF-final-closure-002): preserve
Scout-guidance notice for client-side zero-jobs 422 (review regression)`.
Files:
`apps/web/src/lib/agents-feedback.ts`,
`apps/web/src/__tests__/dashboard/agents-feedback.test.ts` — 2 files, 63
insertions, 4 deletions. Backend commit `019a9e9` (NF-final-closure-001)
untouched, as instructed. `agents/page.tsx` untouched — the fix lives
entirely inside the `agents-feedback.ts` detail-extraction helper, per the
review's required-change option (a).

### 5.4 Corrected summary table

| Finding | File(s) | Fail-before | Pass-after |
|---|---|---|---|
| NF-final-closure-001 | `tests/test_cover006_camelcase.py` | 10 failed, 35 passed | 45 passed |
| NF-final-closure-002 (initial) | `agents-feedback.test.ts` + `agents/__tests__/page.test.tsx` | 9 failed, 17 passed | 26 passed |
| NF-final-closure-002 (review correction) | `agents-feedback.test.ts` | 1 failed, 20 passed | 21 passed |

Worktree `scratchpad/fixer-closure-review` removed after this correction
was written; branch `fix/nf-final-closure` now has 3 commits (`019a9e9`,
`8739455`, and the correction) on top of `99d1a34`, none merged/pushed.
Main tree verified still at `99d1a34` throughout.
