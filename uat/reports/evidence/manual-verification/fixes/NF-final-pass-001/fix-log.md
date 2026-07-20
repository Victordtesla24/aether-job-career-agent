# Fix log — NF-final-pass-001

**Finding:** JD Keyword Coverage panel leaks CamelCase concatenation artifacts
whose glued proper noun is non-Latin script or starts with a non-ASCII
uppercase (`İstanbulSalary`, `КиевLocation`, `МоскваSalary`, `İzmirLocation`,
`ΑθήναLocation` surfaced as top chips on prod).

**Severity:** LOW | **Screen:** cover-letter-studio | **Category:** defect

**Role:** fixer (medium tier), Aether MANUAL-VERIFICATION run. This agent
implements only — closure/verification is out of scope and performed by a
separate qa-adversary instance.

**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent` (main tree =
production @ `f491170`, not edited)

**Worktree:** `/tmp/claude-2000/-home-ubuntu/d977e239-103f-4ad2-a560-335ca7fb27b1/scratchpad/fixer-finalpass`
on branch `fix/nf-final-pass-001`, forked from `f491170414ef39e3f8ba4ca7106ad6f39c3ec3e8`
(HEAD verified before any edit — see below). Worktree removed after commit
(step 6 of pipeline).

---

## 1. Root-cause verification [VERIFIED-WITH-FRESH-EVIDENCE @ 2026-07-20T09:20Z]

Worktree created and HEAD confirmed:

```
$ git worktree add .../fixer-finalpass -b fix/nf-final-pass-001 f491170
$ git rev-parse HEAD
f491170414ef39e3f8ba4ca7106ad6f39c3ec3e8
$ git log -1 --oneline
f491170 Merge fix/nf-final-closure (NF-final-closure-001, NF-final-closure-002)
```

Live probe of `_CAMEL_HUMP_RE` / `_is_camel_concatenation_artifact` against
the exact 5 named gluings, at f491170, before any edit:

```
'İstanbulSalary' humps= ['Salary'] is_artifact= False
'КиевLocation'   humps= ['Location'] is_artifact= False
'МоскваSalary'   humps= ['Salary'] is_artifact= False
'İzmirLocation'  humps= ['Location'] is_artifact= False
'ΑθήναLocation'  humps= ['Location'] is_artifact= False
```

Confirms the qa-diagnosed root cause exactly: `_CAMEL_HUMP_RE =
re.compile(r"[A-Z](?:[A-Z]+(?=[A-Z]|$)|[a-z0-9]*)")` requires an **ASCII**
`[A-Z]` to start a hump. A Cyrillic/Greek capital, or Turkish `İ`
(U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE — confirmed
`'İ'.isupper() is True` in Python, per the orchestrator's Turkish-İ check),
never matches `[A-Z]`, so the non-Latin proper noun contributes NO hump
segment. The token collapses to a single hump (the ASCII label word alone),
and the `len(segments) < 2` early-return in `_is_camel_concatenation_artifact`
fires before the `_ARTIFACT_LABEL_WORDS` check ever runs — while the same
gluing with an ASCII proper noun (`SydneySalary`) is correctly caught, since
it produces 2 humps (`['Sydney', 'Salary']`).

Confirmed the only call site of `_CAMEL_HUMP_RE` in the codebase is
`apps/api/app/routers/cover_letters.py:259` (`_is_camel_concatenation_artifact`);
`grep -rn "_CAMEL_HUMP_RE" apps/api/` returned no other production call
sites, so no other consumer needed updating.

Also confirmed (matches the pipeline's explicit reverse-order and
preserved-case requirements):

```
Reverse order (label-first) — also NOT detected pre-fix:
'SalaryМосква'    humps= ['Salary']   is_artifact= False
'LocationКиев'    humps= ['Location'] is_artifact= False
'Salaryİstanbul'  humps= ['Salary']   is_artifact= False
'Locationİzmir'   humps= ['Location'] is_artifact= False
'LocationΑθήνα'   humps= ['Location'] is_artifact= False

Standalone (unglued) — correctly NOT flagged pre-fix, must stay that way:
'Киев'      humps= []    is_artifact= False
'İstanbul'  humps= []    is_artifact= False
'Zürich'    humps= ['Z'] is_artifact= False
```

## 2. Design (per orchestrator ruling)

Replaced the ASCII-only `_CAMEL_HUMP_RE` regex with `_camel_humps`, a plain
character walk using `ch.isupper()` / `ch.islower()` / `ch.isdigit()` —
Python's Unicode general-category case functions, correct for every cased
script in one shot (no per-alphabet enumeration). Algorithm mirrors the
retired regex's alternation + backtracking exactly (verified byte-identical
on ASCII — see §3):

- A hump starts at any uppercase char.
- If the immediately-following uppercase run reaches end-of-token, the WHOLE
  run is one hump (acronym at the end, e.g. `"API"` in `"GatewayAPI"`).
- Else if ≥1 more uppercase char follows, it's an acronym run followed by a
  new word — the LAST uppercase char of the run is handed back to start the
  next hump (e.g. `"SQLDatabase"` → `"SQL"` + `"Database"`).
- Otherwise it's an ordinary word hump: the starting uppercase char plus the
  following run of lowercase/digit chars (e.g. `"Manager"` in
  `"ManagerLocation"`).

Output contract (`list[str]` of segments) is unchanged, so
`_is_camel_concatenation_artifact` and every other consumer are untouched —
confirmed by grep (single call site, updated from `_CAMEL_HUMP_RE.findall(token)`
to `_camel_humps(token)`).

Caseless scripts (CJK, etc.) have no uppercase/lowercase distinction at all,
so a caseless character can neither start nor continue a hump — it is simply
skipped, exactly like punctuation, identically to how the retired regex
skipped non-`[A-Za-z0-9]` characters. This is why the class of defect
genuinely terminates here with this one structural change, per the
orchestrator's ruling — no further per-script enumeration is needed.

## 3. Characterization-test note

Per the orchestrator's explicit instruction, an ASCII/acronym-behavior
characterization table was captured **live from the actual `_CAMEL_HUMP_RE`
regex at f491170, before any code change** (not from memory/assumption) —
37 ASCII/acronym cases including the acronym-run edge cases the orchestrator
called out (`APIGateway`→`['API','Gateway']`, `PostgreSQL`→`['Postgre','SQL']`,
`OAuth2`→`['O','Auth2']`, `SQLDatabase`→`['SQL','Database']`,
`GatewayX`→`['Gateway','X']`, `XMLHttpRequest`→`['XML','Http','Request']`,
digits `A1B2C3`→`['A1','B2','C3']`, all-caps `NASA`/`ABC`, leading-lowercase
`iPhone`/`macOS`/`eBay`, empty string, single lowercase char).

The test (`test_ascii_camel_hump_segmentation_characterization_byte_identical`
in `apps/api/tests/test_cover006_camelcase.py`) resolves whichever segmenter
is currently wired into the module (`_camel_humps` if present, else falls
back to `_CAMEL_HUMP_RE.findall`), so the identical test file runs unmodified
both BEFORE and AFTER the fix — this is the byte-identical regression guard.
It passed both before (tautologically, since it was asserting the regex
against its own live-captured output) and after (proving the rewrite
reproduces every ASCII/acronym case exactly).

An independent scratch-script cross-check (`old_humps` regex vs. a draft of
the new character-walk, run over ~50 ASCII/acronym tokens plus the non-Latin
cases) showed **zero mismatches on any ASCII input** and, as expected, 4
intentional differences on already-flagged non-Latin/accented inputs
(`München`, `Zürich`, `MünchenLocation`, `LocationMünchen` now segment the
whole accented word instead of stopping at the first ASCII-invisible
character — this does not change `_is_camel_concatenation_artifact`'s
verdict for those specific tokens, which was already correct via the
`_WORD_RE` widening from NF-final-closure-001).

## 4. Tests — fail-before / pass-after

All commands run under `flock /tmp/aether-pytest.lock`, `DATABASE_URL` /
`DATABASE_URL_TEST` grep-extracted from the repo-root `.env` (never sourced,
never a prod DSN — schema `aether_test` on host `db-fdc4e11da...`, matching
the EXIT-G06-FINAL-serialized.md recipe), `AETHER_CREDENTIAL_KEY`
grep-extracted (never logged in full — first 8 chars only: `X5-HScT0…`),
`AETHER_ASYNC_GENERATION=false`.

### Targeted file — fail-before @ f491170 (2026-07-20T09:23:32Z)

```
$ flock /tmp/aether-pytest.lock python3 -m pytest -q -p no:xdist -o addopts="" \
    tests/test_cover006_camelcase.py
...
11 failed, 87 passed, 6 warnings in 0.70s
```

Exactly the 11 new repro tests failed (5 named gluings +
5 reverse-order variants + 1 end-to-end keyword-panel repro); all other 87
tests passed, including:
- all 45 pre-existing camelcase tests (unmodified, untouched) — GREEN
- the 3 new standalone-preserved-case tests (Киев/İstanbul/Zürich unglued) — GREEN
- all 38 new ASCII characterization cases — GREEN

Full log: `/tmp/nf-final-pass-001-baseline.log` (this VM, this run).

### Targeted file — pass-after @ `9e7befb` (2026-07-20T09:29:0xZ)

```
$ flock /tmp/aether-pytest.lock python3 -m pytest -q -p no:xdist -o addopts="" \
    tests/test_cover006_camelcase.py
...
98 passed, 6 warnings in 0.51s
```

All 98 tests (45 pre-existing + 53 new) pass. Full log:
`/tmp/nf-final-pass-001-postfix.log`.

### Broader cover-letter/clstudio batch — pass-after @ `9e7befb`

Per pipeline step 4, ran the `test_*cover*`/`clstudio` batch (12 files
matched by the literal glob, incl. 2 whose filename contains "...dis**cover**y..."
as a substring — run anyway for maximum coverage, no exclusions):

```
tests/test_cover006_camelcase.py tests/test_cover_letter_agent.py
tests/test_cover_letter_studio.py tests/test_gap_p5_cover.py
tests/test_gap_p5_cover_voice.py tests/test_gap_p6_cover_fabrication.py
tests/test_gap_p6_cover_prompt_hardening.py tests/test_gap_p7_discovery_001.py
tests/test_job_discovery.py tests/test_mv_clstudio_003.py
tests/test_mv_clstudio_j_residuals.py tests/test_mv_cluster_a_cover_letter.py
...
219 passed, 6 warnings in 259.05s (0:04:19)
```

Zero regressions. Full log: `/tmp/nf-final-pass-001-batch.log`.

## 5. Diff summary

```
 apps/api/app/routers/cover_letters.py     |  73 +++++++++-
 apps/api/tests/test_cover006_camelcase.py | 233 ++++++++++++++++++++++++++++++
 2 files changed, 303 insertions(+), 3 deletions(-)
```

Production code change is a single-function replacement in
`apps/api/app/routers/cover_letters.py`:
- Removed `_CAMEL_HUMP_RE` (ASCII-only regex constant).
- Added `_camel_humps(token: str) -> list[str]` (Unicode case-function
  character walk, ~35 lines incl. comments).
- Updated the single call site in `_is_camel_concatenation_artifact`
  (`_CAMEL_HUMP_RE.findall(token)` → `_camel_humps(token)`).
- No other production files touched. No scope creep — `_WORD_RE`,
  `_ARTIFACT_LABEL_WORDS`, `_ARTIFACT_SPLIT_WORDS`,
  `_MIXED_CASE_TECH_ALLOWLIST`, `_skill_score`, `_is_semantic_keyword` all
  unchanged.

Test change is additive-only in `apps/api/tests/test_cover006_camelcase.py`
(new sections appended after the existing NF-final-closure-001 preserved-case
tests; nothing removed or modified in the existing 45 tests).

## 6. Commit

```
commit 9e7befb0367baa5b45aaa977f80028f5c3a15a16 (fix/nf-final-pass-001)
Author: Vikram. <melbvicduque@gmail.com>
Date:   Mon Jul 20 09:29:15 2026 +0000

    fix(NF-final-pass-001): unicode case-based CamelCase segmentation (non-Latin proper-noun gluings)
```

Branch `fix/nf-final-pass-001`, parent `f491170`. No `--no-verify`, no merge,
no push (per pipeline — deployment/merge is out of scope for this fixer
role).

## 7. Epistemic status

All claims above are [VERIFIED-WITH-FRESH-EVIDENCE] — captured this run
(2026-07-20T09:2x:xxZ, this VM, this worktree) via direct execution of the
actual regex/function against the actual repo code, and via actual pytest
runs with real output logs (`/tmp/nf-final-pass-001-{baseline,postfix,batch}.log`).
No claim in this log is [INFERRED] or [ASSUMED-PENDING-PROBE] beyond the
original finding's own root-cause attribution, which was independently
re-verified fresh (§1) rather than taken on testimony.

This fixer did not review, deploy, or verify (production/closure) its own
fix — that is qa-adversary's role, out of scope here.
