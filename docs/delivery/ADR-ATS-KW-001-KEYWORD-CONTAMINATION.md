# ADR-ATS-KW-001 — the posting's LOCATION was scored as a required résumé keyword

- **Status:** ACCEPTED (implementation landed; awaiting independent review — the author does not approve his own work)
- **Date:** 2026-08-04
- **Finding:** ATS-KW-001, raised by the reviewer of `28d6393`
- **Governance:** `docs/delivery/GOLD-MASTER-V2-GOVERNANCE.md` GOV-021 — the §5.2 "ATS ≥ 85" ceiling was measured through this defect, so G-C cannot be adjudicated until the five-job probe is re-run against the fixed engine.
- **Code:** `apps/api/app/services/ats_engine.py`, `apps/api/app/services/resume_tailor.py`
- **Tests:** `apps/api/tests/test_gm2s15_ats_kw001_location_keyword.py` (defect, written by test-author), `apps/api/tests/test_ats_kw001_geography_guards.py` (fix guards)

---

## 1. Mechanism — how the location actually got in

**It is not a separate field, and it is not injected.** The location enters as ordinary
job-description prose, and nothing downstream ever knew it was geography.

The text handed to the engine is built by
`apps/api/app/services/fit_evidence.py:38-56`:

```
job_evidence_text(job) == f"{job['title']} {job['description']} {requirements}"
```

There is no `location` term in that expression — the structured `location` column is
never concatenated. The city arrives because postings *state* it in the title and body:
`"Senior Backend Engineer — Sydney."`, `"Location: Melbourne."`, `"must be based in
Melbourne, VIC"`. From there:

1. `_content_tokens` keeps `sydney` — it is ≥ 2 chars, is not in `_STOPWORDS` (which
   contains no geography at all), and `_is_noise_token` only recognises URL/gibberish
   shapes.
2. `_extract_keywords` ranks the surviving tokens by TF-IDF and takes the top
   `_MAX_KEYWORDS` (40) **as the required-keyword set, with no notion of what kind of
   word each one is**. That is the root cause: the function has no concept of "skill",
   so any noun in the posting is a skill.
3. `_keyword_match` then divides matched-by-résumé over that set, and puts the rest in
   `ATSScore.missing_keywords` — the list the user is shown as their gap.

Measured on the suite's own probe pair (`JD_PYTHON` / `RESUME_MATCHING` in
`tests/test_ats_engine.py`), 2026-08-04:

```
extracted keywords (18): engineer automated aws backend cd ci docker fastapi kubernetes
                         microservices pipelines postgresql pytest python redis senior
                         sydney testing
overall=87.74 kw=94.44 sem=74.9077 exp=100.0 path=local
missing_keywords = ['sydney']
```

17 of 18 matched. The **sole** miss was the city. Every posting carries a location, so
every candidate was docked on every posting, and the product's own gap list instructed
them to write a city name into their résumé — the keyword-stuffing this product exists
to refuse.

## 2. Decision — remove geography from the keyword set; do NOT add a location score

**Location fit is already scored separately, and earlier.**
`app/services/discovery/relevance.py:87-134` computes `location_score()` (2 = AU/NZ/APAC,
1 = genuinely remote, 0 = not applicable) and `is_applicable()` gates every posting on it
*before* the posting can be ATS-scored at all. Counting the location again inside
`keyword_match` was therefore double-counting on top of being wrong. **No replacement
signal is added here**, and no new component is introduced — adding a fourth component
would necessarily change the `overall` formula, which is exactly the weight-fiddling this
fix must not do.

**No weight, threshold or cap moved.** `_WEIGHT_KEYWORD`/`_WEIGHT_SEMANTIC`/
`_WEIGHT_EXPERIENCE` (0.4/0.4/0.2), `REVIEW_THRESHOLD` (60.0), `_MAX_KEYWORDS` (40) and
`_DEGRADED_SEMANTIC_SCORE` (50.0) are byte-identical to HEAD, and
`test_10_the_fix_moved_no_weight_and_no_threshold` pins all five so a later "make the
number nicer" edit fails loudly.

## 3. Approach — positional evidence, with an every-occurrence rule

A new `_geographic_tokens(job_description)` decides which tokens are the *posting's
geography*; `_extract_keywords` drops them from the token stream **before** TF-IDF, so
geography neither scores nor consumes one of the 40 keyword slots.

**The rule: a token is geography iff EVERY one of its occurrences in the posting falls
inside a detected geographic span.** Spans come from the signals below (signal 0 is the one
exception to the every-occurrence rule, and is exempt precisely because it contains no
place *names*, only the vocabulary for talking about place — words that are never a skill
anywhere). The bare noun **"location"** was confirmed live in production: it ranked 25th of
40 required keywords on job `ced2ed2e5e5a46d9bfa04f625` and reached the candidate's gap
list as a permanent, unclosable miss (`TAILORING-EFFICACY-PROBE.md` §7).

| # | Signal | Example | Why it is safe |
|---|--------|---------|----------------|
| 0 | Location **vocabulary** — the words for *stating where*, not place names | `location`, `relocation`, `suburb`, `postcode`, `commute`, `workplace` | None can be a skill in any context, so no positional evidence is needed. `office` (MS Office), `state` (state management), `region` (an AWS region) and the work-mode words `remote`/`hybrid` are deliberately **excluded** |
| 1 | Explicit location **label** | `Location: Docklands` | Requires a real separator, so the word "location" in prose opens nothing. `\b` keeps `Relocation:` from matching as `location:` |
| 2 | Closed set of prose **carriers** | `based in X`, `relocate to X`, `our office in X`, `work from X`, `reside in X` | Each carrier can only introduce a place; it is a lexical fact, not a guess about the following word |
| 3 | Geographic **vocabulary** | `Sydney`, `Australia`, `New South Wales`, `Melbourne-based` | Curated; see §5 for what is deliberately excluded |

plus **chain expansion**, so the unrecognisable parts of a multi-part location join the
part that is recognisable:

- a weak region abbreviation (`VIC`, `SA`, `NSW`, `CA`, `MS`) joins a confirmed place
  across a comma *or* plain whitespace — `Adelaide, SA`, `Sydney NSW`. These abbreviations
  never count on their own; `MS` is Microsoft, `CA` a certificate authority, `ACT` an
  English verb.
- any other token joins only across an explicit separator **and** only when *that chain*
  already holds two confirmed geographic elements. This is what recovers a suburb no
  gazetteer will ever list (`Truganina, Melbourne, VIC`) without walking a comma list that
  merely happens to contain a place name (`Georgia, Helvetica and Inter`).

**The label signal has two forms, and the reason matters.** The JD the engine actually
receives is `job_evidence_text` = `title + " " + description + " " + requirements` — *one
line*, with no newline after the title. A `^`-anchored label regex therefore fires on the
multi-line postings used in tests and **never on the real production shape**: measured
2026-08-04 on an Adzuna-shaped row, `Location: Phoenix, AZ` sat mid-line and was missed
entirely. Line-anchored labels accept a colon or a dash; mid-line labels require a colon,
because a mid-line dash is ordinary prose punctuation (`the office - a converted warehouse
- is great`) and would otherwise open a span over it. `test_13` builds its JD through
`job_evidence_text` rather than hand-writing a string, so this cannot silently regress.

Signals 1 and 2 are evidence about a **position in the text**, not about a word. That is
what makes the every-occurrence rule bite: a term that is both a place and a technology
keeps its keyword status the moment it also appears outside every span — which is exactly
what a skills list is. `Location: Phoenix, AZ` + `Required skills: Elixir, Phoenix, Ecto`
keeps `phoenix` and drops `az`.

**Vocabulary precision, measured.** 482 strong tokens, 69 weak abbreviations, 94 phrases.
Audited against 159 common technology/tool/platform terms (languages, frameworks, data
stack, cloud, CI, observability, BI): ~~**zero collisions** with either the strong
vocabulary or the weak abbreviations~~, and all twelve deliberate omissions confirmed
absent. Artifact:
`uat/reports/evidence/models-live/ATS-KW-001/vocabulary-collision-audit-*.log`.

> **CORRECTION (2026-08-04, R-02).** The struck claim is **FALSE**, and this document
> contradicted it two sections later: §5 failure mode 1 already named `Georgia` the
> typeface as a live collision, and `test_2` in the guard file records the same thing as a
> KNOWN LIMITATION. "Zero collisions" was true only of *the 159 terms in that one audit
> list* — a list which contains no editor (`monaco`), no embedded database (`berkeley`),
> no kernel (`darwin`), no typeface (`georgia`), no tool brand (`milwaukee`) and no
> ordinary English verb (`polish`), all six of which were measured as unconditional
> deletions on 9a338c8. The number describes the audit's coverage, not the vocabulary's
> precision, and it must not be read as the latter. **No replacement "zero" is claimed
> here**: the residual collisions that remain are enumerated by name in
> `ADR-R01-GEOGRAPHIC-SPAN-BOUNDING.md` §7. See that ADR for the disqualifying rule the
> vocabulary is now curated under (64 entries removed, 482 → 418) and for the mechanism
> that makes a residual collision survivable rather than fatal.

**Never-empty guard.** If filtering would remove *every* content token, the unfiltered set
is kept and a WARNING is logged. An empty keyword set makes `_keyword_match` return a flat
`0.0` for every résumé alike — a silent, uniform, unexplained zero. Refusing to emit it is
consistent with the module's existing honest-degradation posture.

## 3a. The SECOND location — the same defect gated tailoring itself

`resume_tailor.py` derives its own "JD keyword" set from the same tokenizer, in two
places, and neither knew about geography either:

- `select_bullets_to_tailor` (`jd_key_stems`) — ranks which bullets to rewrite by JD
  overlap, so a bullet naming the city ranked spuriously high;
- **`_validate`'s ATS non-regression floor** (`jd_terms`) — rejects a rewrite that drops
  a JD keyword the original bullet already covered.

The second one has teeth. For a bullet the candidate truthfully owns —
`"Led the Melbourne data platform team, building Python and Spark pipelines."` — the floor
**vetoed any rewrite that did not carry the city forward**. Measured at HEAD:

```
floor hits, rewrite drops only the city : {'melbourne'}   -> rewrite REJECTED
floor hits, rewrite drops Python/Spark  : {'python','spark'} -> rewrite REJECTED (correct)
```

That is tailoring being blocked to defend a keyword that is not a skill. Both sites now
call a single `jd_keyword_terms()` helper that subtracts `_geographic_tokens`. After:

```
floor hits, rewrite drops only the city : set()            -> rewrite ALLOWED
floor hits, rewrite drops Python/Spark  : {'python','spark'} -> rewrite REJECTED (unchanged)
```

The floor's stated purpose is to guarantee `tailoredATSScore >= baselineATSScore`. Since
the engine no longer scores geography, keeping geography in the floor constrained rewrites
for **zero** score benefit — removing it restores the floor's agreement with the engine it
defends. **The anti-fabrication and JD-echo guards are untouched**: they are separate,
earlier branches of the same `_validate` chain and were not read, moved or relaxed. This
matters for GOV-021: some of the "unsatisfiable gap" pressure the ≥ 85 ruling rests on was
this floor refusing rewrites over a city name.

## 4. Measured before / after

Probe pair `JD_PYTHON` / `RESUME_MATCHING` (`tests/test_ats_engine.py`), local embedding
path, 2026-08-04:

| | before | after |
|---|---|---|
| `keyword_match` | **94.44** | **100.0** |
| `overall` | **87.74** | **89.96** |
| `semantic_similarity` | 74.9077 | 74.9077 (unchanged) |
| `experience_gap` | 100.0 | 100.0 (unchanged) |
| `semantic_path` | local | local |
| `missing_keywords` | `['sydney']` | `[]` |

89.96 is precisely the arithmetic ceiling `test_perfect_keyword_overlap_scores_high`
already documents for this pair (`0.4*100 + 0.4*74.91 + 0.2*100`). The score moved because
a non-skill stopped being counted as a skill, and for no other reason.

**The GOV-021 confound, quantified.** On a realistic Melbourne posting plus a strong
résumé, run through `clean_gap_keywords` → `split_gap_keywords` (the exact pair that
produces the loop's `unreachable_keywords`):

| | before | after |
|---|---|---|
| `keyword_match` | 61.11 | 76.92 |
| cleaned gap list | `melbourne, vic, australia, exposure, location, terraform` | `exposure, terraform` |
| **UNSATISFIABLE (unreachable) count** | **6** | **2** |

**Four of the six "unsatisfiable gap keywords" were this defect** — three geography tokens
plus the bare noun "location". None of them can ever be evidenced by a candidate's corpus,
so each one permanently inflated the unreachable count that GOV-015-WC's "≥ 85 is not
honestly reachable" conclusion rests on. This does not by itself settle whether ≥ 85 is
reachable — the remaining two (`exposure`, `terraform`) are real, and `exposure` is
boilerplate of class (B) below — but it confirms the ceiling was measured through the
defect and must be re-measured. Artifact:
`uat/reports/evidence/models-live/ATS-KW-001/gov021-gap-count-*.log`.

## 5. Failure modes — stated honestly

> **SUPERSEDED IN PART (2026-08-04) — see `ADR-R01-GEOGRAPHIC-SPAN-BOUNDING.md`.**
> Failure modes 1 and 3 below both understate their severity, and mode 3 states the
> opposite of what was measured:
>
> * **mode 1** calls the residual "*under-demand* — the engine asks for one keyword
>   fewer — which never fabricates a gap and never docks a candidate". True as far as it
>   goes, and it misses the consequence that matters: a requirement absent from the
>   keyword set cannot be reported missing from it either. Deleting requirements does not
>   merely ask for less, it **fabricates a perfect match**. Measured (R-01): a résumé with
>   none of the posting's stack scored `keyword_match = 100.0`, `missing_keywords = []`.
> * **mode 3** claims carrier over-capture is "largely self-correcting: an over-captured
>   skill almost always also appears outside the span and is therefore kept". In the
>   production JD shape it self-corrects **never**: `job_evidence_text` joins the
>   requirements array with a bare space, each item usually appears exactly once, so a
>   single carrier phrase in the first item took the entire remaining stack, every token
>   of which occurred only inside the span. The "80 chars max" was not a bound on a
>   location — it was a bound on a sentence, and the production JD has no sentences.
>
> Both are fixed. The bound is now a token walk, not a character window; the vocabulary is
> curated under a stated disqualifying rule; and the every-occurrence rule is no longer
> vacuous for vocabulary tokens.

1. **A vocabulary token used as a technology is still dropped.** The every-occurrence rule
   protects a homonym only when the geographic evidence is *positional*. A token in the
   vocabulary is marked wherever it appears, so for those the protection is the curation of
   the list, not the rule. Mitigation: city names that are also well-known technologies —
   `phoenix`, `aurora`, `sierra`, `ventura`, `monterey`, `catalina`, `hudson`, `atlas`,
   `athena` — are **deliberately absent** from the vocabulary, and `english` is absent
   because it is a language competency here. They are still caught when a posting states
   them geographically (signals 1/2). The residual case is a vocabulary city used as a
   product name (`Georgia` the typeface); the error direction is *under-demand* — the
   engine asks for one keyword fewer — which never fabricates a gap and never docks a
   candidate.
2. **Recall is bounded by the vocabulary for bare prose.** A small town stated with no
   label, no carrier and no chain (`"you will join our Truganina crew"`) is not detected.
   Direction of error: the old behaviour, for that one token only.
3. **Carrier over-capture.** A captured location value runs to the first clause boundary
   (80 chars max). Over-capturing is largely self-correcting: an over-captured skill almost
   always also appears outside the span and is therefore kept.
4. **No title-suffix rule.** An earlier draft treated the trailing segment of the title
   line (`"Data Engineer — Sydney"`) as geographic. It was **removed**: it fires identically
   on `"Data Engineer — Snowflake"`, and the JD text in production is
   `title + " " + description` with no newline between them, so "the first line" is not
   reliably the title. The vocabulary covers the realistic version of this case.
5. **Work-mode words still count as skills.** `remote`, `hybrid`, `onsite` and `office` are
   left in the keyword set. They are the same class of non-skill, but `remote` is a real
   value of this product's own `location` column and `office` is a genuine product name
   (MS Office), so suppressing them needs its own finding rather than riding along here.
6. **Freed keyword slots.** On a JD with more than 40 unique content tokens, removing
   geography lets the next-ranked tokens into the top 40. Observed on a realistic posting:
   dropping `melbourne`/`australia`/`docklands` admitted `office`/`operate`/`options`.
   Given defect (C) below, those replacements are no better than what they replaced.

## 6. Other contamination of the required-keyword set (found, NOT fixed here)

Item 3 of the task asked for the *scope* of the contamination, not just this instance.
Probe: a realistic 66-unique-token posting (Atlassian / Senior Data Engineer / Melbourne).

**(A) Company / employer identity.** `atlassian` ranked **first** (TF 3), `ltd` also
entered. An employer's own name is not a candidate skill, and it ranks high precisely
because postings repeat it.

**(B) Benefits, culture and boilerplate.** `allowance`, `catered`, `lunches`, `generous`,
`competitive`, `annual`, `leave`, `days`, `options`, `crew`, `impact`, `mission-driven`,
`fast-growing`, `equal`, `employer`, `agencies`, `click`, `now`, `cv`, `need`, `about`,
`make`, `model`, `head`, `hybrid`, `full-time`. `_STOPWORDS` catches some recruiting
boilerplate (`salary`, `benefits`, `opportunity`) but the coverage is incidental.
`tailoring_loop.clean_gap_keywords` catches more of it (`about`, `make`) — but that runs
**downstream, on the display list only**, so it never affects the score.

**(C) The ranking is alphabetical past the first few terms — and it truncates real
skills.** `TfidfVectorizer` is fitted on a **single document**, so IDF is a constant for
every term present and the ranking degenerates to term-frequency with an alphabetical
tie-break. Almost every JD term appears once, so beyond the handful of repeated words the
"top 40 keywords" is *alphabetical order*. On the probe posting this cut the list at
`now`, and **`python`, `spark`, `snowflake`, `sql`, `terraform`, `streaming` and
`pipelines` — the posting's actual requirements — never entered the required-keyword set at
all**, while `lunches` and `catered` did.

**(D) Seniority and generic role words.** `senior`, `engineer`, `backend`, `data`,
`design`. Harmless when the résumé echoes the title, a false gap when it does not.

**Assessment.** (A), (B) and (D) are the same class of defect as ATS-KW-001 — a non-skill
counted as a skill. (C) is worse and independent: it is not contamination but *silent loss
of the real requirements*, and it plausibly affects the ≥ 85 ceiling more than geography
does. All four are left unfixed here deliberately: each moves scores across the whole
product and needs its own finding, failing tests and review. **(C) in particular should be
raised as its own finding before G-C is adjudicated** — the GOV-021 re-measurement will run
through it.

The deeper fix all four point at: `_extract_keywords` should score against a notion of
*skill*, not against arbitrary prose nouns. That is a redesign, not a defect fix.

## 7. Consequences

- Every ATS consumer improves at once — board scoring (`routers/jobs.py`), `fit_scorer`,
  the tailoring loop, `cover_letter_quality`, `discovery/qualification` — because the
  change is in the shared engine and needs no plumbing. Nothing was threaded through call
  sites, so all scoring paths stay consistent with each other; that consistency matters for
  G-C, where the loop's target and the board's displayed score must be the same number.
- `missing_keywords` no longer tells a user to add a city to their résumé, and
  `split_gap_keywords` no longer counts the city as an unsatisfiable gap — which is the
  specific confound GOV-021 requires re-measuring.
- Scores rise slightly wherever a location was previously unmatched. This is a correction,
  not an inflation: the removed term was never a requirement.

## 8. Follow-ups

1. **Re-run the GOV-021 five-job probe** against this engine before G-C is adjudicated.
2. **File (C)** — single-document TF-IDF truncating real skills alphabetically — as its own
   finding; it is the larger scoring defect.
3. Consider passing the posting's structured `location` into the engine as an exact fourth
   signal. It would close failure mode 2 for suburb-level AU locations, at the cost of the
   cross-path consistency noted in §7; it needs an orchestrator ruling on that trade-off.
