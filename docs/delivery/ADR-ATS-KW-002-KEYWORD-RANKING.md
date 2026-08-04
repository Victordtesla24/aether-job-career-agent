# ADR-ATS-KW-002 — the required-keyword set was chosen ALPHABETICALLY and truncated

- **Status:** ACCEPTED (implementation landed; awaiting independent review — the author does not approve his own work)
- **Date:** 2026-08-04
- **Finding:** ATS-KW-002 (MAJOR), escalated from `ADR-ATS-KW-001-KEYWORD-CONTAMINATION.md` §6 item (C), which named this defect and asked for it to be raised on its own before G-C is adjudicated
- **Governance:** `GOLD-MASTER-V2-GOVERNANCE.md` GOV-021 — the "ATS ≥ 85" ceiling was measured through this defect as well as through ATS-KW-001
- **Code:** `apps/api/app/services/ats_engine.py`
- **Tests:** `apps/api/tests/test_ats_kw002_keyword_ranking.py`
- **Evidence:** `uat/reports/evidence/models-live/ATS-KW-002/`

---

## 1. Mechanism — confirmed independently, and the arithmetic is exact

`ATSEngine._extract_keywords` fitted a `TfidfVectorizer` on a **single document**. With
`n = 1`, sklearn's smoothed IDF is

```
idf(t) = ln((1 + n) / (1 + df(t))) + 1 = ln(2 / 2) + 1 = 1
```

for **every** term present, and L2 normalisation is a positive scalar that preserves order.
So the "TF-IDF weight" was *identically the raw term frequency* — the vectorizer was an
expensive `Counter` that merely looked as though it weighted by rarity. The sort key was
`(-weight, term)`, so among terms of equal frequency the required-keyword set was chosen
**in alphabetical order**, then truncated at `_MAX_KEYWORDS = 40`.

Almost every JD term occurs exactly once, so that tie-break decided most of the set.
`test_5_single_document_idf_is_provably_constant` pins the arithmetic so it cannot be
re-litigated from memory.

### 1a. Corrections to the finding as filed

The reported mechanism is correct. Three refinements, offered because being right matters
more here than agreeing:

1. **It is not alphabetical throughout — it is alphabetical *within each term-frequency
   tier*.** Terms the posting repeats do outrank terms it states once. The damage is
   concentrated in the `tf = 1` tier, which is where the 40-slot cut almost always lands.
   The distinction matters because it explains why severity varies by posting: an ad that
   states its stack twice (common — once under "what you'll do", once under "requirements")
   loses less than one that states it once.
2. **The "9 of 16 real requirements lost / 16 boilerplate tokens scored" figure is
   posting-specific, not universal.** On my own reconstruction of the same posting shape I
   measured 4 of 16 lost and 12 boilerplate, because my version repeats its stack. Neither
   number generalises, which is why I stopped using single synthetic postings and measured
   the corpus instead (§2).
3. **The defect is considerably worse than the filed example suggests.** Measured across
   5750 real postings, **84.9%** of the technology terms actually present in a posting never
   entered the scored set.

## 2. Scale — measured on 5750 real production postings

Synthetic postings were not trusted for this. All 5750 `Job` rows with a description longer
than 900 characters were pulled **read-only** from the production database (`SELECT` only,
`set_session(readonly=True)`; the DSN was parsed out of the repo-root `.env` without
sourcing it, so it could never reach a pytest process).

Both columns below are the **same probe script** (`measure_head.py`) run against the two
engine versions over the same 5 743 postings that hit the 40-keyword cap:

| | BEFORE (HEAD `f5d7139`) | AFTER |
|---|---|---|
| real technology terms present | 14 371 | 14 371 |
| **actually scored** | **2 170 (15.1%)** | **9 211 (64.1%)** |
| silently dropped | 12 201 (84.9%) | 5 160 (35.9%) |
| boilerplate tokens occupying scored slots | 8 571 (3.7% of slots) | 5 286 (2.3%) |
| trailing alphabetical run of the 40 keywords | **mean 14.9, median 15, max 34** | **mean 1.7, median 1, max 6** |
| postings where ≥ 20 of 40 were ONE alphabetical run | **1 596 / 5 743** | **0 / 5 743** |

That last row is the finding's own structural claim, closed: not one posting in the corpus
now has its required-keyword set decided in alphabetical stretches.

Most-dropped real technologies, BEFORE: `python` (1011 postings), `salesforce` (666),
`aws` (565), `pipelines` (535), `kubernetes` (528), `orchestration` (435),
`observability` (421), `sql` (407), `linux` (398), `typescript` (366), `terraform` (210).

Boilerplate that took those slots instead: `customers` (2286 postings), `compensation`
(925), `annual` (819), `leave` (594), `employer` (586), `days` (560), `recruiters` (228),
`resumes` (177), `unsolicited` (45).

What is still dropped AFTER, and it is worth reading honestly, because the composition has
changed: `pipelines` (580 postings), `observability` (436), `orchestration` (402), `python`
(306), `kubernetes` (180), `spark` (154). The list is now dominated by lowercase **concept**
nouns rather than product names — see failure mode 1, which is the direct consequence.

The probe vocabularies (`TECH_PROBE`, `BOILERPLATE_PROBE`) are **measurement instruments
only**. No part of the fix consults them — otherwise this would be teaching to the test.

## 3. Options weighed

**(a) Fit IDF against the live corpus at scoring time — REJECTED.** `ATSEngine.score` is
synchronous, stateless and deterministic, and is called from board scoring, `fit_scorer`,
the tailoring loop, `cover_letter_quality` and `discovery/qualification`. Adding a DB read
would make the same résumé/JD pair score differently as the corpus grew — the score is
shown to users and drives the tailoring loop's convergence test, so non-reproducibility is
disqualifying on its own. It also puts every tenant's postings into every other tenant's
scoring path.

**(b) Ship an offline document-frequency model as data — REJECTED, and the reason is
measured, not assumed.** I built the DF model from all 5750 postings and scored with it. It
is a genuine improvement over HEAD (15.1% → **25.2%** technology terms scored, boilerplate
3.73% → 1.13%), but it is not the fix, and it carries a defect of its own:

> **IDF rewards rarity, and an employer's name is the rarest thing in its own posting.**
> Measured: `atlassian` df=8 → **idf 6.46**, the highest weight of anything I sampled —
> far above `terraform` (3.25), `sql` (2.56), `aws` (2.11) and `python` (1.65). Recruiter
> boilerplate also outranks the primary language: `recruiters` 2.46 and `unsolicited` 2.32
> both beat `python`.

So the expectation in the task — that a real corpus makes company names *and* boilerplate
low-value automatically — is **half right**: it correctly demotes boilerplate that appears
in nearly every posting (`customers` 0.50, `leave` 0.84), and it actively *promotes* the
employer's name to first place. Corpus IDF would have made contaminant (A) worse. It also
bakes production data into the repo, needs a refresh owner nobody has, and cannot be
verified by a reviewer from the source tree.

**(c) Raise or remove `_MAX_KEYWORDS` — REJECTED.** It keeps the noise and merely keeps more
of it, and the cap is pinned by ATS-KW-001's `test_10` as a "no knob was turned" invariant.
It is unchanged at 40, and `test_9` re-pins it here.

**(d) Rank by an explicit skill-likelihood signal — CHOSEN.** This is what ADR-ATS-KW-001 §6
said the defect class actually points at: *"`_extract_keywords` should score against a
notion of skill, not against arbitrary prose nouns."* Crucially, the evidence can be read
out of the posting itself, so the engine stays stateless, deterministic, offline and
reviewable — the properties the module has protected everywhere else.

## 4. Decision — rank by requirement evidence; order, never filter

The ordering key is `(-tier, -frequency, first_occurrence)`:

| key part | what it says |
|---|---|
| **tier 2** | the token carries evidence of NAMING a skill (`_skill_evidence_tokens`) |
| **tier 1** | no evidence either way — the fallback |
| **tier 0** | every occurrence sits in a perks/culture/how-to-apply section (`_non_requirement_tokens`) |
| **frequency** | how insistently the posting states it |
| **first occurrence** | the posting's own ordering — job ads front-load what matters |

**Demotion outranks evidence**: a Title-Cased perk is still a perk.

**The alphabet is gone, structurally — not merely deprioritised.** `first_occurrence` is
unique per token, so the key is a **total order**: two distinct tokens can never compare
equal, and no tie can survive to reach a comparison on spelling. That is a stronger
guarantee than "the tie-break is now meaningful", and
`test_4_ties_are_broken_by_the_posting_not_by_the_alphabet` pins it.

**Nothing is deleted.** Unlike ATS-KW-001's geography filter, this change only *orders*.
Every content token stays eligible, and `len(keywords)` is still
`min(_MAX_KEYWORDS, unique tokens)` — pinned by `test_13` — so **no score can move because
the denominator changed size**. It also means the ranking cannot destroy a requirement in a
posting whose vocabulary this design does not understand; the worst case is the ordering it
already had, minus the alphabet.

### 4a. The three evidence signals

1. **Shape** — an embedded digit or `+`/`#` (`s3`, `log4j`, `oauth2`, `c++`, `c#`), or a
   dotted product name (`node.js`, `asp.net`). The dotted form is bounded to ≤ 12 chars with
   a ≤ 4-char suffix because without that it fired on the run-together token a missing space
   produces (`resources.your`), which is prose. `e.g`/`i.e` are excluded explicitly.
2. **All-caps in the source** — `SQL`, `AWS`, `ETL`, and, just as importantly, `GST`, `FBT`,
   `PAYG`, `CPA`. This is what stops the fix from being a software-only fix.
3. **Capitalised away from a sentence or bullet start** — `Python`, `Snowflake`,
   `Terraform`, `Kubernetes`, `Expensify`, `Slack`. A capital at a clause start is grammar;
   anywhere else in a job ad it is overwhelmingly a product, tool or platform.

Plus **list contagion**: an item of a separator run that already holds ≥ 2 evidenced members
joins them, which recovers lowercase-by-branding tools (`dbt` in "Spark, Kafka, Airflow,
dbt, Snowflake, Terraform"). Requiring **two** confirmed members of the **same run** is the
identical rule `_geographic_tokens` uses for location chains, and it is what stops an
ordinary prose list from being harvested.

Measured in isolation on the corpus: these signals capture **83.3%** of the technology terms
present, against the 15.1% the old ranking scored.

### 4b. Section demotion, and why there is no boilerplate word list

Sections run from a non-requirement heading ("What we offer", "Perks & Benefits", "About
us", "Equal opportunity", "How to apply", "No agencies") to the next heading of either kind.
The regexes are **not `^`-anchored**: production descriptions arrive as one flat blob with no
newlines at all, so a line-anchored heading regex matched **0 of 5750** real postings in my
first attempt. That is precisely the trap ADR-ATS-KW-001 §3 recorded for the location label,
and I walked into it before measuring.

A token is demoted only when **every** occurrence falls inside such a section — the
every-occurrence rule ATS-KW-001 established. That is not a nicety, it is what makes the
signal safe across professions:

> `superannuation`, `payroll` and `compensation` are perks boilerplate in a software ad and
> the **literal subject matter** of an accounting one. A flat "benefits words" blocklist —
> which I drafted, measured and threw away — would have destroyed the accountant's actual
> requirements. Positional demotion does not, because in that posting those words also occur
> in the duties. `test_11` pins exactly this.

Guard: if the detected non-requirement sections would claim more than 50% of the posting,
the whole signal is discarded for that posting. Demoting most of a JD would be a silent,
uniform distortion, and beyond that share the detector is likelier wrong than the posting is
to be entirely perks.

Measured: fires on 80.5% of postings, claims a median 24% of the text, and its collateral on
real technology terms is **141 occurrences across all 5750 postings**.

### 4c. The `TfidfVectorizer` was removed, not re-parameterised

Leaving it would leave the next reader believing IDF is applied when §1 proves it cannot be.
Removing it also removes an `except ImportError` fallback branch whose semantics *differed*
from the main path (insertion order, no ranking at all) — a silent behaviour fork.
`scikit-learn` stays in `requirements.txt`: `sentence-transformers` depends on it.

## 5. No weight, threshold, cap or formula moved

`_WEIGHT_KEYWORD`/`_WEIGHT_SEMANTIC`/`_WEIGHT_EXPERIENCE` (0.4/0.4/0.2), `REVIEW_THRESHOLD`
(60.0), `_MAX_KEYWORDS` (40) and `_DEGRADED_SEMANTIC_SCORE` (50.0) are byte-identical to
HEAD, and the `overall` expression is untouched. `test_9` pins all five so a later "make the
number nicer" edit fails loudly. The score moves only because different — better — keywords
are scored.

## 6. Measured before / after

**On the finding's probe posting** (my own reconstruction: Senior Data Engineer, Atlassian,
Melbourne, 107 unique content tokens, 16 named requirements):

| | before | after |
|---|---|---|
| real skills scored | 12 / 16 | **13 / 16** |
| still unscored | `docker`, `warehousing`, `orchestration`, `modelling` | `warehousing`, `orchestration`, `modelling` |
| boilerplate occupying slots | 12 | **6** |

**On the alphabetically-late posting** (`JD_LATE_REQUIREMENTS` in the test file — the case
the finding called out, where every requirement sits behind the perks vocabulary):

| | before | after |
|---|---|---|
| requirements scored | **0 / 6** | **6 / 6** |
| perks tokens scored | 20 | **4** |
| trailing alphabetical run | **36 of 40** (cut at `crew`) | **2** |

**Corpus-wide (5 743 capped postings): 15.1% → 64.1%** of technology terms present are now
scored; boilerplate slot share 3.7% → 2.3%; postings with a ≥ 20-long alphabetical run
1 596 → 0.

**Qualitatively, the non-technical case** — a real production Accountant posting:

```
BEFORE: ll make people support accounting business get impact indirect monthly
        payments re redbubble review tax up accountant accounts ad add adherence
        advisors always analysis analytical analytics anyone artist balance
        balances bank better beyond bubble ca cash check collaborative ...
AFTER : support impact redbubble run manage gst fbt payg payroll expensify slack
        bubble ca cpa qualification public ll make people payments review monthly
        business indirect tax accounting ...
```

Before, the set is alphabetical sludge from `ad` onward and **none** of `GST`, `FBT`,
`PAYG`, `payroll`, `Expensify`, `CA`, `CPA` — the posting's actual requirements — is scored.

**The suite's own `JD_PYTHON`/`RESUME_MATCHING` pair is unchanged in membership** (same 17
keywords, reordered), so `test_perfect_keyword_overlap_scores_high`'s 85.0 floor and every
ATS-KW-001 guard are unaffected by construction, not by luck.

## 7. Failure modes — stated honestly

1. **Concept requirements stay invisible.** `pipelines`, `orchestration`, `observability`,
   `warehousing`, `modelling` are lowercase common nouns with no shape, no caps and no list
   position. They carry no evidence and sit in tier 1, so on a crowded posting they are
   still crowded out — three of them remain unscored on the probe posting above. The
   capitalisation signal is a **proper-noun** detector; it cannot see a concept. This is the
   largest remaining share of the 36.5% still dropped.
2. **Capitalised NAME LISTS are promoted — and one sub-class of boilerplate got WORSE.**
   The capitalisation signal cannot tell a product from any other proper noun, so
   Title-Cased enumerations reach tier 2 whatever they enumerate:
   - customer/partner lists — "our customers include Visa, Mastercard, Qantas and Shein"
     (observed on a real Airwallex posting);
   - **US-style benefit lists** — "Benefits Medical, Dental, and Vision insurance …
     Generous Parental Leave". With no colon after "Benefits" no section is detected, so
     `medical`, `dental`, `parental` and `leave` are promoted *above* real requirements.
     Reproduced minimally: for a posting whose duties name Python and Go, the ranking
     returns `engineer python medical dental parental leave staff services go …` — `go`
     ranks below four benefit words.

   This is a **measured regression on a sub-class**, and it should be read alongside the
   aggregate rather than hidden by it: across the corpus `insurance` rose 88 → 205 postings,
   `parental` → 170, `vision` 62 → 164, `dental` → 159, `equity` 90 → 253. Total boilerplate
   share still fell (3.73% → 2.30%) because much larger classes fell further, but this class
   moved the wrong way and no guard was added for it. The fix is a better non-requirement
   section detector (a bare "Benefits" heading with no colon), which is exactly the
   heading-vocabulary work failure mode 4 describes and is deferred with it.
3. **A SHOUTING posting degrades.** A description written largely in capitals gives the
   all-caps signal to most of its vocabulary, collapsing tier 2 into "most tokens". The
   ordering then falls back to frequency-then-position, which is still better defined than
   frequency-then-alphabet. Not measured separately; no guard is implemented for it.
4. **Section detection is heading-vocabulary-bound.** A posting that states its perks without
   any recognisable heading gets no demotion at all. Direction of error: HEAD's behaviour for
   those tokens.
5. **Section over-capture.** A non-requirement heading phrase occurring in ordinary prose
   opens a span that runs to the next heading. The every-occurrence rule and the 50% guard
   bound the damage; measured collateral is 141 technology-term occurrences across 5750
   postings, but it is not zero.
6. **Single-dot domain names can still get shape evidence.** `stripe.com` satisfies the
   dotted-product rule. `_is_noise_token` only drops tokens with two or more dots, which is
   pre-existing (MV-job-discovery-001) and not addressed here.
7. **`_CAPS_NOT_ACRONYM` is curated and will be incomplete.** An omission promotes one extra
   ordinary word. It can never delete a requirement, so the error direction is bounded.

## 8. Contaminants from ADR-ATS-KW-001 §6 — what this change does and does not fix

**(B) Benefits / culture / boilerplate — PARTIALLY FIXED**, and it fell out of the ranking
work naturally, because "which part of the posting states requirements" is the same question
the ranking asks. Corpus-wide, boilerplate slot share drops 3.73% → 2.30% (−38%); on the
late-requirements posting, 20 perks tokens → 4. **With one honest exception**: Title-Cased
benefit enumerations under a colon-less "Benefits" heading got *worse*, not better — see
failure mode 2 for the measurements. (B) is therefore reduced, not closed.

**(A) Employer / company name — NOT FIXED, DEFERRED, and the decision is measured.** The
task asked for (A) only if it fell out naturally. It does not:

- A carrier-based employer detector (`About X`, `X is a…`, `join X`, `X Pty Ltd`) does work —
  it cuts postings scoring their own employer name from 5114 to **1142** — but it costs
  **299 real technology terms** and wrongly demotes `sql`, `gitlab`, `mongodb`, `databricks`,
  `datadog`, `figma`, `grafana` and `servicenow`, because for a job *at* Databricks the
  employer name is also a technology.
- Adding the every-occurrence protection that would make it safe reduces its effect to
  almost nothing (5114 → **4852**), because the employer's name legitimately appears in
  requirement prose ("you'll help Canva scale").

That is separate machinery with its own trade-off, so it needs its own finding, failing
tests and review. **This change neither fixes nor meaningfully worsens (A): 5008 → 5114
postings (+2.1%).** Note the structured `company` column would settle it exactly, but
threading it into the engine has the same cross-path-consistency question ADR-ATS-KW-001 §8
item 3 raised for `location`, and needs an orchestrator ruling.

**(D) Seniority / generic role words — NOT FIXED.** `senior`, `engineer`, `data` are
Title-Cased in the posting's title, so they reach tier 2 and rank high. Unchanged in kind
from HEAD, where they ranked high on frequency instead.

## 9. Consequences

- Every ATS consumer improves at once — board scoring (`routers/jobs.py`), `fit_scorer`, the
  tailoring loop, `cover_letter_quality` (which calls `_extract_keywords` directly),
  `discovery/qualification` — because the change is in the shared engine with no plumbing.
- `missing_keywords` now names things a candidate can actually act on, so the tailoring
  loop's gap list stops chasing `catered`/`lunches`/`allowance`.
- **Scores will move on real postings, in both directions.** A résumé that matched the
  alphabetical noise loses that credit; a résumé that genuinely holds the stack gains it.
  This is a correction, not an inflation — but it means GOV-021's ≥ 85 ceiling must be
  re-measured against this engine, not merely re-cited.

## 10. Follow-ups

1. **Re-run the GOV-021 five-job probe** against this engine before G-C is adjudicated. Both
   ATS-KW-001 and ATS-KW-002 now sit under that measurement.
2. **File (A) employer identity** as its own finding, with §8's measurements as its starting
   evidence.
3. **Consider a concept-requirement signal** for failure mode 1 — the largest remaining loss.
   A shipped, reviewable skill/concept lexicon is the obvious candidate; it must not be a
   silent tech-only list, or non-technical postings regress.
4. **Widen the non-requirement heading vocabulary** to catch colon-less "Benefits"/"Perks"
   headings, which is what failure mode 2's measured regression turns on.
