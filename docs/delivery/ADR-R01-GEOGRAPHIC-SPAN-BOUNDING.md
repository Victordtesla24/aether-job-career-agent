# ADR-R01 — the geography filter deleted the posting's requirements and reported a perfect match

**Status:** accepted, implemented
**Date:** 2026-08-04
**Supersedes in part:** `ADR-ATS-KW-001-KEYWORD-CONTAMINATION.md` §3 (span bound), §5 failure
modes 1 and 3, and its "zero collisions" claim (corrected in place there)
**Findings:** R-01 (CRITICAL, deploy-blocking), R-02 (MAJOR)
**Code:** `apps/api/app/services/ats_engine.py`
**Tests:** `apps/api/tests/test_r01_geographic_span_bounding.py`
**Evidence:** `uat/reports/evidence/models-live/R-01/`

---

## 1. What was wrong

ATS-KW-001 stopped scoring the posting's location as a required résumé keyword. It did so
with three positional signals plus a place-name vocabulary, and rested its safety argument
on an **every-occurrence rule**: a token is geography only if *every* occurrence of it sits
inside a detected geographic span.

Two things about that shipped wrong. Both were measured on `9a338c8`.

### R-01 — the location value had no bound

`_geo_value_spans` captured "everything after the label or carrier, up to the first stop
character, or 80 characters". Stop characters were `. ; : ! ? \n ( ) [ ]`, a spaced dash,
and a short list of connector words.

That is a bound on a **sentence**. Production's JD has no sentences. `fit_evidence.py:51,56`
builds the scored text as

```python
req_text = " ".join(str(item) for item in requirements)
return f"{title} {description} {req_text}".strip()
```

— requirement items joined by a **bare space**, with no punctuation between them. So a
requirements array whose first item mentions relocation places the carrier phrase
immediately in front of the entire tech stack, with no stop character anywhere in it, and
the 80-character window swallowed all of it.

Reproduced verbatim on `9a338c8`:

```
reqs = ['Relocation to Melbourne supported','Snowflake','dbt','Airflow','Spark',
        'Kafka','Python','SQL','Terraform','AWS']

JD (job_evidence_text)  -> 'Senior Data Engineer We build data products. Relocation to
                            Melbourne supported Snowflake dbt Airflow Spark Kafka Python
                            SQL Terraform AWS'
tokens deleted as geo   -> ['airflow','aws','dbt','kafka','melbourne','python','relocation',
                            'snowflake','spark','sql','supported','terraform']
required-keyword set    -> ['data', 'engineer', 'senior', 'products']
stack terms scored      -> NONE  (all 9 swallowed)
```

Scored against a résumé carrying the generic title words and **none** of that stack:

```
keyword_match    = 100.0
missing_keywords = []
overall          = 73.26
```

**The product told the candidate they were a perfect keyword match with zero gaps, on a
posting whose entire stack they lack.** That is the fabrication this product exists to
refuse, and it is worse than the defect the geography filter was added to fix.

Two further shapes in the same class, found while fixing it:

* **`Title - City, ST` headers.** `" - "` counted as a location-chain separator, so the
  chain `[engineer, melbourne, vic]` held two confirmed places and expansion walked
  **left**, deleting `engineer` from the keyword set of every posting with that headline.
* **Pipe-delimited one-liners.** `Data Engineer | Melbourne, VIC | Python | Spark` is one
  chain by the old separator set; two confirmed elements licensed taking all of it.

### R-02 — the every-occurrence rule was vacuous for the vocabulary

Signal 3b seeded a vocabulary token at **every** occurrence (`ats_engine.py:568` on HEAD).
"Every occurrence is geographic" was therefore true *by construction* for exactly the
tokens the rule was advertised to protect. Measured:

| JD | term | on `9a338c8` |
|---|---|---|
| `ship binaries for linux, windows and darwin` | `darwin` | deleted |
| `Build the IDE with Monaco, React and TypeScript` | `monaco` | deleted |
| `Experience with Berkeley DB, LMDB and RocksDB` | `berkeley` | deleted |
| `Our type system: Georgia, Helvetica and Inter` | `georgia` | deleted |
| `You will polish long-form copy` | `polish` | deleted |
| `Service Milwaukee and DeWalt power tools` | `milwaukee` | deleted |

The ATS-KW-001 commit message claims the vocabulary has "zero collisions". Its own §5
failure mode 1 and its own guard `test_2` already named `Georgia` as a live one. That
claim is corrected in place in the KW-001 ADR.

### Why the guard suite could not find either

Every JD in the ATS-KW-001 guard file, and all 18 in its differential corpus, terminates
the location with punctuation, and every homonym it tests (`Phoenix`) is one the
vocabulary deliberately omits — so it exercises the *positional* signals and never the
vocabulary. The corpus was structurally incapable of finding either defect.

**One correction to the finding as reported.** It stated that deleting the `.` after
`Melbourne` in the `JD_TAILOR` fixture (`test_ats_kw001_geography_guards.py:210`) would
flip that test. It does not, and it was checked before the fix was written:

```
JD_TAILOR as shipped       span -> 'Location: Melbourne'
JD_TAILOR with the '.' cut span -> 'Location: Melbourne Required skills'
                           real terms lost -> none
```

The window closes on the **`:` after "Required skills"**, not on the deleted `.`, and both
words it does swallow are stopwords. That one fixture is a poor demonstration; the defect
is real and the corpus's blindness to it is real, but the mechanism is that the fixture is
*multi-line and colon-rich*, not that it carries a single load-bearing full stop. The
production shape — `job_evidence_text`, one line, requirement items space-joined and
punctuation-free — is what actually has no stop character, and that is the shape §1
reproduces and the new corpus covers.

## 2. Decision

Keep the geography feature; bound it. Specifically:

1. Bound the location **value** token-by-token instead of by character window.
2. Make the pipe and the spaced dash chain **boundaries**, not joins.
3. Cap what chain expansion may absorb.
4. Curate the vocabulary under a **stated disqualifying rule**, and make the
   every-occurrence rule non-vacuous so a residual collision is survivable.

Rejected alternatives:

* **Delete or disable the geography feature.** It fixes a real defect — the founding
  measurement (`sydney` docking `keyword_match` 100 → 94.44 on every posting) still holds.
* **"Require a vocabulary hit inside the span"** (one of the two shapes the reviewer
  offered). This is the *simpler* rule and it was rejected on evidence: it deletes the
  carrier signal's entire purpose. `based in Wodonga`, `commute to Yarrawonga`,
  `Location: Docklands` name places no gazetteer carries — that is *why* carriers exist —
  and guard tests 5 and 6 pin exactly those. Adopting it would have required weakening two
  existing under-match guards.
* **Reformat `fit_evidence.job_evidence_text` to punctuate the join.** Tempting and wrong:
  it would fix this one call path and leave the engine still unable to bound a span, so
  any other unpunctuated JD — every pipe/middot one-liner a board emits — keeps the defect.
  It would also change the text every ATS consumer scores, moving scores for reasons
  unrelated to this finding.

## 3. Approach — what a location value may contain

`_walk_location_value` walks tokens from the value start and stops at the first token that
cannot be part of a location. A token may be consumed when it is

* a **place** — vocabulary or phrase member, a weak region abbreviation, or location
  vocabulary; or
* **filler** — a determiner, `greater`/`metro`/`area` (`_GEO_VALUE_FILLER`); or
* the **one unlisted token** a location statement is allowed (`_GEO_UNLISTED_BUDGET = 1`) —
  the place name no gazetteer carries.

That single allowance is spendable only where an unlisted name can actually be: *before*
any place has been seen (`based in Wodonga`), or immediately after a chain separator
following one (`Location: Melbourne, Truganina`). An unlisted token separated from a
confirmed place by nothing but a space is the next field or the next sentence —
`Relocation to Melbourne supported Snowflake dbt …` — and ends the value.

It is also **never spent on a token the posting is itself naming as a skill** (the
`_skill_context_indices` set of §3.2). This was added after an adversarial pass on the
first implementation of this fix found `Location: Melbourne, Kubernetes, Terraform, Go`
absorbing `kubernetes` — the allowance exists for unlisted *place* names, not for the first
item of the next field.

The character window survives as an **outer backstop only** (`_GEO_VALUE_MAX_CHARS`, plus
`|`/`•`/`·` added to the stop set). It is no longer the bound.

Chain expansion gets the same cap: a chain must still hold two confirmed geographic
elements, **and** may now absorb at most one token it cannot otherwise account for. A chain
the filter cannot account for that tightly is left entirely alone. `We hire across Sydney,
Melbourne, Python, Spark, Airflow teams` has two confirmed elements and three unaccounted
tokens, so nothing is taken.

### The vocabulary's disqualifying rule (R-02)

> An entry is **excluded** from `_GEO_STRONG_TOKENS` when the colliding sense is something
> a **job posting can require** — a technology, a product or brand the role services, a
> material, a published standard, a language competency, or an ordinary work verb.

64 entries removed under it (14 named senses + 50 demonyms), 482 → 418; weak abbreviations
and phrases unchanged at 69 and 94:

* **technologies/products** — `monaco`, `darwin`, `berkeley`, `georgia`, `milwaukee`,
  `hobart` (commercial kitchen equipment);
* **materials/standards/equipment** — `cork`, `portland` (Portland cement), `chicago` (the
  Chicago Manual of Style), `bristol` (Bristol board, the Bristol Stool Chart),
  `anchorage` (a structural/fall-arrest anchorage), `wellington` (wellington boots),
  `hawthorn` (the plant);
* **ordinary words** — `polish`, `turkey` (`turkiye` retained);
* **language and nationality demonyms, as a class** (50 entries, `polish` counted here as
  well as above: `spanish`, `japanese`, `french`, `german`, `australian`, `british`, …;
  `mandarin` was never in the vocabulary). ATS-KW-001 already
  omitted `english` because it is a competency here rather than a nationality; that
  reasoning is not special to English. A posting asking for fluent Spanish is stating a
  **requirement**, and deleting it tells a monolingual candidate they match a bilingual
  role. Dropping the demonyms costs no detection: the country name is still listed and the
  demonym is still caught positionally (`based in the Netherlands`).

An excluded place is not undetectable — it is detected **positionally**, which is how
postings state a location in the first place.

### 3.2 Making the every-occurrence rule bite (R-02)

`_skill_context_indices` marks the token indices sitting in a separator run that already
holds **two** members carrying independent skill evidence (`_skill_evidence_tokens`). A
vocabulary place named inside such a run, and outside every value span, is not seeded. The
two anchors may not themselves be places or region abbreviations — otherwise `Sydney,
Melbourne and Brisbane` would anchor itself and the founding ATS-KW-001 defect would walk
straight back in.

Runs are detected over **content** tokens, exactly as `_extract_keywords` feeds
`_skill_list_neighbours`. Over the raw token stream the conjunction in `Tahoma and Geneva`
is a token of its own, so the gap between two list items is a bare space and
`_SKILL_LIST_SEP_RE`'s `and`/`or` branch can never fire. (This cost one red test on the
first implementation attempt and is the kind of drift the shared-tokenizer comment in
`_iter_tokens` warns about.)

## 4. The invariant

> **No JD shape may cause a real requirement to be deleted from the required-keyword set by
> the geography filter.**

This is **not** provable in general — "Truganina" and "Kubernetes" are lexically
indistinguishable unlisted capitalised tokens, and no rule separates them with certainty.
So the design does not claim it. It makes the filter **fail safe** instead: every ambiguity
above is resolved by *stopping* or by *keeping the token*.

The argument that the failure direction is now safe, in three parts:

1. **Bounded consumption.** Every path that can delete a token now consumes a bounded
   number of unaccounted tokens: at most `_GEO_UNLISTED_BUDGET = 1` per location statement
   and per chain. There is no path left that consumes an unbounded run of prose. The old
   80-character window could take ~12 tokens; the walk takes at most one it cannot name.
2. **Positional evidence is required for anything not in the vocabulary**, and positional
   evidence is a *closed* set of labels and carrier phrases — a fixed lexicon, not a
   guess about the following word.
3. **Vocabulary membership is no longer sufficient on its own.** A vocabulary hit inside a
   skills list is not geography, so the every-occurrence rule finally does the work it was
   advertised to do, and a collision that survives curation costs a keyword rather than a
   requirement.

The asymmetry that motivates all of it: **under-filtering leaves a cosmetic entry in the
gap list; over-filtering fabricates a perfect match.** Those costs are not comparable, so
every doubt is resolved towards under-filtering.

## 5. Measured before / after

Exact reproduction from the finding, same JD, same résumé:

| | `9a338c8` | fixed |
|---|---|---|
| tokens deleted as geography | 12 (`airflow aws dbt kafka melbourne python relocation snowflake spark sql supported terraform`) | **2** (`melbourne`, `relocation`) |
| required-keyword set | `['data','engineer','senior','products']` | 14 incl. all 9 stack terms |
| stack terms scored | **0 of 9** | **9 of 9** |
| `keyword_match` | **100.0** | **28.57** |
| `missing_keywords` | **`[]`** | `['snowflake','airflow','spark','kafka','python','sql','terraform','aws','supported','dbt']` |
| `overall` | 73.26 | 44.68 |

The candidate is now told the truth: they match 4 of 14 required terms and are missing the
posting's entire stack.

*(The finding reported `overall = 74.45`; measured here as 73.26. The difference is the
`semantic_similarity` component, which depends on the exact résumé prose and was not quoted
in the finding. `keyword_match = 100.0` and `missing_keywords = []` — the load-bearing
claims — reproduced byte-exactly.)*

### Differential, on a corpus that includes the missing shapes

`uat/reports/evidence/models-live/R-01/differential-head-vs-fixed-20260804T103401Z.log`
(source alongside it; two earlier runs are retained — see below). 44 JDs: the original 18,
plus 26 covering space-joined requirements
arrays, `Title - City, ST` headers, bullet/middot/pipe one-liners, locations with no
trailing punctuation, and the R-02 homonyms.

Every token each engine deletes is classified **against the tokenizer's output, not against
`_geographic_tokens`** — the original probe compared removals against the same function
that performed them, which cannot detect a wrong removal.

```
HEAD  9a338c8 : 69 unaccounted deletions   (real requirements deleted)
FIXED         :  0 unaccounted deletions
distinct tokens deleted by HEAD : 74      by FIXED: 27
RESULT: PASS — the fixed filter deletes only geography
```

The 8 geography-free JDs are byte-identical in both engines. All 27 tokens the fixed filter
deletes are places, region abbreviations, region acronyms, demonyms or location vocabulary.

Three runs are retained, deliberately:

* `…T102259Z.log` — first run, flagged `apac` and `latam` as unclassified. Adjudicated as
  region acronyms carried by the vocabulary alongside `emea`/`anz`/`oceania` and deleted
  identically by HEAD, therefore neither a regression nor a new over-filter — recorded in
  §7.4 rather than quietly allowlisted;
* `…T102333Z.log` — same corpus after the classification table was corrected;
* `…T103401Z.log` — after the round-2 tightening (§3, "never spent on a named skill").

The first run reads `HEAD 71 / FIXED 2` because `apac` and `latam` were missing from the
classification table and were counted against BOTH engines; the two later runs read
`HEAD 69 / FIXED 0`. The delta is the table, not the filter — no engine behaviour changed
between the first and second run.

## 6. Tests

`apps/api/tests/test_r01_geographic_span_bounding.py` — 28 test items, **26 fail against
`9a338c8`**, all pass after. The 2 that pass before are deliberate controls: the en-dash
separator (already closed by the existing stop set) and `test_r02_4`, which pins that a
real location is *still* removed.

Fail-before artifacts, in `uat/reports/evidence/models-live/R-01/`:

* `fail-before-20260804T101512Z.log` — the first 27 items against `9a338c8`: **25 failed,
  2 passed**;
* `fail-before-full-downstream-20260804T103408Z.log` — the complete 28-item file plus all
  38 downstream test files against `9a338c8`: **26 failed, 465 passed**, every one of the
  26 in `test_r01_geographic_span_bounding.py`. This also establishes that the baseline
  this fix departs from was green. Its provenance header records honestly that the run
  acquired the `9a338c8` engine by accident — see §6.1.

**§6.1 — a process incident, recorded.** To establish fail-before for the late-added
`test_r01_8`, the fixer copied the `9a338c8` engine over the working tree in this
**shared, production-serving** repo. A tool timeout killed the command before its restore
step ran, leaving the HEAD copy in place for ~90 seconds; it was restored from a
checksummed backup (`md5 ef70de1b…`, verified against the working tree afterwards). Nothing
was committed, and no service was restarted or deployed, so production was unaffected. The
correct technique — used for `test_r01_8` afterwards, and by the differential probe
throughout — is to load the old module through `importlib` under a different module name
and never touch the working tree. The pass-after run below therefore carries md5 bookends
of `ats_engine.py` taken immediately before and after the pytest invocation, so the artifact
proves which code it exercised.

Pass-after: `pass-after-full-downstream-20260804T103908Z.log` — the same 38 downstream test
files plus the new one against the fixed engine, **491 passed, 0 failed**, opening and
closing md5 both `ef70de1b5d9472df64ab4121b8cd4b13`. 465 + 26 = 491: every test that passed
on `9a338c8` still passes, and the 26 that failed now pass.

Covering, per the shapes the original corpus could not contain:

| test | shape |
|---|---|
| `r01_1`, `r01_2` | space-joined requirements array; `keyword_match != 100`, `missing_keywords != []` |
| `r01_3` | carrier span stops at the first non-place token |
| `r01_4` | `Title - City, ST` header keeps the title words |
| `r01_5` | middot / bullet / pipe / en-dash one-liners (parametrised) |
| `r01_6` | location with no trailing punctuation |
| `r01_7` | chain expansion refuses a chain it cannot account for |
| `r01_8` | the one-unlisted allowance is not spent on a named skill |
| `r02_1` | the six named vocabulary homonyms (parametrised) |
| `r02_2` | a place *remaining* in the vocabulary survives a skills list (`geneva`) |
| `r02_3` | a language competency is not a location |
| `r02_4` | **control** — a real location is still removed |
| `invariant_*` | 8 JD shapes; nothing but geography may be deleted |

No existing test was weakened. `test_2`'s "KNOWN LIMITATION" note about `georgia` is now
stale in the KW-001 guard file — deliberately left, since it asserts nothing and was
written to make fixing it *not* a test failure.

## 7. Failure modes and residuals — stated honestly

1. **Under-detection of multi-word unlisted locations.** `Location: North Ryde, Macquarie
   Park` spends its one allowance on `north` and stops. `ryde`, `macquarie`, `park` stay in
   the keyword set and can reach the user's gap list. This is the founding ATS-KW-001
   defect returning in miniature for unlisted suburbs. **Accepted**: cosmetic, and the safe
   direction.
2. **A location in a skills-shaped list is not filtered.** `Sydney, Melbourne, Python,
   Spark` has two skill-evidenced non-place anchors, so the run is treated as a skills list
   and the cities survive as keywords. Same direction, same reason.
3. **Residual vocabulary collisions remain, and are not zero.** No "zero collisions" claim
   replaces the corrected one. Entries kept despite a nameable colliding sense, judged
   place-dominant: `sheffield` (Sheffield steel), `kyoto` (the Kyoto Protocol), `raleigh`
   (bicycles), `tucson` (a car model), `oregon` (chainsaw bars), `cleveland` /
   `cincinnati` (golf clubs / machine tools), `malvern` (Malvern Panalytical), `napier`
   (Napier grass), `bendigo` / `bundaberg` / `carlton` (brands), `victoria`, `charlotte`,
   `guinea`, `florence`, `valencia`, `seville`, `geneva`, `hamburg`, `halifax`, `bern`.
   Each is now **survivable** rather than fatal: named in a skills list, it keeps its
   keyword status (§3). Where it is named in prose and lowercase, it is still deleted —
   that is the un-fixed residual, and it is why the rule in §3 resolves doubt towards
   exclusion.
4. **Region acronyms are deleted.** `apac`, `latam`, `emea`, `anz` are geography by the
   vocabulary. A localisation posting asking for APAC locale work loses the region word
   from its gap list. Pre-existing, unchanged by this fix, cheap direction.
5. **Work-mode words still count as skills.** `remote`, `hybrid`, `onsite`, `office`
   unchanged — ATS-KW-001 §5 mode 5 still stands and still needs its own finding.
6. **The one-unlisted budget is a judgement, not a measurement.** It is set to 1 because
   that is how many unknown names a single location slot holds. A posting stating three
   unlisted suburbs in one chain will under-filter two of them.
7. **Exactly one over-filter survives, and it is bounded to one token.** A label followed
   by filler and then a space-separated stack — `Location: the the the Kubernetes Terraform
   Go` — spends the allowance on `Kubernetes`, because filler does not count as a place
   seen and the stack is not separator-joined so `_skill_context_indices` sees no list.
   Found by the round-2 adversarial pass and left: the JD is degenerate, the cost is one
   keyword (never a fabricated 100), and every candidate rule that closes it also breaks
   the `based in Wodonga` carrier case that guard test 6 pins. Recorded rather than fixed,
   because the honest statement of this design is that **the invariant is enforced as a
   bound, not as a proof** (§4).

## 8. Consequences

* Scores **fall** wherever a carrier phrase or an unpunctuated location previously ate the
  requirements — by design; the previous number was fabricated. The reproduction moves
  `overall` 73.26 → 44.68 and `keyword_match` 100.0 → 28.57.
* `resume_tailor`'s ATS non-regression floor consumes `_geographic_tokens` through
  `jd_keyword_terms`, so it stops vetoing rewrites over swallowed stack terms too.
* Any ATS ceiling measured through the old engine (G-C's `>= 85`, GOV-021's gap counts) was
  measured through a filter that could delete a posting's whole stack, and must be
  re-measured before adjudication.

## 9. Follow-ups

1. Re-measure the G-C `>= 85` ceiling and the GOV-021 gap counts against this engine.
2. Consider punctuating the join in `fit_evidence.job_evidence_text` as *defence in depth*
   — not as the fix (§2), and only with its own finding, since it moves the text every ATS
   consumer scores.
3. The residual list in §7.3 is hand-curated and will drift. The durable fix is the one
   ATS-KW-001 §6 already names: score against a notion of *skill* rather than against
   arbitrary prose nouns.
