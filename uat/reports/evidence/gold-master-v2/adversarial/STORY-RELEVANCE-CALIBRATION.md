# STORY-RELEVANCE THRESHOLD CALIBRATION AGAINST REAL PRODUCTION DATA

**Task:** GOLD-MASTER-V2 §7.3.3 — calibrate the story-relevance selection floor before it is wired.
**Role:** independent adversarial measurement (did not author, fix, or first-test the relevance machinery).
**Run window:** 2026-07-31T08:02:24Z → 2026-07-31T08:12Z (UTC).
**Repo commit under measurement:** `962d0ee` — *fix(W-E): wire relevance-filtering capability into build_story_evidence*.
**Production DB:** `aether` schema, reached READ-ONLY (`SET SESSION READ ONLY`, SELECT only; no
INSERT/UPDATE/DELETE/TRUNCATE/DDL issued). DSN read by grepping only the `^DATABASE_URL=` line; never printed.
**Production code changed:** NONE. All analysis scripts live under the session scratchpad
(`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/`), not in the repo.
**Data left behind:** none (read-only).

Every claim below is tagged `[VERIFIED]` (a query/computation performed in this run, with timestamp) or
`[INFERRED]` (reasoning over verified facts).

---

## 0. Headline

**0.4 is not merely mis-calibrated — it is above the mathematical ceiling of the scorer on real data.**

`[VERIFIED 2026-07-31T08:03:01Z]` Across **1,872 real (story × job) pairs** (36 production stories × 52
production jobs) the **maximum** `story_relevance_score` ever observed is **0.1017**. Mean 0.0268, median
0.0234. At the shipped default 0.4, **52 of 52 jobs (100 %) qualify ZERO stories.** So do 0.3, 0.25, 0.2 and
0.15. At 0.1, 50 of 52 jobs (96.2 %) still qualify zero.

`[VERIFIED 2026-07-31T08:06:45Z]` Ceiling probe: concatenating **all 36 stories into one pseudo-story** (the
entire Story Bank, ~2,000 unique terms, every distinct achievement the user owns) scores median **0.2106**,
max **0.3242** against the 52 real JDs — **still below 0.4 for every single job**. Therefore no individual
story can ever reach 0.4 against a real posting; 0.4 is unreachable *by construction*, not by bad luck.

**And the scorer is too weak to gate on at any threshold.** `[VERIFIED 2026-07-31T08:04:18Z]` The 34-of-36
paraphrase duplicates give a free, decisive noise measurement: the *same achievement, merely reworded*, scores
a **median 2.33× (p90 4.98×, max 10.04×)** apart against the *same* job. Between-achievement signal is only
**1.57×** the within-achievement rewording noise. In one real job the same achievement family occupies
**rank 1 and rank 32 out of 36**. A hard gate on this score decides evidence inclusion largely by how verbosely
a story happens to be written.

---

## 1. Data pulled (READ-ONLY, PII-redacted)

`[VERIFIED 2026-07-31T08:02:24Z]` — script `scratchpad/pull_data.py`, output `scratchpad/prod_pull.json`.

| Item | Value |
|---|---|
| `StoryEntry` rows | **36**, all owned by one user (id redacted to `c6c8d016…`) |
| `Job` rows | **52** (task brief said 51; one more has since been sourced), same owner |
| Job sources | greenhouse 21, ashby 17, lever 10, remoteok 3, remotive 1 |
| Job statuses | ready 39, applied 10, tailoring 3 |
| JD description length | min 375, median **5,644**, mean 5,566, max 8,000 chars — **0 empty** |
| Story STAR text length | min 465, median **654**, max 970 chars |
| Story unique significant terms (`_tokens`) | median **57.5** |
| JD unique significant terms | median **382.5** |

Story titles were clustered into achievement families using the **shipped** `story_paraphrase.similarity_score`
plus manual confirmation against titles — 10 families over 36 rows, consistent with the brief's "34/36 are
paraphrases of 8 distinct achievements" (the two extra families are genuine singletons):

`A_SIT_recovery` (4) · `B_exec_rebaseline` (5) · `C_cloud_core_banking` (5) · `D_jira_dashboard` (6) ·
`E_llm_eval_stack` (4) · `F_cobol_mainframe` (5) · `G_ntp_war_room` (3) · `H_ml_telemetry_gap` (2) ·
`I_websocket_server` (1) · `J_pubkey_server` (1).

Employer/PII redaction: no personal names, emails or phone numbers are quoted anywhere in this artifact; only
public job titles, employer names of the *postings*, and story *titles* (which are role-generic achievement
labels) appear.

---

## 2. Score matrix — the real, shipped function

`[VERIFIED 2026-07-31T08:03:01Z]` — script `scratchpad/score_matrix.py`, output `scratchpad/matrix.json`.
Imported `app.services.story_relevance.story_relevance_score` directly from
`apps/api/app/services/story_relevance.py` (no reimplementation). JD string built exactly as
`TailoringAgent.run` builds it (`apps/api/app/agents/tailor_agent.py`):
`f"{job['title']} at {job['company']}. {job.get('description','')}"`.

**Pairs scored: 1,872.**

| Statistic | Value |
|---|---|
| min | 0.0000 |
| max | **0.1017** |
| mean | 0.0268 |
| median | 0.0234 |
| p90 | 0.0495 |
| p99 | 0.0785 |
| stdev | 0.0165 |

**Robustness check** `[VERIFIED 2026-07-31T08:07:10Z]`: the *other* JD-construction form actually shipped —
`routers/stories.py:152`, `f"{title} {description}"` (no company, no separator) — gives max **0.1019**, mean
0.0269, median 0.0234 and the identical zero-qualifying-jobs table. The conclusion does not depend on which
call site builds the JD.

---

## 3. THE DECISIVE METRIC — jobs left with ZERO qualifying stories

`[VERIFIED 2026-07-31T08:03:01Z and finer sweep 2026-07-31T08:07:55Z]`

| Threshold | pairs passing | **jobs with ZERO stories** | median stories/job | mean stories/job | median *distinct achievements*/job |
|---:|---:|---:|---:|---:|---:|
| **0.40 (shipped default)** | 0 (0.0 %) | **52 / 52 = 100 %** | 0 | 0.00 | 0 |
| 0.35 | 0 (0.0 %) | 52 / 52 = 100 % | 0 | 0.00 | 0 |
| 0.30 | 0 (0.0 %) | **52 / 52 = 100 %** | 0 | 0.00 | 0 |
| 0.25 | 0 (0.0 %) | **52 / 52 = 100 %** | 0 | 0.00 | 0 |
| 0.20 | 0 (0.0 %) | **52 / 52 = 100 %** | 0 | 0.00 | 0 |
| 0.15 | 0 (0.0 %) | **52 / 52 = 100 %** | 0 | 0.00 | 0 |
| 0.10 | 2 (0.1 %) | **50 / 52 = 96.2 %** | 0 | 0.04 | 0 |
| 0.08 | 0.9 % | 46 / 52 = 88.5 % | 0 | 0.31 | 0 |
| 0.06 | 4.2 % | 29 / 52 = 55.8 % | 0 | 1.50 | 0 |
| 0.05 | 9.9 % | 15 / 52 = 28.8 % | 1.5 | 3.56 | 1 |
| 0.04 | 19.5 % | 5 / 52 = 9.6 % | 4.5 | 7.02 | 2.5 |
| 0.03 | 36.2 % | 1 / 52 = 1.9 % | 12 | 13.04 | 5 |
| 0.025 | 47.1 % | **0 / 52 = 0 %** | 17 | 16.96 | 6 |
| 0.02 | 58.4 % | 0 / 52 = 0 % | 20 | 21.02 | 7 |
| 0.01 | 87.2 % | 0 / 52 = 0 % | 32 | 31.40 | 10 |

**Reading of this table** `[INFERRED]`: there is **no threshold with a usable operating point**. Everything
≥ 0.06 starves the majority of jobs of all evidence. The first threshold that starves *no* job is **0.025**, at
which point 47 % of all pairs pass and 17 of 36 stories survive — that is not §7.3.3 relevance selection, it is
a mild trim whose cut line sits inside the noise band measured in §5. The window between "starves half the
jobs" (0.06) and "barely filters" (0.025) is **0.035 wide on a score whose own rewording noise is ±0.007
(§5)** — i.e. the entire usable dynamic range is only ~5 noise units.

---

## 4. WHY the scale is compressed — mechanism, not mystery

`[VERIFIED 2026-07-31T08:07:40Z]`

The formula is *share of the JD's TF-weighted vocabulary that the story covers*:
`matched_weight / total_jd_weight`. The denominator is the whole posting; the numerator is what a ~650-char
story can cover. With median 382 unique JD terms vs median 57 unique story terms, a *perfectly on-topic* story
can only ever cover a small slice. Three compounding effects:

1. **Length asymmetry (dominant).** `[VERIFIED]` Pearson correlation between a story's unique-token count and
   its mean score across all 52 jobs is **+0.6375** — verbosity, not fit, is the single strongest predictor of
   score. Correlation between JD length and a job's max score is **+0.013** (none), so this is a story-side,
   not JD-side, artefact.
2. **Generic vocabulary carries the signal.** `[VERIFIED]` Aggregating matched weight over all 1,872 pairs,
   **56.1 % of ALL matched weight is carried by just 25 terms**, most of them corporate boilerplate or missed
   stopwords: `delivery, team, management, program, data, teams, technical, build, including, automation, time,
   all, while, operational, engineering, using, risk, governance, compliance, environment, end-to-end, product,
   within, enterprise, leadership`. Note `including`, `all`, `while`, `using`, `within`, `time` — pure
   connectives the shipped `_STOPWORDS` list does not cover. The score is measuring *how corporate the prose
   is*, not *whether the achievement fits the role*.
3. **Tokenizer keeps trailing punctuation (real defect, minor magnitude).** `[VERIFIED]`
   `_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")` admits `.`, `-`, `/` as *trailing* characters, so
   `"services."` and `"services"` are different tokens. **6.6 % of all weighted JD vocabulary (1,800 / 27,432
   tokens across the 52 jobs)** is punctuation-suffixed and can essentially never match a story term. Repairing
   this raises the max from 0.1017 → 0.1080 and the mean from 0.0268 → 0.0297 (+11 % relative) — a genuine bug
   worth fixing, but it moves the scale by ~0.006 absolute and changes no conclusion here.

---

## 5. IS THE SCORER DISCRIMINATING, OR IS IT NOISE? — the paraphrase-duplicate experiment

`[VERIFIED 2026-07-31T08:04:18Z]` — script `scratchpad/discriminate.py`.

The 34/36 paraphrase duplicates are a gift: **two rewordings of the SAME achievement scored against the SAME
job MUST score alike if the metric measures relevance.** They do not.

| Measurement | Value | Meaning |
|---|---|---|
| Mean **within**-family stdev (same achievement, reworded) | **0.00718** | pure wording noise |
| Mean **between**-family stdev (different achievements) | **0.01124** | the actual relevance signal |
| **Signal-to-noise (between / within)** | **1.566** | ~39 % of score variance is rewording noise |
| Same-achievement **max/min score ratio** (families ≥3 members) | median **2.33×**, p90 **4.98×**, max **10.04×** | the same achievement scores up to 10× apart |
| Distinct achievement families in each job's top-5 | mean 2.9 (top-5 is 3 families for 25/52 jobs) | duplicates crowd the top |
| Cross-**job** story-ranking Spearman (mean over 1,326 job pairs) | **+0.545** | over half the ordering is a property of the *story*, not the (story, job) pair |
| Top-1 story identity | one story is top-1 for 11/52 jobs; one family (`C_cloud_core_banking`) is top-1 for **23/52 jobs** | the "most relevant story" is largely JD-invariant |

`[INFERRED]` A metric where re-wording the same true achievement moves it 2.3× (median) is not safe to use as a
**hard binary gate**. Whether a story clears the bar is decided substantially by prose style.

---

## 6. QUALITATIVE SAMPLE — does the ranking match human judgement?

`[VERIFIED 2026-07-31T08:05:40Z and 08:06:20Z]` Six jobs sampled across domains. Scores are the shipped
function's, verbatim.

### 6.1 Plenti — *Business Analyst* (fintech lender, AU) — **partial hit, with a disqualifying internal contradiction**

Top-5 are all `D_jira_dashboard` (analytics/reporting/stakeholder visibility) — a **defensible** #1 family for a
BA role. But the full 36-row ranking exposes the noise directly:

```
0.0722  [D_jira_dashboard] Analytics Dashboard for Sprint Velocity & LLM-Retrospectives     <- rank 1
0.0695  [D_jira_dashboard] JIRA Analytics Dashboard for Agile Team Insights
0.0668  [D_jira_dashboard] JIRA Analytics Dashboard for Sprint Velocity & LLM-Powered Retros
...
0.0481  [C_cloud_core_banking] Cloud-Native Core Banking Transformation - 30% Faster Delivery  <- rank 7
...
0.0214  [D_jira_dashboard] JIRA Analytics Dashboard for Agile Insight Generation            <- rank 32 (!)
0.0160  [C_cloud_core_banking] Delivering Cloud-Native Core Banking Transformation at ANZ    <- rank 34
0.0107  [E_llm_eval_stack] Developing LLM Evaluation Stack to Reduce Hallucination Risk     <- rank 36
```

**The SAME achievement family occupies rank 1 (0.0722) and rank 32 (0.0214)** — a 3.4× spread from wording
alone. `C_cloud_core_banking` — the *most domain-relevant* family for a **lending/banking** BA role — is spread
across ranks 7, 13, 24, 30 and **34**. A gate at any level slicing this list keeps or drops core-banking
evidence essentially at random.

### 6.2 decagon — *Senior Agent Product Manager* (conversational-AI platform) — **clear contradiction of human judgement**

```
0.0519  [C_cloud_core_banking] Cloud-Native Modernisation of Core Banking Platforms at ANZ   <- rank 1
0.0452  [C_cloud_core_banking] Cloud-Native Core Banking Transformation - 30% Faster Delivery
0.0419  [A_SIT_recovery]       Recovery of Infeasible SIT Window for Payday Super Reform
0.0318  [E_llm_eval_stack]     LLM Evaluation Stack - 38% Fewer Error Budget Breaches        <- best AI story, rank 5
0.0184  [E_llm_eval_stack]     LLM Evaluation Stack to Reduce Error Budget Breaches
0.0168  [E_llm_eval_stack]     Developing LLM Evaluation Stack to Reduce Hallucination Risk
0.0151  [E_llm_eval_stack]     LLM Evaluation Stack for Production Risk Management
0.0084  [H_ml_telemetry_gap]   AI/ML Telemetry Gap Analysis at ANZ                           <- bottom-2
0.0067  [H_ml_telemetry_gap]   Azure ML Telemetry Gap Analysis Driving System Reliability    <- bottom-1
```

For an **AI-agent product role**, the candidate's LLM-evaluation and AI/ML-telemetry work is the single most
relevant evidence they own — the `E` story's own words are *"Built and deployed an end-to-end evaluation stack
using Langfuse and Phoenix to score hallucination, latency, and cost across LLM generations."* The scorer ranks
core-banking modernisation **1.6–3.4× above** it and puts the AI/ML telemetry stories **dead last**. Human
judgement is inverted.

### 6.3 Grafana Labs — *Senior Product Manager, Infrastructure Observability* — **contradiction + within-family inversion**

```
0.0678  [C_cloud_core_banking] Cloud-Native Modernisation of Core Banking Platforms at ANZ   <- rank 1
0.0313  [E_llm_eval_stack]     LLM Evaluation Stack - 38% Fewer Error Budget Breaches        <- rank 5
0.0209  [E_llm_eval_stack]     LLM Evaluation Stack to Reduce Error Budget Breaches
0.0196  [H_ml_telemetry_gap]   Azure ML Telemetry Gap Analysis Driving System Reliability
0.0183  [I_websocket_server]   Real-Time WebSocket Telemetry Server - P95 Latency <200ms
0.0078  [E_llm_eval_stack]     LLM Evaluation Stack for Production Risk Management           <- bottom-3
0.0078  [E_llm_eval_stack]     Developing LLM Evaluation Stack to Reduce Hallucination Risk  <- bottom-3
```

For an **observability** product role, the telemetry-server, telemetry-gap-analysis and error-budget/SLO
stories are the obvious evidence; core banking wins by 2.2×. Worse, the **same** LLM-eval achievement appears at
rank 5 (0.0313) *and* in the bottom-3 (0.0078) — a **4.0× spread**, opposite ends of the same ranking, for two
paraphrases of one piece of work.

### 6.4 MUSEUM OF ICE CREAM — *Creative Project Manager* — **no honest signal, and the metric does not say so**

Top-1 is *"Recovery of Infeasible SIT Window for Payday Super Reform"* (0.0659) — an enterprise banking
test-management story, for a creative/experiential PM role at an ice-cream museum. Human judgement: **none** of
the 36 stories is strongly relevant here; the ranking simply surfaces the most verbose one. Yet
`[VERIFIED 2026-07-31T08:14:05Z]` 0.0659 is the **16th-highest max-score of all 52 jobs** — higher than 36
other postings, and statistically indistinguishable from the Grafana Observability role's best match (0.0678,
rank 14) where the candidate owns directly relevant telemetry work. The score gives no usable "no good match"
signal: an off-domain posting and a well-matched posting land 0.002 apart.

### 6.5 Stripe — *Program Manager, Security GRC* — **defensible**

Top-3: cloud-native core-banking transformation (0.1017 — the global maximum), COBOL/mainframe test-evidence
automation for 8 squads (0.0944), executive **governance** & capacity re-baselining (0.0896). Regulated-finance
governance/compliance evidence at the top is a reasonable human answer. Bottom: JIRA dashboards, Azure ML
telemetry — also reasonable.

### 6.6 Anthropic — *Senior Data Center Capacity Delivery Manager, AUS* — **defensible**

Top-5: SIT-window recovery ×2, executive **capacity** re-baselining ×2, mainframe test-evidence automation.
"Capacity" and delivery-recovery evidence at the top matches the role. Bottom: LLM-eval stack — arguably wrong
for **Anthropic** specifically, but right for the *role* described.

### Qualitative verdict `[INFERRED]`

**2 of 6 defensible (Stripe, Anthropic), 1 partial-but-internally-contradictory (Plenti), 2 outright inverted
(decagon, Grafana), 1 pure noise with no honest "no match" signal (Museum of Ice Cream).** The function has
*some* real topical signal — it is not random — but it is contaminated by verbosity and boilerplate to the point
that its ordering disagrees with obvious human judgement on a third of the sample, and its *within-achievement*
spread routinely exceeds its *between-achievement* spread.

---

## 7. THE DISPUTED FIXTURE — `test_gap_p6_tailoring_ats.py::test_tailoring_agent_wires_story_bank_into_evidence`

`[VERIFIED 2026-07-31T08:05:02Z]` Independently recomputed:

| JD string | score |
|---|---|
| the fixture's bare `_JD` constant (`apps/api/tests/test_gap_p6_tailoring_ats.py:53-56`) | **0.1818** |
| the JD `TailoringAgent.run` actually builds — `"Backend Engineer at Acme. " + _JD` | **0.1429** |

**The implementing agent's ≈0.18 is CORRECT** (it is the bare-`_JD` figure; the value that would actually gate
in `run()` is 0.1429). Its refusal to wire `run()` without adjudication was the right call.

**Is the fixture representative? No — and not in the direction anyone assumed.** The fixture's JD tokenizes to
**14 tokens**:

```
['backend', 'engineer', 'acme.', 'senior', 'backend', 'engineer.', 'requirements',
 'python', 'postgresql', 'rest', 'kubernetes', 'kafka', 'backend', 'services.']
```

Real JDs tokenize to a **median 610 tokens / 382 unique**. The fixture is a bare keyword list with zero company
boilerplate — the *easiest possible* denominator. Consequently:

- The fixture's 0.1429–0.1818 is **higher than the maximum score achieved by ANY of the 1,872 real pairs
  (0.1017)** — it is roughly **1.4–1.8× the best real-world case**, and ~6× the real median.
- It is therefore **not** an "artificial edge case that scores too low"; it is an artificial edge case that
  scores **too HIGH**. Tuning the threshold down until the fixture passes (≤ 0.14) would still leave
  **~100 % of real jobs with zero qualifying stories** (0.15 → 52/52 zero; 0.10 → 50/52 zero).

`[INFERRED]` **There is no threshold value that both keeps this fixture green and supplies real jobs with
evidence** until you drop to ≈0.05, where the fixture passes comfortably but 28.8 % of real jobs still starve
and the cut line is deep inside the noise band. **Neither the test nor the threshold is the thing that should
move: the design should.**

---

## 8. WHAT THE FILTER WOULD ACTUALLY DO IF WIRED — the call sites are guard corpora, not prompt content

`[VERIFIED 2026-07-31T08:01–08:08Z by file read]` `build_story_evidence` has exactly three call sites, and
**none passes `job_description` today** — so the filter is inert in production, as the brief states:

| Call site | Line | What `story_evidence` feeds |
|---|---|---|
| `apps/api/app/agents/tailor_agent.py` | 411 | `evidence_extra` → the **anti-fabrication / entailment corpus** of `TailoringLoop` |
| `apps/api/app/agents/cover_letter_agent.py` | 1338 | `claim_evidence` → `resume_tailor.unsupported_claim_tokens` — the **§9 claim guard's** evidence corpus |
| `apps/api/app/routers/cover_letters.py` | 717 | same `claim_evidence` role on the **refine** path (ML-W26) |

`[INFERRED — this is the most important structural finding]` At all three sites the story text is **evidence the
guards check claims AGAINST**, not text handed to the model as "use these stories". Narrowing it therefore does
**not** mean "the letter cites better stories" — it means **the anti-fabrication guard forgets that a true
achievement exists**. A claim the candidate genuinely proves via a filtered-out story becomes an *unsupported
claim*; `cover_letter_agent.run` then re-drafts with `"do not claim personal experience with: …"` feedback and,
after `retry`/`retry2`, **rejects the letter** (guard-rejection degrade → `coverLetterUnavailable`, run
refunded). On the tailoring side a narrowed `evidence_extra` makes rewrites fail the fabrication guard until
`best["changes"] == 0` and `NoChangesApplied` is raised.

That is precisely the brief's "too HIGH" failure mode — *an anti-fabrication refusal where a good letter was
possible* — and at 0.4 it would fire on **100 % of real jobs**, reverting both guards to a résumé-only corpus
and making them strictly *more* likely to reject truthful drafts than today's behaviour.

`[INFERRED]` §7.3.3's intent ("generation uses only stories with relevance ≥ threshold") is a statement about
**evidence selection for the prompt**. Applying it to a **guard corpus** is a category error that trades a
truthfulness *win* for a truthfulness *risk*. If §7.3.3 is to be satisfied in substance, the filtered set should
govern **which stories are offered to the model as material**, while the **guard corpus stays the candidate's
full true evidence**. Those two must not be the same variable.

---

## 9. WOULD A DIFFERENT NORMALISATION RESCUE IT? (diagnostic only — no production change proposed)

`[VERIFIED 2026-07-31T08:06:05Z]` — script `scratchpad/alternatives.py`. Same 1,872 pairs, same family
signal/noise method as §5. **This is measurement, not a proposal to reimplement anything.**

| Variant | min | max | mean | median | within-sd | between-sd | **signal/noise** |
|---|---:|---:|---:|---:|---:|---:|---:|
| **shipped** (JD-coverage, TF-weighted) | 0.0 | 0.1017 | 0.0268 | 0.0234 | 0.00718 | 0.01124 | **1.566** |
| story-side coverage (story-normalised) | 0.0 | 0.3929 | 0.1410 | 0.1358 | 0.02525 | 0.04041 | 1.600 |
| Jaccard | 0.0 | 0.0651 | 0.0200 | 0.0190 | 0.00428 | 0.00639 | 1.494 |
| TF cosine | 0.0 | 0.1978 | 0.0487 | 0.0410 | 0.01021 | 0.02237 | **2.191** |

`[INFERRED]` Length-normalisation fixes the **scale** (story-side coverage reaches 0.39; a 0.4-style number
becomes at least discussable) but **not the discrimination**: the best variant still has rewording noise at
~46 % of the achievement signal. The limitation is the method — bag-of-words lexical overlap over a 36-story
corpus drawn from **one career**, where every story shares the same professional vocabulary — not the choice of
denominator. No re-normalisation makes a hard binary gate safe.

---

## 10. RECOMMENDATION

### (a) Empirically-supported threshold value

**Do not ship a hard relevance gate at any value.** If a numeric floor must exist in config for §7.3.5, the only
value defensible on this data is **0.0 (gate disabled by default)**, with the *ranking* used instead of the
*threshold* (see (c)).

If the programme insists on a non-zero floor being live, the **maximum** empirically survivable value is
**0.025** — the highest threshold at which **zero of 52 real jobs is starved** (`[VERIFIED §3]`). I recommend
against it: at 0.025 the filter passes 47 % of pairs (17/36 stories, 6/10 achievement families), so it delivers
almost none of §7.3.3's intent while introducing a cut line whose position is inside the ±0.007 rewording-noise
band. **0.4, 0.3, 0.25, 0.2, 0.15 and 0.1 are all empirically refuted** — each starves ≥96 % of real jobs.

### (b) Should `TailoringAgent.run` pass its JD? — **NO, not as the code stands.**

`[INFERRED from §3 + §8]` Passing the JD at the current default turns the story contribution to
`evidence_extra` into the empty string for **100 % of real jobs** (`[VERIFIED §3]`), which:
- silently removes the Story Bank from the **anti-fabrication corpus** — the exact thing GAP-P6-TAIL-001 added
  it for — making truthful rewrites *more* likely to be rejected and `NoChangesApplied` *more* likely to fire;
- delivers **zero** §7.3.3 benefit, because nothing about which stories the model is *shown* changes at this
  call site.

**Effect on the protected regression test under my recommendation:** with the recommended value (gate disabled /
`0.0`) `test_tailoring_agent_wires_story_bank_into_evidence` **stays green, unchanged, untouched** — `run()`
keeps not passing a JD, `build_story_evidence` keeps its current behaviour, and the assertions on `"Kubernetes"`
/ `"Kafka"` in `evidence_extra` continue to hold. **Nothing about that test needs to move, and it was right to
protect it.** For the record: had `run()` been wired at 0.4, the fixture would have failed
(0.1429 < 0.4) — and so would every real job.

The correct future wiring, if §7.3.3 is to be met in substance, is a **separate parameter**: pass the JD to
select/rank stories for the *prompt material*, and keep `build_story_evidence(user_id, repo)` (unfiltered) for
the `claim_evidence` / `evidence_extra` **guard corpora**. That is a design change, out of scope for this
measurement task, and it should be specified and reviewed before any code moves.

### (c) Fallback-when-empty policy — **REQUIRED if any gate is ever wired; but prefer top-N ranking INSTEAD of a gate**

`[VERIFIED §3]` At the shipped default a fallback would fire on **52 of 52 jobs (100 %)** — i.e. the "fallback"
would be the only code path that ever runs, which is itself proof the gate is wrong. **Arguments in favour:** it
is the only thing standing between a mis-set `AETHER_STORY_RELEVANCE_THRESHOLD` and a silent, total loss of the
Story Bank from the anti-fabrication corpus — a change that degrades *truthfulness machinery*, produces no
error, and would be invisible in production. **Argument against a fallback as designed:** a policy that triggers
100 % of the time is not a fallback, it is the actual behaviour wearing a disguise, and shipping it would let a
refuted threshold sit in config looking calibrated.

**Recommendation:** replace the binary gate with **top-N-by-score selection (N ≈ 5), never a floor.** Evidence:
`[VERIFIED §5]` each job's top-5 already spans a mean of **2.9 distinct achievement families**, so top-5 gives
real diversity while genuinely narrowing 36 → 5; it is **scale-free** (immune to the length asymmetry of §4 that
makes any absolute threshold meaningless); and it **can never return an empty set**, so no fallback branch is
needed and the "starve the guard" failure mode is structurally impossible. Given §5's noise, the *ordering*
within the top-N is only weakly trustworthy — which is tolerable for *choosing what to show the model* and
intolerable for *deciding what the guard is allowed to know* (§8).

### (d) Is the scorer good enough to gate on at all? — **NO. Stated plainly, per the brief's invitation.**

`[VERIFIED §5, §6, §9]` **The scorer is too weak to gate generation safely.** The decisive evidence, independent
of any threshold choice:

1. **Rewording the same true achievement moves its score a median 2.33× (max 10.04×)** against the same job.
   A binary gate would admit or exclude the *same* evidence based on prose style.
2. **Signal/noise is 1.57** — 39 % of score variance is rewording noise. No re-normalisation fixes it
   (best alternative: 2.19).
3. **Human judgement is inverted on 2 of 6 sampled jobs**, including an AI-agent PM role that ranks the
   candidate's LLM-evaluation and AI/ML-telemetry work **below core-banking modernisation and dead last**.
4. **56 % of matched weight comes from 25 generic/boilerplate terms**, several of them missed stopwords
   (`including`, `all`, `while`, `using`, `within`) — the metric substantially measures corporate register.
5. **It has no honest "no good match" signal**: an ice-cream-museum creative PM role (no relevant evidence
   whatsoever) scores a best match of 0.0659 — rank 16 of 52, indistinguishable from the 0.0678 of a Grafana
   observability role for which the candidate owns directly relevant telemetry work.

**What it IS good enough for** `[INFERRED]`: a **soft, advisory ordering** — exactly what
`GET /stories?job_id=` (`routers/stories.py:154`) already does, surfacing `relevance_score` for a **human** to
sanity-check and choose from. That is an honest, deterministic, reproducible aid. Note for the UI/UX owner: the
values a user sees there will be **0.00–0.10**, and presenting a 0.07 as "relevance" without a scale
explanation reads as "7 % relevant" and will look broken; the *rank* is the meaningful part, not the number.

### Secondary defects found while measuring (filed here, not fixed — no production code was changed)

1. `[VERIFIED §4.3]` **Trailing-punctuation tokenizer bug** in `story_relevance.py:41` — `_WORD_RE` admits
   `.`/`-`/`/` as trailing characters, so `services.` ≠ `services`. **6.6 % of all weighted JD vocabulary**
   (1,800 / 27,432 real tokens) is permanently unmatchable. Real, small, worth a one-line fix
   (`rstrip("./-")` after `findall`) independent of everything above.
2. `[VERIFIED §4.2]` **Stopword list misses common connectives** that carry real matched weight —
   `including`, `all`, `while`, `using`, `within`, `time`, `end-to-end`.
3. `[VERIFIED §2 vs §8]` **Two different JD strings** feed the same scorer:
   `tailor_agent.run` → `"{title} at {company}. {description}"`; `routers/stories.py:152` →
   `"{title} {description}"`. Numerically immaterial here (max 0.1017 vs 0.1019) but it means the score a user
   *sees* is not byte-identical to the score generation *would* use — worth unifying before anything gates on it.

---

## 11. Reproduction

Scripts (session scratchpad, not committed):
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/{pull_data.py,score_matrix.py,discriminate.py,alternatives.py}`
Data: `prod_pull.json` (raw prod rows — **contains real user data, deliberately NOT committed**),
`matrix.json` (1,872-cell score matrix + per-job top/bottom), `clusters.json`, `discriminate.json`.

All scoring used the shipped `apps/api/app/services/story_relevance.py::story_relevance_score` imported
directly. No production code, config, or data was modified. No secrets printed. No deploy, restart, or push. No
pytest suite run.
