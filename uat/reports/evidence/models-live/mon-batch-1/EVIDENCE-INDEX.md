# EVIDENCE-INDEX.md — MON-batch-1

Written by the evidence-remediation agent in response to
`../mon-batch-1-be-rereview-verdict.json` (one directory up from this file —
verdict: FAIL on NEW-BE-1 and NEW-BE-2 only; all four prior findings
independently reconfirmed RESOLVED). This index
maps every code-fix commit in MON-batch-1 to its RED (fail-before) and GREEN
(pass-after) evidence. Mechanical evidence-hygiene scope only — no production
code or test logic was changed to produce this file.

**Path convention:** every bare filename below (no `../` prefix) is relative
to this file's own directory. That directory exists in two places, kept
byte-identical for every file cited here (verified with `diff -q` at write
time). The two `../mon-batch-1-*-review-verdict.json` files referenced in
prose (not evidence-map entries — they are the review documents this
remediation responds to) live one directory up, in
`uat/reports/evidence/models-live/` directly, in both checkouts:

- `aether-wt-market-perf` (this worktree, branch `feat/mon-batch-1`):
  `uat/reports/evidence/models-live/mon-batch-1/`
- `aether-job-career-agent` (main checkout):
  `uat/reports/evidence/models-live/mon-batch-1/`

Both are gitignored (`evidence/` in `uat/reports/.gitignore`); only this index
file is force-tracked in git (`git add -f`), matching an existing precedent in
this repo (`uat/reports/evidence/models-live/wave4c/full-backend-suite-*.txt`
is likewise force-tracked despite the same ignore rule).

## Remediation of the two open findings

- **NEW-BE-1** (stray 5-line misdirected capture at
  `fe-refix-pass-after-20260813T123031Z.log`, no summary/exit status, content
  from an unrelated test file, captured before d248391 even existed): deleted.
  Not replaced in place — d248391's own evidence need is covered by
  `mon-batch-1-refix-PASS-AFTER-20260813T123400Z.log` (below), which already
  existed, was already verified genuine by the re-reviewer, and simply hadn't
  been copied into this repo (see NEW-BE-2).
- **NEW-BE-2** (d248391 cites no evidence path; its genuine RED/PASS-AFTER/lint
  files existed only in the worktree, breaking the dual-location convention
  every other commit in this chain follows): the three worktree-only files are
  now copied into this repo byte-identical (`diff -q` clean), and this index
  supplies the citation d248391's own commit message omitted.

## Commit → evidence map

### `20d58c5` / `b0aa62c` / `b568e65` / `5578f96` / `82c1502` — TDD stage (tests-first)

These five commits added FAILING tests before any fix existed
(`test(MON-00N): failing test for …`). They are the origin of the "RED"
evidence cited below for the fix commits that follow each one. No separate
evidence artifact is attached to the test-authoring commits themselves; their
RED state is captured together with the corresponding fix's RED reconstruction
(next section), since both need the same pre-fix source tree.

### `eb35231` — fix(MON-001): bound the board-sweep target selection

- **RED**: `pytest-mon001-boardsweep-failbefore-20260813T121804Z.log`
  — reconstructed post-hoc (source under test reverted to the verified
  pre-fix origin/main blob; see file header for the `git diff` provenance
  check). Honestly labelled as a reconstruction, not a recording of the
  original RED run — eb35231's original run was never written to disk
  (this is exactly what the prior BE review, and 643f07b's remediation of
  it, established; re-verified present and correct by the re-reviewer).
- **GREEN**:
  - `mon-batch-1-evidence-remediation-BACKEND-PASSAFTER-20260813T124409Z.log`
    — FRESH, captured by this remediation pass at current HEAD (`d248391`):
    `nice -n 10 flock /tmp/aether-pytest.lock scripts/run-tests.sh
    tests/test_mon001_board_sweep_bounded_read.py
    tests/test_rt_007_board_sweep.py
    tests/test_ml_w19_w20_board_sweep_suppression.py
    tests/test_mon011_honest_format_integrity.py tests/test_resume_upload.py
    tests/test_mv_resume_studio.py tests/test_resume_ingest.py
    tests/test_mv_resume_grounding.py -q` → **84 passed, exit-status 0**.
  - `pytest-mon001-boardsweep-passafter-20260813T121859Z.log` (historical,
    captured 121859Z against the committed fix) — supplementary.

### `5355edc` — fix(MON-004, MON-005): retry + JWT-argv fix

- **RED+GREEN** (combined in one artifact, as originally captured):
  `shell-mon004-mon005-failbefore-passafter-20260813T115310Z.log` — FAIL-BEFORE
  section run against `origin/main`'s `scripts/discovery_cron.sh` (6
  assertions fail for MON-004, 2 for MON-005, both `RESULT: FAIL`); PASS-AFTER
  section run against the worktree's fixed script (all assertions pass, both
  `RESULT: PASS`, `rc=0`). Genuine, not reconstructed — captured during the
  original build at 11:53:10Z, before the fix commit (11:56:30Z) landed.

### `e9385de` — fix(MON-011): expose an honest formatPreserved flag (backend)

- **RED**: `pytest-resume-adjacent-failbefore-20260813T121804Z.log`
  — same reconstruction run as eb35231's RED (same combined pytest invocation,
  source reverted to pre-fix origin/main blobs for
  `apps/api/app/routers/resumes.py` and `apps/api/app/services/resume_pdf.py`).
  Honestly labelled as a post-hoc reconstruction.
- **GREEN**:
  - `mon-batch-1-evidence-remediation-BACKEND-PASSAFTER-20260813T124409Z.log`
    — same FRESH run cited under eb35231 above (it includes
    `test_mon011_honest_format_integrity.py` and the adjacent resume suites
    e9385de's own commit message names) → **84 passed, exit-status 0**.
  - `pytest-resume-adjacent-passafter-20260813T121859Z.log` (historical) —
    supplementary.

### `fd7cca0` — fix(MON-010, MON-011): Clear-filters label + Format Integrity disclosure (FE round 1)

- **RED**:
  - `mon-010-011-fe-fail-before-fresh-20260813T122009Z.log` — reconstructed:
    `page.tsx`/`resumes.ts` reverted to the pre-fd7cca0 origin/main blobs,
    2 failed / 28 passed (30) — exactly the MON-010 and MON-011 assertions.
  - `mon-010-011-fe-fail-before-provenance-20260813T122141Z.log` — method,
    blob SHAs, and the explicit reconstruction caveat.
- **GREEN**:
  - `mon-010-011-fe-pass-after-20260813T122049Z.log` — captured against
    fd7cca0's own committed tree (HEAD=fd7cca0 at capture time): 6 files / 30
    tests passed, exit-status 0, including all four adjacent suites
    (`resume-mv-honesty`, `resume-hero-identity`, `resume-tailor-score-warning`,
    `resume-conversion-tooltip`) fd7cca0's own commit message names as passing.
  - `mon-010-011-fe-tsc-lint-20260813T122109Z.log` — tsc 0 errors, eslint 0
    warnings.
  - **⚠ See "Known gap" below** — one of the four adjacent suites this GREEN
    run covered (`resume-mv-honesty.test.tsx`, MV-resume-studio-004) no longer
    passes at current HEAD. The regression was introduced by the *later*
    commit d248391, not by fd7cca0; fd7cca0's own GREEN evidence for its own
    tree state is genuine and unaffected.

### `643f07b` — fix(MON-001): multi-page keyset coverage + RED-evidence reconstruction

- **RED**: same two reconstruction files as eb35231 (backend) — this commit's
  own two new tests
  (`test_candidate_walk_pages_and_resumes_on_the_keyset_without_gaps_or_dupes`,
  `test_next_target_selects_a_winner_that_lives_beyond_the_first_page`) are
  included in that same failbefore run and both fail pre-fix with
  `AttributeError: ... has no attribute '_CANDIDATE_PAGE_SIZE'`
  (`pytest-mon001-boardsweep-failbefore-20260813T121804Z.log`).
  This commit is also the one that produced the FE reconstruction files cited
  under fd7cca0 above (`mon-010-011-fe-fail-before-fresh-*`,
  `mon-010-011-fe-fail-before-provenance-*`, `mon-010-011-fe-pass-after-*`,
  `mon-010-011-fe-tsc-lint-*`) and the backend ones cited under eb35231/e9385de.
- **GREEN**: `mon-batch-1-evidence-remediation-BACKEND-PASSAFTER-20260813T124409Z.log`
  (FRESH, this pass) plus `pytest-mon001-mon011-passafter-20260813T121859Z.log`
  (historical) — both include `test_mon001_board_sweep_bounded_read.py` in
  full, i.e. the two new keyset tests.

### `d248391` — fix(MON-011): re-fix FE review findings (FE round 2)

No evidence path was cited in this commit's own message (NEW-BE-2). Supplied
here:

- **RED**: `mon-batch-1-refix-FAIL-BEFORE-20260813T123400Z.log` — round-2
  assertions run against `d248391^` (pre-fix `page.tsx`/`resumes.ts`):
  3 failed / 3 passed, failures match FE-MON011-A/C from
  `../mon-batch-1-fe-opus-review-verdict.json` (one directory up) exactly.
- **GREEN**:
  - `mon-batch-1-refix-PASS-AFTER-20260813T123400Z.log` — same file, committed
    fix, single-file run
    (`npx vitest run --maxWorkers=2
    src/app/dashboard/resume/__tests__/mon011-format-integrity-honesty.test.tsx`):
    6/6 passed. Matches FE-MON011-A/B/C from
    `../mon-batch-1-fe-opus-review-verdict.json` (one directory up).
  - `mon-batch-1-evidence-remediation-FE-PASSAFTER-20260813T125718Z.log` —
    FRESH, this remediation pass, current HEAD, widened by one file to match
    the literal MON-010+MON-011 scope (`page.test.tsx` +
    `mon011-format-integrity-honesty.test.tsx`): **2 files, 24 tests, 24
    passed, exit-status 0.**
  - `mon-batch-1-refix-ESLINT-TSC-20260813T123400Z.log` — eslint
    `--report-unused-disable-directives` exit 0; tsc filtered to the 3 changed
    files: 0 errors.

## Known gap — NOT fixed by this remediation pass (out of mechanical scope)

While producing the FRESH, complete FE capture called for by this task, a
**genuine code-level regression** was discovered — distinct from, and more
serious than, either evidence-hygiene finding this task was scoped to fix:

- **File**: `mon-batch-1-evidence-remediation-FE-ADJACENT-REGRESSION-DISCOVERY-20260813T125456Z.log`
  (captured 2026-08-13T12:54:56Z, current HEAD `d248391`).
- **Command**: the wider file set fd7cca0's own commit message named as
  passing together (`page.test.tsx`, `mon011-format-integrity-honesty.test.tsx`,
  `resume-mv-honesty.test.tsx`, `resume-hero-identity.test.tsx`,
  `resume-tailor-score-warning.test.tsx`, `resume-conversion-tooltip.test.tsx`).
- **Result**: 33 passed, **1 failed** —
  `resume-mv-honesty.test.tsx > MV-resume-studio-004 — format integrity
  reflects a real signal > is green when the version's formatHash matches the
  base, amber when it differs`. Expected text to match `/matches the base/i`;
  actual: `"Format preservation status is unknown for this version — …"`.
- **Root cause**: MV-resume-studio-004's fixture resumes set only `formatHash`
  (no `formatPreserved` field at all —
  `apps/web/src/__tests__/dashboard/resume-mv-honesty.test.tsx:55-69,112-129`).
  fd7cca0's commit message states this exact fixture's "pre-existing
  green/amber hash-comparison behaviour (no formatPreserved field in its
  fixtures) is untouched" — true when fd7cca0 landed (confirmed by
  `mon-010-011-fe-pass-after-20260813T122049Z.log`, captured against fd7cca0's
  own tree: this file passed 4/4). d248391 (FE-MON011-C) then gated the
  hash-comparison fallback behind an explicit `formatPreservationKnown` check
  specifically so a *missing* `formatPreserved` renders "unknown" instead of
  falling through to hash comparison — which silently breaks the exact
  guarantee fd7cca0's own commit message made, because d248391's targeted gate
  ("vitest on this file" — its own commit message) never re-ran this adjacent
  file to check.
- **Why it wasn't caught earlier**: both `../mon-batch-1-fe-opus-review-verdict.json`
  (round-2 FE review) and `../mon-batch-1-be-rereview-verdict.json` (this task's
  trigger, both one directory up from this file) verified d248391 only against
  `mon011-format-integrity-honesty.test.tsx` in isolation — never against the
  adjacent suite fd7cca0's own evidence had exercised.
- **Disposition**: this is a functional regression requiring a code change.
  This remediation pass is mechanical evidence-hygiene scope only (explicitly
  no production code or test-logic changes authorized) and does not fix it.
  Flagging for the orchestrator to open a follow-up MON-011 fix slice
  (round 3) before this batch is considered functionally closed — the
  evidence trail being clean (this file's own purpose) does not mean the
  round-2 FE fix is regression-free.

## Bottom line

Every citation in this index resolves to a real, complete file on disk, in
both `aether-wt-market-perf` and `aether-job-career-agent`, byte-identical
where the same filename appears in both. The one substantive problem
surfaced while producing this index (the MV-resume-studio-004 regression) is
called out above rather than concealed, papered over, or fixed out-of-scope.
