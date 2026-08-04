# ADR-F04 — The "Job Probability Score" stops claiming evidence Aether does not have

- **Status:** Implemented (fix landed; gate closure is not this document's to assert)
- **Date:** 2026-08-04
- **Finding:** `docs/delivery/PROD-UAT-2026-08-03.md` F-04
- **Independently corroborated by:** `docs/delivery/audit-fabrication-2026-08-03.md` F-1
  ("a made-up composite sold as a likelihood" — same endpoint, different reviewer, different
  account; it additionally flagged that `app_volume_factor` pegs at 100 from >= 30 applications
  and that the payload carried "no provenance, no confidence, no estimate/heuristic flag")
- **Production evidence:** `uat/reports/evidence/prod-uat-2026-08-03/s13-probability-score-inconsistency.json`,
  `uat/reports/evidence/prod-uat-2026-08-03/s8_dashboard_analytics.png`
- **Fix evidence:** `uat/reports/evidence/models-live/f04/`
- **Surfaces:** `GET /analytics/market-pulse` → `/dashboard` and `/dashboard/analytics`
  (`apps/web/src/components/analytics/MarketPulse.tsx`)

---

## 1. What production showed

One paid analytics screen, two panels, contradicting each other:

| Panel | What it said |
| --- | --- |
| Your Job Probability Score | **34%** — "Likelihood of landing an offer in the next 60 days". Factors: Application volume 3, Interview conversion 0, **Market demand 100**, Skill match 0 |
| Market vs. Your Performance | "External market benchmark unavailable", "Provider: none configured", "Market data: not connected", "No market data source connected — showing your own figures only." |

The larger problem is not the contradiction, it is *where the 100 came from*.

## 2. Formula BEFORE

`apps/api/app/routers/analytics.py::market_pulse()` (pre-fix):

```python
sources_total  = COUNT(*) FROM "Job"  WHERE "userId" = me                 # the user's own board
counts         = get_application_counts(cur, user_id)                      # DISTINCT jobId
total_apps     = counts["total"]
interviews     = counts["interviewed"]
avg_fit        = COALESCE(AVG("fitScore"), 0) FROM "Job"
                 WHERE "userId" = me AND "fitScore" IS NOT NULL

interview_rate       = round(interviews / total_apps * 100) if total_apps else 0
app_volume_factor    = min(100, round(total_apps    / 30 * 100)) if total_apps    else 0
market_demand_factor = min(100, round(sources_total / 50 * 100)) if sources_total else 0
skill_match_factor   = min(100, round(avg_fit))

factors  = [Application volume, Interview conversion, Market demand, Skill match]   # all four ALWAYS displayed
measured = [app_volume_factor, market_demand_factor]                                # unconditional
if total_apps: measured.append(interview_rate)
if avg_fit:    measured.append(skill_match_factor)

prob_score = round(sum(measured) / len(measured)) if measured else 0
```

Rendered as: **"Your Job Probability Score — {prob_score}% — Likelihood of landing an offer in the
next 60 days"**, with the frontend tooltip "…blending your fit scores, application activity, and
**current market conditions**" hardcoded in `MarketPulse.tsx`.

## 3. Every factor, classified

The parent finding asked whether `market_demand` was the only unearned term. It was the only
*fabricated* one, but it was not the only defect in the list.

| # | Factor | Derivation | Verdict | Evidence / reasoning |
| --- | --- | --- | --- | --- |
| 1 | **Application volume** | `min(100, total_apps / 30 * 100)` where `total_apps` = `get_application_counts()["total"]` (canonical DISTINCT-`jobId`) | **Grounded input, undisclosed normalisation constant** | The count is a real fact about the user's own submitted applications and uses the platform-canonical helper. The `/30` reference is an invented convention with no evidence behind it and was never disclosed anywhere on the surface. Kept, with the constant now stated verbatim in the methodology string. |
| 2 | **Interview conversion** | `interviews / total_apps * 100`, both from `get_application_counts()` | **Grounded** | Real outcomes from the user's own `Application` rows; already hardened to the canonical DISTINCT-`jobId` counts by `test_market_pulse_interview_count_divergence.py`. This is the only factor of the four that is an actual outcome measurement. |
| 3 | **Market demand** | `min(100, sources_total / 50 * 100)`, `sources_total = COUNT(*) FROM "Job" WHERE "userId" = me` | **UNEARNED — fabricated** | `sources_total` is the number of postings the user's own scout agent saved. It contains no information about the labour market, about demand, or about this user's prospects. It saturates at 50 jobs; the UAT account held **1637**, so it read a pinned **100** and was the single largest term in the headline. Its label asserted market evidence on a response that simultaneously reported `marketDataConnected: false`. |
| 4 | **Skill match** | `min(100, round(avg_fit))`, `avg_fit = AVG(Job.fitScore)` over fit-scored jobs | **Grounded measurement, mis-gated** | `Job.fitScore` is produced by the real ATS/fit engine against the user's résumé and the job description. But the gate was `if avg_fit:` — *the value*, not *the basis*. So "no job has ever been fit-scored" and "the average fit score is genuinely 0" were the same state, and in both cases the wire still shipped `{"label": "Skill match", "value": 0}` while silently excluding it from the average. Production showed exactly this: `Skill match 0` displayed as if measured, contributing nothing. |
| — | **The composite itself** | `mean(measured)`, presented as "Likelihood of landing an offer in the next 60 days" | **UNEARNED CLAIM** | Even with every input grounded, the *output claim* was not. Aether holds no offer-outcome model, no calibration set, and no base rates. An unweighted mean of (an application count scaled to an invented 30-app target, an interview rate, and an average fit score) is not a probability of anything. The claim was unearned independently of the market term. |
| — | **Zero-evidence behaviour** | `measured = [app_volume_factor, market_demand_factor]` unconditionally | **UNEARNED** | A brand-new account with no jobs and no applications scored a definite **0%** under the headline "Likelihood of landing an offer in the next 60 days" — a confident claim of ~zero chance, asserted from no data at all. |

**Answer to the question asked:** `market_demand` was the only *fabricated* factor, but three
further honesty defects rode on the same surface — the mis-gated Skill match, the uncalibrated
offer-likelihood claim on the composite, and the confident 0% at zero evidence. All four are fixed
here; the surface is not honest with only the first one removed.

## 4. Option chosen

Three options were on the table.

**(a) Connect a genuine market signal — REJECTED, not available.** There is no external
market-data provider anywhere in this codebase, and this is not an oversight but a recorded
position: `_MARKET_DATA_SOURCE_CONNECTED = False` (GAP-P4-060), and
`apps/api/app/agents/market_trends_agent.py` states it in the same terms — *"Aether subscribes to
NO market-data feed: there is no BLS/Seek-insights/Indeed-hiring-lab integration anywhere in the
codebase."* Wave-4A already narrowed the Market Trends Agent's scope to the user's own discovery
feed for this exact reason (ADR-AG-1). Option (a) would require integrating a provider — a product
decision with a contract and a cost, not a defect fix.

**(c) Relabel and keep the term — REJECTED.** Renaming "Market demand" to, say, "Sourced job
volume" would end the *labelling* lie but keep a saturating restatement of the user's own board
inside a headline number, where one click of "Sync Now" still moves it to 100. F-02 (the hardcoded
discovery query that dumped ~1637 irrelevant jobs) guarantees that pin for every user on day one.
A relabelled term that still drives the number is the same defect with better copy.

**(b) Remove the unearned factor and re-weight honestly over what remains — CHOSEN**, combined
with the product's existing degraded-scoring vocabulary for what is left over, per §3 of the
finding brief:

1. `market_demand_factor` is **deleted**. Not renamed, not down-weighted — the input carries no
   information, so no weight is correct except zero.
2. The re-weight is the honest one: the composite was already an unweighted mean of measured
   factors, and it stays an unweighted mean of the measured factors that remain. Nothing is
   re-normalised to "make up" the lost term — losing a fabricated input is *supposed* to move the
   number.
3. Every factor now carries its own provenance on the wire (`measured`, and `value: null` when not
   measured), and the "measured iff its basis has rows" rule — which the code's own comment
   already claimed — is applied **uniformly** instead of to two of the four factors.
4. The composite is relabelled to what it actually is, because after (1)–(3) it still could not
   honestly be called an offer likelihood.
5. At zero evidence the score is `null` and the UI shows "not measured", following
   `LetterQualityPanel` ("Not measured — …, so no score was ever recorded for it") and the Resume
   Studio / job-insight dimension panels, rather than inventing a new empty state.

## 5. Formula AFTER

```python
# analytics.py::market_pulse()
fit_scored_jobs, avg_fit = COUNT(*), COALESCE(AVG("fitScore"), 0)
                           FROM "Job" WHERE "userId" = me AND "fitScore" IS NOT NULL

interview_rate = round(interviews / total_apps * 100) if total_apps else 0

# (label, value, measured, requires_market_data)
factor_specs = [
    ("Application volume",   min(100, round(total_apps / _APPLICATION_VOLUME_REFERENCE * 100)),
                             total_apps > 0,       False),
    ("Interview conversion", interview_rate,
                             total_apps > 0,       False),
    ("Skill match",          min(100, round(avg_fit)),
                             fit_scored_jobs > 0,  False),
]

# A factor that needs external market data cannot be emitted while no provider
# is connected — the flag is part of the factor's DEFINITION, not a check bolted on.
factors = [
    {"label": label, "value": value if measured else None, "measured": measured}
    for label, value, measured, needs_market in factor_specs
    if _MARKET_DATA_SOURCE_CONNECTED or not needs_market
]

measured_values = [f["value"] for f in factors if f["measured"]]
prob_score = (max(0, min(100, round(sum(measured_values) / len(measured_values))))
              if measured_values else None)
```

Response shape (the `probability` wire key is kept — renaming it would ripple through six
consumers for no honesty gain — but nothing rendered from it claims a probability any more):

```jsonc
"probability": {
  "score": 22,                    // int | null  — null means NOT MEASURED, never 0
  "measured": true,
  "label": "Job Search Progress",
  "note": "Average of the measured signals below …",
  "methodology": "Not an offer-likelihood estimate. …",
  "unmeasuredReason": null,       // populated exactly when score is null
  "marketDataConnected": false,   // SAME constant as marketVsYou.marketDataConnected
  "factors": [
    {"label": "Application volume",   "value": 10,   "measured": true},
    {"label": "Interview conversion", "value": 33,   "measured": true},
    {"label": "Skill match",          "value": null, "measured": false}
  ]
}
```

### Behaviour delta on the exact production account

[INFERRED — arithmetic applied to the captured UAT figures, not a fresh production probe; the
production tree is not redeployed by this fix.] The UAT free account (1637 sourced jobs, 1
application → `Application volume 3`, 0 interviews → `Interview conversion 0`, 0 fit-scored jobs)
goes from a reassuring **34% "likelihood of an offer in 60 days"** to **`round((3 + 0) / 2)` = 2%
"Job Search Progress"** with Skill match badged *not measured*. Every point of that number is now
this person's own submitted application and their own measured 0% interview conversion. Sourcing
another 1000 jobs moves it by exactly zero points; the pre-fix 34% was, by contrast, 100/3 of the
way built out of the fact that they had clicked Sync.

## 6. What the user sees at zero evidence

A new account has no applications and no fit-scored jobs, so no factor has a basis:

- `score: null`, `measured: false`, every factor `{"value": null, "measured": false}`.
- The green progress ring is **not rendered at all** — an empty ring still reads as a measured
  zero. In its place is a dashed circle reading **"not measured"** (`data-testid`
  `probability-not-measured`), with the accessible name `"Job Search Progress: not measured"`.
- Below it, `unmeasuredReason`: *"Not measured — none of these signals has data yet. Apply to a
  job, or score a job for fit, and this will start reporting."*
- Each factor still lists by name with *not measured* beside it and **no bar**, so the user can
  see what would be measured and what to do about it.

This is the same vocabulary as `LetterQualityPanel`'s `letter-quality-not-measured`, the Resume
Studio "not measured" badges, and the job-insight dimensions gated by
`fitDimensionsFrom()` — a not-measured signal is shown as absent, never as zero.

## 7. How the banner contradiction is made structurally impossible

The two panels contradicted each other because they had **two independent sources of truth**: the
banner read `_MARKET_DATA_SOURCE_CONNECTED`, while the score panel's market claim was an
unconditional term in the factor list plus hardcoded copy in the React component. Three changes
collapse that to one source:

1. **Server, one constant.** `probability.marketDataConnected` and
   `marketVsYou.marketDataConnected` are the *same* `_MARKET_DATA_SOURCE_CONNECTED` module
   constant, emitted on the same response. They cannot diverge.
2. **Server, market-dependence is part of a factor's definition.** Factors are declared as specs
   carrying a `requires_market_data` flag and filtered against that same constant at construction.
   Re-adding a market-derived factor while no provider is connected is not a display state that
   can ship — the factor is not built. (No factor currently sets the flag; the mechanism exists so
   the next one has to state its dependence.)
3. **Client, no hardcoded copy.** `MarketPulse.tsx` previously hardcoded "Your Job Probability
   Score" and the tooltip "…blending your fit scores, application activity, and current market
   conditions" — copy the server could never correct. The heading, tooltip, note, unmeasured
   reason and the market-data caveat all now come from the API response. The panel renders
   "Market data: not connected — this figure uses only your own recorded activity" from the same
   flag that drives the banner, and drops it when a provider really is connected.

The web test *"states the same market-data availability as the Market vs. You banner"* asserts the
two panels agree; the backend test
*"probability panel reports the same market data state as the banner"* asserts identity of the
flags at the source.

## 8. Type-level protection (why `null` and not a sibling flag)

`MarketPulse["probability"].score` and `factors[].value` are typed `number | null`, not
`number` + a sibling `measured` boolean. Under `strict: true`, `score / 100` and
`` `${value}%` `` are **compile errors** until the caller has narrowed away the null. This is the
same fail-closed reasoning as `apps/web/src/lib/scoring/provenance.ts` ("the untrustworthy arm
simply DOES NOT HAVE the numeric member"), reached without adding a new normaliser module: for
this payload the nullable type already makes the unguarded render a build failure. `measured` is
carried alongside for explicitness and for backend assertions, but it is not what protects the
render path.

## 9. Scope deliberately NOT taken

- **No market-data provider was integrated.** Option (a) remains open as a product decision.
- **`sources_total` and the Jobs-by-Source donut are untouched** — a count of sourced jobs is an
  honest thing to display *as a count of sourced jobs* (already relabelled by GAP-P4-058). The
  defect was using it as a market signal, not showing it.
- **`marketVsYou.comparisons[].you` still carries `0` for a user with no applications.** That is
  the same measured-zero-vs-not-measured question on a different panel and a different finding;
  changing it here would be scope creep. Recorded as residual.
- **`Job.fitScore` carries no persisted degraded-provenance column.** `ats_engine.py` substitutes
  a neutral placeholder for the semantic component when no embedding path is available
  (`semantic_path == "degraded"`), but the `Job` table stores only the number, so `AVG("fitScore")`
  at this layer cannot tell a fully measured score from a partly-degraded one. The Skill match
  factor is therefore *grounded but of unattested precision*. It is not currently materialising —
  `docs/delivery/audit-fabrication-2026-08-03.md` records production logging
  `ATS semantic scoring active path=local` with zero "degraded" lines — but the gap is structural,
  not closed. Closing it needs an additive column plus a backfill decision. Recorded as residual.

## 10. Tests

| Test | Asserts |
| --- | --- |
| `apps/api/tests/test_f04_probability_score_honesty.py::TestScoreIsNotARestatementOfTheUsersOwnJobCount::test_sourcing_more_jobs_cannot_move_the_headline_score` | The load-bearing one, and the one a rename cannot satisfy: seeding 200 more unscored, un-applied-to jobs must not move the score or any factor by a point. |
| `…::test_no_factor_claims_market_evidence_while_no_market_source_is_connected` | No factor label contains "market" while `marketDataConnected` is false. |
| `…::TestScoreAndBannerShareOneSourceOfTruth::test_probability_panel_reports_the_same_market_data_state_as_the_banner` | `probability.marketDataConnected is marketVsYou.marketDataConnected`. |
| `…::TestZeroEvidenceDegradesInsteadOfScoringZero::test_user_with_no_applications_and_no_fit_scores_gets_no_score` | Empty account → `score is None`, `measured is False`, every factor not measured, `unmeasuredReason` present. |
| `…::test_sourcing_jobs_alone_still_produces_no_score` | 60 sourced jobs and nothing else → still no score (pre-fix: `market_demand` 100 → a 50% headline). |
| `…::TestFactorsCarryTheirOwnProvenance::test_unscored_jobs_make_skill_match_not_measured_rather_than_zero` | Basis-empty Skill match is `value: null, measured: false`, not `0`. |
| `…::test_scored_jobs_make_skill_match_measured` | Fit-scored jobs → `value: 72, measured: true`. |
| `…::test_measured_zero_interview_conversion_is_still_counted` | Regression guard on the pre-existing rule: a real 0% conversion stays in the average; the score equals the mean of measured factors. |
| `…::TestHeadlineDoesNotClaimAnOfferLikelihood::test_copy_does_not_promise_a_probability_of_an_offer` | Headline copy makes no offer-likelihood claim; methodology says plainly it is not one. |
| `apps/web/src/components/analytics/__tests__/probability-score-honesty.test.tsx` (6 tests) | Rendered panel: no "Market demand", no offer-likelihood promise, market-data state agrees with the banner and disappears when a provider is connected, null factor badged "not measured" with no bar (while a measured 0 keeps both), null score degrades to the dashed "not measured" ring with no `0%` and no `svg[role="img"]`, and the measured case renders the API's own copy. |

Fail-before / pass-after logs: `uat/reports/evidence/models-live/f04/`.

## 11. Residual

1. No external market-data provider exists; "Market vs. Your Performance" remains a
   your-figures-only panel. Option (a) is a product decision, unaddressed here.
2. `Job.fitScore` has no persisted degraded-provenance column, so Skill match is grounded but of
   unattested precision (§9).
3. `marketVsYou.comparisons[].you` still reports a measured-looking `0` for a user with no
   applications (§9).
4. The JSON key is still `probability` and the React `data-testid` is still `probability-score`.
   Neither is user-visible, and both are load-bearing for six existing consumers/tests; the
   comments on the type and the payload say plainly that the key is historical.
5. The `/30` application reference is a stated convention, not a measurement. It is now disclosed
   in the methodology string, but it remains an arbitrary constant — a defensible one only for as
   long as it is disclosed.
