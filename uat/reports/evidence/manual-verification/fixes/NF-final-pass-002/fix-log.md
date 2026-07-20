# Fix log — NF-final-pass-002

**Finding:** JD Keyword Coverage panel leaks CamelCase concatenation
artifacts whose glued proper noun is a CASELESS script (CJK/Kana/Hangul/
Arabic/Hebrew/Devanagari/Thai) — `القاهرةSalary`, `बईLocation`, `ソウルSalary`,
`東京Salary` observed as top chips on prod (closure-qa novel adversarial
sweep, `CLOSURE-REPORT.json`).

**Severity:** LOW | **Screen:** cover-letter-studio | **Category:** defect

**Role:** fixer (medium tier), Aether MANUAL-VERIFICATION run. This agent
implements only — closure/verification is out of scope and performed by a
separate qa-adversary instance. No self-approval.

**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent` (main tree =
production @ `c158729`, not edited)

**Worktree:**
`/tmp/claude-2000/-home-ubuntu/d977e239-103f-4ad2-a560-335ca7fb27b1/scratchpad/fixer-caseless`
on branch `fix/nf-final-pass-002`, forked from
`c158729818cecc0e4788b75bbbb6b6481143bd96` (HEAD verified before any edit —
see below). Worktree removed after commit (step 6 of pipeline); gitignored
`.env` copied in for conftest, removed before worktree removal.

---

## 1. Root-cause verification [VERIFIED-WITH-FRESH-EVIDENCE @ 2026-07-20T12:48Z]

Worktree created and HEAD confirmed:

```
$ git worktree add .../fixer-caseless -b fix/nf-final-pass-002 c158729
$ git rev-parse HEAD
c158729818cecc0e4788b75bbbb6b6481143bd96
$ git log -1 --oneline
c158729 Merge fix/nf-final-pass-001 (NF-final-pass-001)
```

Live probe of `_camel_humps` / `_is_camel_concatenation_artifact` against
the 4 named gluings + my own adversarial variants, at c158729, before any
edit:

```
'القاهرةSalary' -> humps= ['Salary']   is_artifact= False
'बईLocation'    -> humps= ['Location'] is_artifact= False
'ソウルSalary'   -> humps= ['Salary']   is_artifact= False
'東京Salary'     -> humps= ['Salary']   is_artifact= False
'Salaryソウル'   -> humps= ['Salary']   is_artifact= False   (reverse/label-first, verified pre-fix)
'東京'           -> humps= []          is_artifact= False   (standalone, correctly unflagged)
'Salary'        -> humps= ['Salary']   is_artifact= False   (standalone label, correctly unflagged)
'Salaries'      -> humps= ['Salaries'] is_artifact= False   (distinct word, exact-match safe)
'Salary/Benefits' -> humps= ['Salary','Benefits'] is_artifact= True (already caught, len>=2 path)
```

Confirms the qa-diagnosed root cause exactly: caseless characters (CJK,
Kana, Hangul, Arabic, Hebrew, Devanagari, Thai, ...) have no upper/lower
distinction in Python's Unicode case functions
(`ch.isupper()`/`ch.islower()`), so `_camel_humps` skips them exactly like
punctuation — a caseless proper noun contributes NO hump segment. Gluing one
to an ASCII structural label leaves exactly ONE segment (the label alone),
so the `len(segments) < 2` early-return in `_is_camel_concatenation_artifact`
fires before the `_ARTIFACT_LABEL_WORDS` check ever runs. This is the THIRD
distinct path to the same historical early-return bug:

1. NF-final-closure-001 — severed unicode fragments (`_WORD_RE` too narrow,
   fixed by widening the tokenizer).
2. NF-final-pass-001 — non-Latin CASED proper nouns (`_CAMEL_HUMP_RE` was
   ASCII-only, fixed by replacing it with the Unicode case-function
   `_camel_humps`).
3. NF-final-pass-002 (this fix) — caseless-script proper nouns structurally
   cannot start/continue a hump under ANY case-function-based segmenter, so
   they always collapse to zero segments of their own, regardless of how
   correct the segmenter is for cased scripts.

`grep -rn "_is_camel_concatenation_artifact\|_camel_humps" apps/api/`
confirms `apps/api/app/routers/cover_letters.py` is the sole
definition/call site; no other consumer needed updating.

## 2. Design (per orchestrator ruling)

**Orchestrator ruling:** kill the early-return pattern itself instead of
adding a fourth script-family branch — when segmentation yields FEWER than
2 segments, do not unconditionally return `False`. New rule: if the token
has exactly one cased segment AND that segment is in the boilerplate-label
set (`_ARTIFACT_LABEL_WORDS`) AND the token contains material beyond that
segment (`token != segment`), classify as ARTIFACT (unless the whole token
is allowlisted). A standalone label token (`token == segment`) keeps its
current behavior. Zero segments → keep current behavior.

Implemented exactly as specified, in `_is_camel_concatenation_artifact`:

```python
segments = _camel_humps(token)
if len(segments) < 2:
    if len(segments) == 1:
        solo = segments[0]
        if token != solo and solo.lower() in _ARTIFACT_LABEL_WORDS:
            return True
    return False
```

The `_MIXED_CASE_TECH_ALLOWLIST` check already runs FIRST (unchanged,
line above the segmentation), so an allowlisted whole-token match is
unaffected regardless of segment count.

### False-positive analysis (worked through BEFORE coding, per instruction)

- **Plural/possessive forms** (`Salaries`): segment equality against
  `_ARTIFACT_LABEL_WORDS` is exact-string (`solo.lower() in
  _ARTIFACT_LABEL_WORDS`), and `"salaries" != "salary"`, so plurals are
  structurally excluded — verified live (`'Salaries' -> humps=['Salaries'],
  is_artifact=False`) and locked in by
  `test_standalone_label_word_behavior_unchanged`.

- **Hyphen/slash continuations** (`_WORD_RE` allows `[+#./-]` mid-token, so
  `"Salary/Benefits"` and `"Salary-Location"` tokenize as ONE token each):
  traced `_camel_humps` on both — the punctuation character is skipped
  exactly like a caseless character, but there IS cased material on BOTH
  sides, so each yields 2 segments (`['Salary','Benefits']`,
  `['Salary','Location']`) and was **already** caught by the pre-existing
  `len(segments) >= 2` path (both segments are boilerplate/label words).
  These never reach the new `len(segments) == 1` branch at all — confirmed
  by `test_hyphen_slash_continuation_tokens_unaffected_by_single_segment_rule`,
  which asserts the exact segment lists in addition to the artifact verdict.

- **Legit product names with a single label segment + extra chars**
  (the orchestrator's own example: `"eSalary"`-style names): surveyed the
  existing `_MIXED_CASE_TECH_ALLOWLIST` (21 entries at the time of this
  fix — javascript, typescript, postgresql, graphql, mongodb, nodejs,
  node.js, github, gitlab, devops, oauth2, oauth, javafx, jquery, mysql,
  dynamodb, cloudformation, websocket, elasticsearch, log4j2,
  webassembly, slideshare, sharepoint, geolocation). None of these, nor
  any product I could identify with reasonable confidence, matches the
  lowercase-ASCII-prefix + lone-label-segment shape (`eSalary`, `iLocation`,
  `eShare`, `eBenefits`). Per the epistemic-discipline rule against guessing
  when unsure, **no new allowlist entries were added** — these tokens are
  intentionally treated as artifacts. `_MIXED_CASE_TECH_ALLOWLIST` is
  checked FIRST and remains the designed escape hatch: if a real product
  is later identified, adding it there requires no further code change.
  Decision locked in by
  `test_single_label_segment_with_lowercase_ascii_prefix_or_suffix_is_flagged`.

- **Single-segment gluings where the lone segment is NOT a label word**
  (e.g. `"東京Manager"`, `"東京Engineer"` — "manager"/"engineer" live only in
  the broader `_ARTIFACT_SPLIT_WORDS`, not the narrower
  `_ARTIFACT_LABEL_WORDS`): deliberately left unflagged. This mirrors the
  pre-existing asymmetry in the `len(segments) >= 2` path (ANY-segment-
  is-a-LABEL vs. ALL-segments-are-boilerplate) and stays within the
  orchestrator's exact ruling text (which names `_ARTIFACT_LABEL_WORDS`
  specifically, not the broader set) — widening to
  `_ARTIFACT_SPLIT_WORDS` for the single-segment case would be scope creep
  beyond the ruling and risk new false positives on real compound terms.
  Locked in by
  `test_single_non_label_segment_with_caseless_prefix_is_not_flagged`.

## 3. Tests — fail-before / pass-after

All commands run under `flock /tmp/aether-pytest.lock`, `DATABASE_URL` /
`DATABASE_URL_TEST` grep-extracted from the repo-root `.env` (never
sourced, never a prod DSN — schema `aether_test` on host
`db-fdc4e11da...`, matching the `EXIT-G06-FINAL-serialized.md` recipe),
`AETHER_CREDENTIAL_KEY` grep-extracted (never logged in full — first 8
chars only: `X5-HScT0…`), `AETHER_ASYNC_GENERATION=false`.

### Targeted file — fail-before @ `c158729` (2026-07-20T12:5x:xxZ)

```
$ flock /tmp/aether-pytest.lock python3 -m pytest -q -p no:xdist -o addopts="" \
    tests/test_cover006_camelcase.py
...
13 failed, 106 passed, 6 warnings in 0.74s
```

Exactly the 13 new tests that assert the CURRENT (bugged) behavior must
change failed:
- 4 named-gluing detection tests (`القاهرةSalary`, `बईLocation`, `ソウルSalary`,
  `東京Salary`)
- 4 reverse/label-first order tests (my own design)
- 3 Thai/Hebrew variant tests (my own design)
- 1 end-to-end `_keyword_coverage` repro
- 1 false-positive-decision characterization test (`eSalary`-style now
  flagged by design)

All other 106 tests (98 pre-existing + 8 new characterization/preserved-
behavior tests that assert UNCHANGED behavior) already passed pre-fix, as
expected — they test behavior the fix must NOT change.

Full log: `targeted-fail-before.log` (this directory).

### Targeted file — pass-after @ `9ceb92f` (2026-07-20T12:5x:xxZ)

```
$ flock /tmp/aether-pytest.lock python3 -m pytest -q -p no:xdist -o addopts="" \
    tests/test_cover006_camelcase.py
...
119 passed, 6 warnings in 0.61s
```

All 119 tests pass (98 pre-existing, byte-identical + 21 new). Full log:
`targeted-pass-after.log`.

### Broader cover-letter/clstudio batch — pass-after @ `9ceb92f`

Per pipeline step 4, ran the `test_*cover*`/`clstudio` batch (12 files):

```
tests/test_cover006_camelcase.py tests/test_cover_letter_agent.py
tests/test_cover_letter_studio.py tests/test_gap_p5_cover.py
tests/test_gap_p5_cover_voice.py tests/test_gap_p6_cover_fabrication.py
tests/test_gap_p6_cover_prompt_hardening.py tests/test_gap_p7_discovery_001.py
tests/test_job_discovery.py tests/test_mv_clstudio_003.py
tests/test_mv_clstudio_j_residuals.py tests/test_mv_cluster_a_cover_letter.py
...
240 passed, 6 warnings in 263.25s (0:04:23)
```

Zero regressions. Full log: `batch-pass-after.log`.

## 4. Diff summary

```
 apps/api/app/routers/cover_letters.py     |  29 ++++
 apps/api/tests/test_cover006_camelcase.py | 254 ++++++++++++++++++++++++++++++
 2 files changed, 283 insertions(+)
```

Production code change is a single-branch addition inside
`_is_camel_concatenation_artifact` in
`apps/api/app/routers/cover_letters.py` (see `prod-code-diff.patch`, this
directory, for the exact diff `c158729..9ceb92f`):
- Added the `len(segments) == 1` branch described in §2 (6 lines of logic
  + docstring).
- No other production code touched — `_camel_humps`, `_WORD_RE`,
  `_ARTIFACT_LABEL_WORDS`, `_ARTIFACT_SPLIT_WORDS`,
  `_MIXED_CASE_TECH_ALLOWLIST`, `_skill_score`, `_is_semantic_keyword` all
  unchanged (confirmed by the diff containing exactly one hunk in one
  function).

Test change is additive-only in
`apps/api/tests/test_cover006_camelcase.py` (new section appended after
the existing NF-final-pass-001 ASCII-characterization tests; nothing
removed or modified in the existing 98 tests).

## 5. Commit

```
commit 9ceb92ff58a42154ee18109699131693f969f721 (fix/nf-final-pass-002)
Author: Vikram. <melbvicduque@gmail.com>
Date:   Mon Jul 20 12:59:22 2026 +0000

    fix(NF-final-pass-002): single-label-segment gluings are artifacts (caseless-script proper nouns; closes the len<2 early-return family)
```

Branch `fix/nf-final-pass-002`, parent `c158729`. No `--no-verify`, no
merge, no push (per pipeline — deployment/merge is out of scope for this
fixer role). Worktree removed after this log was written; `.env` copy
deleted from the worktree before removal.

## 6. Epistemic status

All claims above are [VERIFIED-WITH-FRESH-EVIDENCE] — captured this run
(2026-07-20T12:4x–12:5xZ, this VM, this worktree) via direct execution of
the actual function against the actual repo code (both pre- and post-fix),
and via actual pytest runs with real output logs (`targeted-fail-before.log`,
`targeted-pass-after.log`, `batch-pass-after.log`, this directory). The
false-positive survey of `_MIXED_CASE_TECH_ALLOWLIST` (§2) is
[VERIFIED-WITH-FRESH-EVIDENCE] as a factual inventory (21 entries read
directly from the file at fix time); the JUDGMENT not to add new
allowlist entries for hypothetical products is a documented decision, not
a verified-real/verified-fake claim about those products' existence — it
is flagged as such rather than asserted as fact.

This fixer did not review, deploy, or verify (production/closure) its own
fix — that is qa-adversary's role, out of scope here.
