# Aether v5 diagnosis — 103 gaps from 9 parallel readers + 8 adversarial challenges

## Adversarial outcome: 5 of 8 challenged claims REFUTED

REFUTED — do NOT act on these as originally stated:
1. coverLetter "records failures as successes, CRITICAL live defect" -> HISTORICAL. An upstream LLM
   outage 2026-07-27..29; rows carry cover_letter_unavailable:true, billed $0.00 (refunded). Not live.
2. board_sweep "burned 1,645 runs" -> HISTORICAL, already fixed.
3. notification agent never ran -> true but NOT a defect; the catalog does not misrepresent it.
4. "scout/fitScorer are dead" -> they function correctly; the discovery SOURCE POOL is exhausted.
   MEDIUM, already tracked as tasks #23/#24.
5. tailor "applies zero changes in 120 runs" -> that is the ANTI-FABRICATION GUARD WORKING.
   116 of 120 carry 7-8 rejected rewrites of unverifiable metrics; costUsd 0, refunded.
   *** Do NOT "fix" this. Weakening the guard would destroy the product's core promise. ***

CONFIRMED under challenge:
- submission agent has ZERO AgentRun rows (0 of 3923).
- emailAgent recruiter-voice drafts are real, but the cause is different: drafts are grounded on the
  candidate's OWN sent mail when he wrote last, so the model replies TO him in the recruiter voice.
- BLOCKER-002 is live: 8 of 92 Applications carry the test-probe cover letter (6 submitted + 2 draft,
  count corrected from 5+2).

## [CRITICAL] SRC-01
**What:** [VERIFIED] Adzuna — the ONLY configured source that searches the whole AU open market and the ONLY one that applies the user's `location` — is skipped on every single run because its credentials are absent. This is the single largest cause of zero new AU jobs.
**Where:** apps/api/app/services/discovery/adzuna_adapter.py:60-68 (credential check) → apps/api/app/agents/scout_agent.py:67-74 (records status="skipped")
**OPERATOR:** YES — external account. Register at developer.adzuna.com (free tier), obtain app_id + app_key, hand them over for .env. Nothing in this repo can substitute for it.
**Fix:** Operator registers a free developer account at developer.adzuna.com, then adds `ADZUNA_APP_ID=...` and `ADZUNA_APP_KEY=...` to /home/ubuntu/github_repos/aether-job-career-agent/.env (start-api.sh:20 exports every .env key into the API process) and restarts aether-api. Zero code change — adapter, registry entry, pagination (AETHER_ADZUNA_MAX_PAGES=5, MAX_JOBS=200, max_days_old=30, sort_by=date) and the AU country default are already written and wired. Verify with one cron cycle: adzuna must flip from status=skipped to status=ok with fetched>0 (a wrong key surfaces honestly as status=error via AdapterFetchError at adzuna_adapter.py:97, not as a silent skip).

## [CRITICAL] AG-01
**What:** coverLetter records LLM-unavailable FAILURES as status='completed'. Only 82 of 2,002 "completed" runs (4.1%) actually contain a letter; 1,865 carry the message "The cover letter couldn't be generated because the writing model was temporarily unavailable" and an EMPTY cover_letter field, yet GET /agents reports the agent's status as "completed".
**Where:** apps/api/app/agents/cover_letter_agent.py:1513-1528 (LLMUnavailableError → CoverLetterResult(cover_letter_unavailable=True)); surfaced by apps/api/app/routers/agents.py:2129 (GET /agents status)
**OPERATOR:** Decide whether the 1,865 historical rows should be backfilled to a truthful status or left as-is with a documented caveat.
**Fix:** An LLMUnavailableError is an infrastructure FAILURE, not a graceful degrade — record status='failed' (or a distinct 'degraded' enum value) rather than 'completed'. Keep the guard-rejection path ('withheld', 55 runs) as completed since that is the guard working as designed, but separate the two so /agents and the catalog stop reporting an upstream outage as a healthy completion.

## [CRITICAL] AG-02
**What:** A board-sweep autopilot loop burned 1,645 coverLetter runs across 2026-07-27/28 against 5 job ids (≈278 runs per job) and produced ZERO letters. 1,883 of 2,132 coverLetter runs are systemRun (autopilot), not user-initiated.
**Where:** apps/api/app/workers/board_sweep.py (RT-007 autopilot tick, every 10 min per apps/api/app/workers/settings.py:31)
**Fix:** The letterless-failure backoff at board_sweep.py:98-111 (max_cover_failures, default 3, 24h window) demonstrably did not fire — verify the predicate at board_sweep.py:269 actually matches the LLMUnavailable degrade shape (`output->'coverLetterUnavailable' = 'true'`), since AG-01's degrade writes BOTH `cover_letter_unavailable` and `coverLetterUnavailable` and 55 rows write only the camelCase key. Add a hard per-job attempt ceiling independent of shape matching.

## [CRITICAL] TAIL-01
**What:** The loop has NEVER reached its 85 target in production. It always burns all 5 iterations and stops far short — the "loops until ATS >= 85" claim is aspirational, not observed behaviour. Total lift is ~1-4 points per run.
**Where:** apps/api/app/services/tailoring_loop.py:202-203 (the break that never fires); production data in aether."Resume".sections->'tailoringIterations'
**OPERATOR:** Decide whether the product claim "tailors until ATS >= 85" must be removed from UI/marketing copy until convergence is demonstrable.
**Fix:** Either (a) treat 85 as a stretch goal and stop advertising convergence, or (b) attack the real bottleneck: experience_gap is pinned at 100.0 and keyword_match is only 35-40 — the gap keywords being chased are unattainable noise (see TAIL-03), so more iterations cannot help. Consider scoring-corpus and keyword-extraction fixes before adding iterations.

## [CRITICAL] TAIL-02
**What:** The ATS before/after summary is never persisted. `_compute_conversion_metrics` runs AFTER the Resume row is created and its output is only assigned to the in-memory `TailorRunResult`. A page reload has no score to show. This is exactly the known RED test, and I reproduced it.
**Where:** apps/api/app/agents/tailor_agent.py:487-505 (create) then :506-509 (_compute_conversion_metrics) then :563 (conversionMetrics=… on the in-memory result only)
**Fix:** Move `_compute_conversion_metrics` above `self._resumes.create(...)` and add `"conversionMetrics": conversion_metrics` to the sections dict written at tailor_agent.py:488-498; or add a follow-up `update_sections` call. Then have GET /resumes surface it and have the web page hydrate the banner from the persisted value.

## [CRITICAL] GAP-EMAIL-01
**What:** There is NO parser anywhere in the codebase that recognises a job-alert email or extracts individual postings from it. Plainly: it does not exist. The only email intelligence is a 4-way LLM triage label; nothing extracts job title, company, location, salary, or job URL from an alert body.
**Where:** apps/api/app/agents/email_agent.py:41-49 (_TRIAGE_SYSTEM — the ONLY email classifier) and apps/api/app/agents/email_agent.py:213-226 (run() modes: triage/draft_reply/draft_follow_up/insights/apply_labels/send — no extract/parse mode)
**Fix:** Add apps/api/app/services/job_alert_parser.py: (a) sender allowlist keyed on From domain (s.seek.com.au, linkedin.com, jobs2web.com, mail.michaelpage.com.au, hire.lever.co); (b) per-source extractor over the text/plain body _decode_body already returns — for Seek, regex the canonical https://au.seek.com/job/<id> anchors and take the two preceding non-empty lines as title/company (proven format above); for LinkedIn, linkedin.com/comm/jobs/view/<id> plus the subject's '<Title> at <Company>' shape; (c) emit the normalized dict shape BaseAdapter already produces (title/company/location/sourceUrl/postedAt/source='email:<vendor>') so it can feed JobRepository unchanged.

## [CRITICAL] GAP-EMAIL-02
**What:** There is NO path from an email to a Job row or an Application row. None. Emails and jobs are two disconnected subsystems.
**Where:** apps/api/app/repositories/job.py:299 (the only INSERT INTO "Job") ← reached only from apps/api/app/agents/scout_agent.py:56,66 via apps/api/app/services/discovery/adapter_registry.py:44-58, which contains no email source
**Fix:** Register an email-sourced ingest that calls the existing JobRepository upsert with source='email:seek'/'email:linkedin' and dedupHash/sourceUrl set from the canonical job URL, so the existing (userId,sourceUrl) ON CONFLICT dedup at repositories/job.py:299-320 applies. That alone makes alerts flow into the jobs feed; from there the existing Apply path (routers/jobs.py:602-660) already produces Applications with its tailored-resume + cover-letter gates intact.

## [CRITICAL] SUB-001
**What:** Nothing is ever transmitted to an employer. "Submitted" is purely a local Postgres status label. There is no HTTP submission to any ATS and no application email anywhere in the codebase.
**Where:** apps/api/app/routers/jobs.py:587-678 (submit_application_for_job — the ONLY submission write); apps/api/app/agents/submission_agent.py:98
**OPERATOR:** Product decision on channel (recruiter email vs per-ATS API) and, for the ATS route, obtaining employer-side API credentials — neither is achievable from inside the codebase.
**Fix:** Decide the real channel and build it: (a) email-to-recruiter — add an employer/apply-email column to Job, populate it from the source adapter, and reuse the proven _execute_email_send + resolve_email_attachments path; and/or (b) per-ATS API submission (Greenhouse/Lever/Ashby all have documented candidate-submission endpoints requiring per-employer keys). Until one exists, rename the state to 'marked_applied' so no UI, agent message, or funnel claims transmission.

## [CRITICAL] SUB-002
**What:** POST /approvals/{id}/execute is a stub for type='application_submit': it claims the idempotency slot, then returns {"status":"executed"} without performing any action. Only 'email_send' does real work.
**Where:** apps/api/app/routers/approvals.py:250-279 (specifically line 270-272)
**Fix:** Either implement _execute_application_submit against the real channel from SUB-001, or make the endpoint return an honest 501/409 for application_submit instead of the word "executed", so no caller can record a transmission that did not happen.

## [CRITICAL] SUB-003
**What:** No resume is ever attached to anything on the submission path. Application.resumeId is a foreign key into Resume — a pointer, not an attachment. The only attachment-building code is unreachable from any application flow.
**Where:** apps/api/app/routers/applications.py:441 / apps/api/app/routers/jobs.py:552-566 (resumeId is only ever selected and stored); apps/api/app/routers/approvals.py:314-333 (the only attachment builder)
**Fix:** Once SUB-001 has a channel, call resolve_email_attachments(current_user, resume_id=application.resumeId, cover_letter_id=application.id) from the submission path — the PDF rendering (services/resume_pdf.py, routers/cover_letters.py:998) already exists and is proven.

## [CRITICAL] SUB-004
**What:** There is no recipient to send to. The Job schema has no employer/recruiter/apply-email column, and nothing derives one from the job posting.
**Where:** aether."Job" table (24 columns); apps/api/app/repositories/job.py:296-330 (the only INSERT INTO "Job")
**Fix:** Add Job.applyEmail (nullable) + adapter extraction where the source exposes it, or resolve a recruiter Contact per job via the existing Contact/CRM table; make absence of a recipient an honest 422 rather than a silent success.

## [CRITICAL] Q5-PROB-001
**What:** The Analytics page shows a green 60% ring labelled "Your Job Probability Score" captioned "Likelihood of landing an offer in the next 60 days", tooltip "An estimate of your likelihood of landing an offer, blending your fit scores, application activity, and current market conditions." It is not a probability of anything. It is round(mean(app_volume, market_demand, interview_rate, skill_match)) where app_volume = min(100, total_apps/30*100) and market_demand = min(100, jobs_sourced/50*100) — both of which are capped at 100 by merely having applied a lot and having had a lot of jobs scraped. It has never been calibrated against a single outcome. It tells a user with 49 applications, 0 interviews and 0 offers that they have a 60% chance of an offer, and it says "current market conditions" in the SAME response that reports marketDataConnected: false.
**Where:** apps/api/app/routers/analytics.py:544-567 (computation), :651-656 (label + note); apps/web/src/components/analytics/MarketPulse.tsx:176-217 (green ring + tooltip)
**OPERATOR:** Product decision: remove vs. rename. This is the single most misleading number in the product.
**Fix:** Delete the score, or demote it to a non-probability activity indicator. There is no data on this platform from which an offer probability could be fit (zero positive outcomes in 208 tailor runs / 49 applications). If a composite is kept, it must be renamed to what it is ("Pipeline activity index"), lose the % and the ring, lose the "likelihood of landing an offer" caption, and carry "not calibrated against outcomes". The "Market demand" factor must be renamed "Jobs sourced for you" since it consults no market.

## [CRITICAL] GT-01
**What:** [VERIFIED] No job application has EVER been submitted to an employer. `ApprovalRequest."executedAt"` is NULL on all 133 rows, and even if `/approvals/{id}/execute` were called, the `application_submit` branch is a no-op stub that returns `{"status":"executed"}` without performing any submission. The product's terminal, entire-value-proposition step has never fired once.
**Where:** aether."ApprovalRequest".executedAt (133/133 NULL); apps/api/app/routers/approvals.py:271
**OPERATOR:** Decide product direction: real auto-submit vs. honest hand-off. 86 Applications currently read 'submitted' to the user and none were.
**Fix:** Either build a real submission integration (per-ATS apply endpoints or a supervised browser-driven flow) behind the `application_submit` branch, or make the UI and the `Application.status='submitted'` enum stop claiming submission happened — rename to 'ready_to_submit' and surface an explicit "you must apply manually" step with the job's sourceUrl.

## [CRITICAL] GT-02
**What:** [VERIFIED] Job sourcing is dead. 669 scout runs have persisted 53 jobs in total; 41 of those landed on day one (2026-07-21). In the last 48 hours 70 scout runs persisted ZERO new jobs. The board is stale and the only user's feed cannot grow.
**Where:** aether."AgentRun" agentName='scout'; aether."JobSourceStatus"
**OPERATOR:** Supply Adzuna app_id/app_key (status='skipped' implies missing config) and decide LinkedIn/Indeed policy.
**Fix:** Three separate problems: (a) 6 of 10 sources return nothing (3 hard-skipped incl. Adzuna, 1 timing out, 1 403-blocked, workable/remotive empty); (b) the 3 working ATS sources poll a static, exhausted company list — 36 fetched / 0 new every sweep; (c) nothing alerts on a 12-day zero-yield streak. Rotate/expand the company list, wire Adzuna credentials, and add a 'no new jobs in N sweeps' alarm.

## [CRITICAL] GT-03
**What:** [VERIFIED] The cover-letter agent records failure as success. 1921 of 2004 `status='completed'` runs (95.9%) returned 'the writing model was temporarily unavailable' and produced no letter. Only 83 completed runs ever emitted a real letter. A runaway on 2026-07-27/28 burned 1645 runs and produced zero Applications and zero Application updates on either day.
**Where:** aether."AgentRun" agentName='coverLetter' status='completed'
**OPERATOR:** Check the OpenRouter/provider credential health — billingAudit says provider='openrouter', authMode='api_key', credentialSource='database'.
**Fix:** An unavailable-model result must set `AgentRun.status='failed'` with the error, not 'completed'. Add a circuit breaker so a repeated provider failure stops the retry loop instead of issuing 800+ no-op runs/day. Every dashboard counting 'completed coverLetter runs' is currently reporting ~24x reality.

## [HIGH] SRC-02
**What:** [VERIFIED] The producing corpus is 54 hardcoded company tokens in static module-level tuples. Confirmed: this is exactly why the same 36 recur. The pool's total AU+on-target capacity is 17 postings, so the board's ceiling is fixed and new rows appear only when one of those 54 employers happens to post a matching role (~1 every 2-3 days).
**Where:** apps/api/app/services/discovery/portals.py:37 (GREENHOUSE_BOARDS, 26 entries), :76 (LEVER_COMPANIES, 8), :98 (ASHBY_BOARDS, 15), :125 (WORKABLE_ACCOUNTS, 5)
**Fix:** CODE-ONLY/CONFIG-ONLY but LOW YIELD for AU — do not treat this as the fix. I probed 38 plausible unconfigured AU employer tokens: 35 returned HTTP 404 (atlassian, canva, rea-group, airtasker, linktree, employmenthero, zeller, safetyculture, myob, carsales, xero, tyro on Greenhouse; canva/atlassian/linktree/zeller/shippit/koala on Lever; Canva/Atlassian/Zeller/Linktree/Immutable on Ashby), and the 3 that resolved (greenhouse 'up' raw=2, lever 'airtasker' raw=0, ashby 'Airtasker' raw=8) yielded 0 relevant AU roles. Most AU employers use Workday/SmartRecruiters/PageUp, which have no adapter here. Adding tokens is worth doing opportunistically via the env vars (no deploy needed) but it cannot close the gap.

## [HIGH] SRC-03
**What:** [VERIFIED] The user-visible board is not merely static, it is EXHAUSTED: 30 of the 52 persisted jobs are already `applied` and 4 are `archived`, and active_feed excludes both, so /jobs returns 18 rows — with zero greenhouse rows because all 20 greenhouse jobs have been applied to. This is what 'the board never gets new jobs' actually looks like to the user.
**Where:** apps/api/app/services/discovery/active_feed.py:192 (_TERMINAL_JOB_STATUSES) and :218; DB table aether."Job"
**Fix:** No code fix — this is a supply problem, and it is the reason SRC-01 is urgent. Any honest remediation must add NEW inbound volume (Adzuna), not re-surface applied rows. A UI note ('X of Y discovered roles already applied to') would at least make the exhaustion legible instead of reading as a broken feed.

## [HIGH] SRC-04
**What:** [VERIFIED] The Workable adapter can never produce a job, even from an account that has jobs: the public v3 payload contains no `url`, `application_url` or `shortlink`, so every posting is dropped by the apply-URL guard. Separately, all 5 configured accounts are empty, and the adapter's pagination docstring is factually wrong.
**Where:** apps/api/app/services/discovery/workable_adapter.py:76-83 (apply_url guard) and :31-38 (false pagination claim)
**Fix:** CODE-ONLY: (a) build the apply URL from the fields that do exist — `https://apply.workable.com/<account>/j/<shortcode>/` — instead of the three absent keys; (b) follow the `nextPage` cursor (currently truncating at 10/account); (c) drop the `query` from the POST body or send a single term (the production body is the whole 200-char comma query — blueground total fell 28→25 with it); (d) replace the 5 dead accounts, verifying each with `GET /api/v1/widget/accounts/<sub>?details=true` (jobs>0) before adding. Correct the docstring — it currently asserts a verified-sounding falsehood.

## [HIGH] AG-03
**What:** The `notification` agent has NEVER executed once in production. Its run() creates the NotificationDigest table on first use, and that table does not exist in the schema — conclusive proof of zero executions. Yet GET /agents/catalog reports it status="active", runnable=true, and counts it in "22 active / 0 error".
**Where:** apps/api/app/agents/notification_agent.py:173 (run) / :96-117 (ensure_notification_digest_table); catalog status assignment apps/api/app/routers/agents.py:2911-2913
**Fix:** Two things: (a) run the agent once end-to-end against the real account to prove the code path (it will queue an approval, not send); (b) make the catalog's `state` distinguish never-run from healthy — the `else: state='active'` branch at agents.py:2911 currently paints a never-executed agent the same green as a working one.

## [HIGH] AG-04
**What:** The `submission` agent has NEVER executed once in production, despite being the agent that performs the product's terminal action (submitting an application). The catalog reports it active+runnable.
**Where:** apps/api/app/agents/submission_agent.py:87 (run) → app.routers.jobs.submit_application_for_job
**OPERATOR:** Human approval needed: any submission run sends a real application. I deliberately did not run it.
**Fix:** Execute one supervised run against the known-good top candidate (its cover letter is clean — verified signature "Sincerely, Vikram Deshpande") to prove the path, then wire it into the autopilot per task #19. Note two of the 4 ready candidates carry probe-signed letters (see AG-08) — fix that first.

## [HIGH] AG-05
**What:** emailAgent draft_reply ROLE INVERSION — it drafts the reply as the counterparty writing TO the user, instead of the user's reply. 4 of 10 stored drafts are addressed to "Vik"/"Vikram" and signed by the recruiter.
**Where:** apps/api/app/agents/email_agent.py:213 (run, mode='draft_reply'); prompt/model call at email_agent.py:407 / :425 (get_model("REASONING"))
**Fix:** The prompt does not pin WHO is replying. Determine the last message's sender vs the user's own address (GmailAccount.googleEmail) and state the speaker explicitly in the system prompt; add a post-generation assertion that the salutation is not the user's own name and the signature is not the counterparty's.

## [HIGH] AG-06
**What:** scout and fitScorer are green but functionally dead: 668 + 679 runs over 12 days have yielded 53 net-new jobs total (41 of them on day one) and the last 8 days produced 3 new jobs and 2 new scores across ~740 runs. Half the configured sources are skipped or blocked.
**Where:** apps/api/app/agents/scout_agent.py:52; apps/api/app/agents/fit_scorer.py:45; scheduled by /etc/systemd/system/aether-discovery.timer → scripts/discovery_cron.sh
**Fix:** This is task #23/#24 territory. Every 30 min the timer re-fetches the SAME 36 postings from 3 static company lists (greenhouse 14, lever 8, ashby 14) and persists 0. Enable Adzuna (currently 'skipped'), broaden the static company lists, and add a discovery-yield alarm so 300 consecutive zero-persist runs surfaces as an incident instead of 668 green rows.

## [HIGH] AG-07
**What:** tailor applies ZERO changes in 120 of 207 completed runs (58%), and when it does apply changes it applies 1-2 and misses its own stated ATS target of 85 by 30-45 points.
**Where:** apps/api/app/agents/tailor_agent.py:414 (run); NoChangesApplied at tailor_agent.py:279
**Fix:** The rejected[] arrays show the guard is rejecting nearly every proposed edit as unsupported — the loop generates claims the résumé cannot entail. Either feed the résumé corpus into generation more tightly so proposals are entailment-safe by construction, or lower/retire the advertised ATS-85 target, which the product has never once reached (task #3 claims this workstream is complete).

## [HIGH] AG-08
**What:** BLOCKER-002 is LIVE in production data, on the REAL user's account: 8 Application rows carry cover letters signed "GAP-P7-DEF-B Probe <timestamp>" instead of the user's name — and 5 of those 8 are already status='submitted'.
**Where:** aether."Application"."coverLetter" (8 rows, userId c6c8d0163d973a8048e7e33b8); source runs in aether."AgentRun" agentName='coverLetter'
**OPERATOR:** 5 applications with a probe-signed cover letter have ALREADY been submitted to real employers. Operator must decide on remediation/outreach; I made no writes.
**Fix:** Find and remove the probe signer injection point (the signer resolution in cover_letter_agent.py — PlaceholderSignerError at :1200 exists to catch exactly this and did not fire for these two runs), then remediate the 8 stored rows. The 2 draft rows are also ready-to-submit candidates for the SubmissionAgent (AG-04), so an autopilot submission could mail a probe-signed letter.

## [HIGH] CL-SCORE-001
**What:** [VERIFIED] There is NO scoring loop for cover letters. The drafting loop's exit condition is a pure boolean AND of four pass/fail guards — no score, no target threshold, no best-of-N selection, no iteration record. This is categorically different from the resume, which is score-aware.
**Where:** apps/api/app/agents/cover_letter_agent.py:1531-1537 (loop) vs apps/api/app/services/tailoring_loop.py:52,55,168-209
**Fix:** Introduce a deterministic CoverLetterScorer (JD keyword coverage + evidence grounding + structure) and wrap `_draft` in a score-aware loop mirroring TailoringLoop: score every draft, keep the best, retry while below target and iterations remain, and record per-iteration scores. Reuse `_keyword_coverage` (cover_letters.py:526) so the loop's decisions and the studio's displayed number are computed identically — exactly the invariant tailor_agent.py:347-351 documents for the resume.

## [HIGH] CL-SCORE-002
**What:** [VERIFIED] The anti-fabrication guard's dominant production effect on cover letters is total deletion, not improvement. Because there is no score to optimise and no partial-credit degrade, any surviving flag after 2 retries raises FabricationError and the user gets NO letter — the opposite of the resume path's documented CONVERGE-BUT-FLAG policy, which always returns the best bullets and only withholds the success verdict.
**Where:** apps/api/app/agents/cover_letter_agent.py:1598-1604 (raise FabricationError) vs apps/api/app/services/tailoring_loop.py:211-229 (converge-but-flag)
**Fix:** Adopt the resume's CONVERGE-BUT-FLAG semantics: on residual claim_flags after the final retry, return the best draft with an explicit `requiresReview` + the flagged terms surfaced in the studio for the human to edit, instead of discarding the artifact. Reserve hard rejection for FabricationGuard entity/metric hits (genuine invented facts), not for lowercase JD-vocabulary claim flags which are a soft over-claim signal.

## [HIGH] TAIL-03
**What:** Iterations 2..N are frequently exact no-ops: the retry directive is a pure function of (score, gapKeywords) and the LLM runs at temperature=0.0, so a pass that changes nothing hands the NEXT pass a byte-identical prompt and gets a byte-identical answer. Users are billed for LLM passes that provably re-score identical text.
**Where:** apps/api/app/services/tailoring_loop.py:208-209 and :283-309 (_build_directive); apps/api/app/services/resume_tailor.py:2137 (temperature=0.0)
**Fix:** Break out of the loop when an iteration yields 0 changes AND the directive is unchanged from the previous pass (or vary the directive/temperature/seed between passes). Also filter the gap keywords: the live list included 'decagon' (the company name), 'nbsp' (an HTML entity), 'own', 'end', 'every', 'remote' — clean_gap_keywords (tailoring_loop.py:66-89) only drops <=2-char tokens, contraction fragments and a 5-word _GENERIC_NOISE set, so unattainable noise is fed to the model as a target.

## [HIGH] TAIL-04
**What:** There are THREE different ATS numbers for the same tailored resume, and the one the user sees after reload is ~10 points higher than the one in the before/after banner. Nothing reconciles them.
**Where:** apps/api/app/agents/tailor_agent.py:433 (loop JD = title+company+description) vs :508 (conversion JD = description only) vs apps/api/app/routers/resumes.py:171 (ATSEngine().score(raw_text, description))
**Fix:** Pick one canonical (corpus, job_description) pair. The loop and _compute_conversion_metrics must at minimum use the identical JD string; and the loop's `_corpus` (strip_bullet_lines(resume_text)+bullets, tailoring_loop.py:274-281) should match what /resumes/{id}/ats scores (the persisted raw_text) or the divergence will persist.

## [HIGH] TAIL-05
**What:** The ARQ worker — which actually executes every tailoring run, since AETHER_ASYNC_GENERATION=true — is running stale in-memory code predating the commit that added semanticPath / iterations / gapKeywords / degradation flags. So the newest features are dead in production even though they are on disk.
**Where:** aether-worker.service (pid 3093457, started 2026-07-31 16:57:25) vs apps/api/app/services/tailoring_loop.py (mtime 2026-07-31 18:49:41) and apps/api/app/agents/tailor_agent.py (mtime 2026-07-31 18:48:37)
**OPERATOR:** Operator must restart aether-worker.service — I am read-only and did not restart anything.
**Fix:** Restart aether-worker (and rebuild aether-web — see TAIL-07) as part of the deploy procedure; add a version/commit stamp to the worker's job results so staleness is detectable from the response.

## [HIGH] GAP-EMAIL-03
**What:** The system cannot express a date range at all. GmailService.list_threads takes a Gmail `q` string, but no production caller ever passes one, and max_results is hardcoded to the default 25. 'Last 7 days' is not requestable through any API, agent mode, or UI control.
**Where:** apps/api/app/services/gmail_service.py:504-520 (list_threads signature + .list(userId="me", q=query, maxResults=max_results)); callers: apps/api/app/routers/workspaces.py:493 and apps/api/app/agents/email_agent.py:234
**Fix:** Thread a query through: add `since_days: int | None` to the inbox/agent entry points, build `newer_than:{n}d` (optionally `in:anywhere`), pass it to sync_threads_to_db(query=..., max_results=...), and raise max_results with pagination — 25 is too small for a real 7-day sweep on the secondary account (312 messages in that window).

## [HIGH] GAP-EMAIL-04
**What:** The Email Agent reads ONLY the primary inbox. Its triage mode never touches the second account — which is exactly the account holding almost all of the Seek job alerts.
**Where:** apps/api/app/agents/email_agent.py:118-123 (_gmail_for returns GmailService(user_id) with no account_id) → apps/api/app/services/gmail_service.py:369-372 → apps/api/app/repositories/gmail_account.py:269-274 (ORDER BY "isPrimary" DESC, "createdAt" ASC LIMIT 1)
**Fix:** Mirror the workspaces.py:490-496 pattern in EmailAgent: iterate GmailAccountRepository().list_accounts(user_id) and construct GmailService(user_id, account_id=acc['id']) per inbox, accumulating `synced`; degrade per-account on GmailAuthError exactly as the inbox route already does.

## [HIGH] GAP-EMAIL-05
**What:** Gmail's default search scope excludes TRASH and SPAM, and 95 of the 101 job-board/ATS messages from the last 7 days are in Trash. The code passes q=None, so the app sees ~6% of the owner's job-alert mail — a parser bolted on today would still miss almost everything.
**Where:** apps/api/app/services/gmail_service.py:518 — `.list(userId="me", q=query, maxResults=max_results)` with query always None; no `in:anywhere`
**OPERATOR:** Confirm it is acceptable to read Trash. These messages are in Trash — I cannot tell from the API whether the owner deleted them deliberately or a Gmail filter did; mining Trash is a product decision, not a code one.
**Fix:** Once GAP-EMAIL-03 lands, pass a scope-explicit mining query such as `in:anywhere newer_than:7d from:(jobmail@s.seek.com.au OR jobalerts-noreply@linkedin.com OR noreply10.jobs2web.com OR noreply@mail.michaelpage.com.au)` for the alert-mining sweep, kept separate from the human-facing inbox sync (which should stay Inbox-scoped so Trash doesn't pollute the Email Center).

## [HIGH] SUB-005
**What:** In production the entire agent-pipeline half of the kanban is empty and unreachable: all 18 jobs the feed returns have status='ready', which maps to NO board column.
**Where:** apps/web/src/components/applications/tracker-lib.ts:113-118 (JOB_STAGE has no 'ready' key) vs apps/api/app/agents/cover_letter_agent.py:1685-1690 (advances Job to 'ready')
**Fix:** Either add 'ready' to JOB_STAGE (mapping to the 'ready' column) or stop cover_letter_agent from advancing Job to a status the board cannot render. Note the suppression at tracker-lib.ts:231 (`!appJobIds.has(j.id)`) currently masks it, since all 18 'ready' jobs happen to have applications.

## [HIGH] SUB-006
**What:** Two of the three paths that set Application.status='submitted' never advance the parent Job, leaving 19 applications 'submitted' under a Job still marked 'ready'. The Applied/History view consequently shows 30 of the 48 submitted cards.
**Where:** apps/api/app/repositories/approval.py:292-317 (_sync_application) and apps/api/app/services/stage_transitions.py:214-220 (the UPDATE) — neither touches Job; contrast apps/api/app/routers/applications.py:560-567 and apps/api/app/routers/jobs.py:676 which do
**Fix:** Move the Job advance into the shared layer: have _sync_application and move_application_stage call JobRepository().advance_status(job_id,'applied', allowed_from={discovered,screening,matched,tailoring,ready}) whenever the new Application status leaves 'draft', matching applications.py:560-567.

## [HIGH] SUB-007
**What:** Dragging a card from "Ready to Apply" to "Submitted" on the kanban bypasses every submission gate — no tailored-resume check, no cover-letter check, no approval check. It just relabels the row.
**Where:** apps/api/app/services/stage_transitions.py:133-250 (no gate between the CLOSED_STATUSES check at :173 and the UPDATE at :214)
**Fix:** Apply the same gate the two submit endpoints use when new_status leaves 'draft' (or make the promotion route through submit_application_for_job), so a drag cannot produce a 'submitted' row that POST /applications/{id}/submit would have 422'd.

## [HIGH] SUB-008
**What:** The Submission Agent is not approval-gated, by explicit design — but that is moot today, and the agent has never executed in production even once.
**Where:** apps/api/app/routers/agents.py:104-107 (_APPROVAL_GATED omits 'submission'); apps/api/app/routers/agents.py:1157 (approvalRequired = agent_name in _APPROVAL_GATED)
**Fix:** If SUB-001 is ever built, 'submission' MUST be added to _APPROVAL_GATED before the first real transmission. Today the honest statement is that the gate is irrelevant because the agent performs no external act — and that the agent card advertises a capability that has never once run.

## [HIGH] RT-PROP-001
**What:** The only realtime transport in the system is completely unused by the UI. Zero frontend code opens the SSE stream, so all the concurrency caps, heartbeats, kanban_updated evidence gating and slot accounting are dead weight in production.
**Where:** apps/api/app/routers/agents.py:2171 (endpoint) vs apps/web/src — 0 consumers
**Fix:** Either wire the stream into the agents screen (replacing the 3s startPolling loop) or delete/flag it. It cannot be wired as-is — see RT-PROP-004 and RT-PROP-005.

## [HIGH] RT-PROP-002
**What:** Nine screens fetch once on mount and never again, so a change written by a background agent is invisible until the user manually reloads: dashboard home, analytics, approvals, cover-letters, email, interviews, networking, offers, resume.
**Where:** apps/web/src/app/dashboard/page.tsx:102-121 (useLoad, deps []); analytics/page.tsx:69; approvals/page.tsx:95; cover-letters/page.tsx:143; email/page.tsx:127; interviews/page.tsx:176; networking/page.tsx:67; offers/page.tsx:34; resume/page.tsx:112
**Fix:** Two-line change per screen: import usePolling from ../../../hooks/usePolling and replace `useEffect(() => { void load(); }, [load])` with `usePolling(load, 20_000)` (pass restartKey for the filter/period screens: approvals -> filter, analytics -> period). The hook already handles mount fetch, visibility pause and catch-up. Next's app router mounts one dashboard page at a time, so the added cost is ~1 request/20s/user, identical to what jobs/applications/stories already spend.

## [HIGH] RT-PROP-003
**What:** The Agents screen — the one place a user watches agent activity — only polls while a run THIS tab started is in flight, and stops the moment that call returns. Runs started by the discovery timer, the board sweep, or another tab never appear until reload.
**Where:** apps/web/src/app/dashboard/agents/page.tsx:225-259 (startPolling), called only at :265 (pipeline) and :292 (trigger), cleared in the finally blocks at :272 and :300
**Fix:** Add a baseline `usePolling(load, 20_000)` alongside the existing 3s burst poll, so the screen stays current on background activity and only escalates to 3s during a locally-started run.

## [HIGH] RT-PROP-004
**What:** The SSE endpoint cannot be consumed by a browser EventSource at all: it is Bearer-header-only, the JWT lives in localStorage (not a cookie), and EventSource cannot set request headers. A token in the query string is rejected.
**Where:** apps/api/app/middleware/auth.py:13,33,58 (OAuth2PasswordBearer -> get_current_user -> CurrentUser) + apps/web/src/lib/api/client.ts:14,203
**Fix:** Pick one: (a) consume the stream with fetch() + ReadableStream + TextDecoder — headers work, but you must write a ~40-line SSE frame parser (none exists in the repo); or (b) add a short-lived, single-use stream ticket accepted as a query param and exchanged for the user (keeps the long-lived JWT out of URLs/access logs). Do NOT put the raw JWT in the query string.

## [HIGH] Q1-RELOAD-002
**What:** The resume's "ATS Conversion Impact" panel (Before X% -> After Y% + estimated lift) is the ONLY place a before/after ATS pair is ever shown, and it lives exclusively in React state set by the tailor run. It does not survive a reload, a tab close, or navigating away. The numbers ARE persisted in AgentRun.output.conversionMetrics, and Resume.sections.tailoringIterations holds every per-iteration score — but no endpoint or UI reads either back. The user permanently loses the before/after evidence for every resume they have ever tailored.
**Where:** apps/web/src/app/dashboard/resume/page.tsx:90 (useState), :135 and :144 (the only two setConversion call sites, both inside runTailor), :376-423 (render); no rehydration anywhere
**Fix:** Add GET /resumes/{id}/conversion (or fold baseline/tailored into GET /resumes/{id}) that reads the persisted AgentRun.output.conversionMetrics for that resume_id, and have openResume() populate the panel from it — mirroring how the ATS Score panel already rehydrates.

## [HIGH] Q1-DIVERGE-003
**What:** Two panels on the SAME Resume Studio page report two different ATS scores for the SAME resume version against the SAME job, ~10 points apart, with no indication they are different measurements. "ATS Conversion Impact" says After: 43.46%; "ATS Score" says 53.3. Cause: _compute_conversion_metrics scores `strip_bullet_lines(original_text) + bullet text`, while GET /resumes/{id}/ats scores `sections.raw_text` (the full rendered tailored resume, 7215 chars vs 25 bullets). Whichever the user reads last is the one they believe.
**Where:** apps/api/app/agents/tailor_agent.py:95-102 (_corpus = context + bullets) vs apps/api/app/routers/resumes.py:162-164 (text = sections.raw_text)
**Fix:** Pick ONE corpus definition and use it in both places. tailoring_loop.py:274-281 already documents the intent ("the SAME like-for-like corpus _compute_conversion_metrics scores, so the loop's convergence decisions match what the UI ultimately shows") — resumes.py:162 breaks it by preferring raw_text. Either score raw_text in _compute_conversion_metrics, or have /resumes/{id}/ats use strip_bullet_lines(parent raw_text) + this version's bullets.

## [HIGH] Q5-LIFT-004
**What:** "Estimated interview conversion improvement: +0.2%" is arithmetic on an assumption presented as a business outcome. lift = ((tailored - baseline)/baseline) * 2.5%, where 2.5% is a hardcoded constant (_DEFAULT_POPULATION_BASELINE_RATE) with no cited source, no study, and no connection to this user's data. The methodology string shown to the user says "Like-for-like ATS delta (shared context) x population baseline (2.5%)" and confidence is the string "model-estimated" — but no model estimated it; it is a multiplication by a literal.
**Where:** apps/api/app/agents/tailor_agent.py:41 (_DEFAULT_POPULATION_BASELINE_RATE = 0.025), :106-112 (lift), :130-132 (methodology/confidence); apps/web/src/app/dashboard/resume/page.tsx:403-412
**Fix:** Remove the figure, or relabel to "ATS score change: +3.4 points (40.0 -> 43.5)" and drop the x2.5% entirely. If a lift must stay, the label must name the assumption inline: "assumes an unvalidated 2.5% baseline conversion rate — not derived from your data". Change confidence from "model-estimated" to "assumption-derived".

## [HIGH] Q5-DIMS-005
**What:** Four of the ten "fit dimensions" on the Jobs radar chart are hardcoded constants, and three more are relabels of the same three ATS sub-scores dressed up as unrelated concepts. Location Match = 100/95/70 by remote/AU flag. Company Stability = a lookup table keyed on the JOB BOARD (greenhouse 86, indeed 78, remoteok 72) + 6 if a salary is listed — it measures nothing about the company. Salary Fit = a band hardcoded in a comment as "AUD 150k-260k for the demo profile", returning 70 when salary is absent; no salary preference is stored anywhere (CareerProfile has no salary column). Culture Fit = 0.5*semantic + 0.5*experience_gap. North Star Align = 0.6*overall + 0.4*semantic. Career Growth = 0.6*seniority_keyword(title) + 0.4*overall. All ten render identically in the radar polygon and the dimension list.
**Where:** apps/api/app/routers/jobs.py:148-152 (_SOURCE_STABILITY), :176-182 (_seniority_score), :184-198 (_salary_fit incl. the "demo profile" comment), :371-377 (the six derived dims), :388-399 (dimension list); apps/web/src/app/dashboard/jobs/page.tsx:258-290 (RadarChart), :1462-1465
**OPERATOR:** Product decision on whether a 10-point radar is worth keeping when only 4 points are real.
**Fix:** Split the panel: render only the genuinely measured dimensions (Technical Skills, Experience Level, Industry Match, Role Alignment) in the radar; move Salary Fit / Location Match / Company Stability out as plain factual chips ("Remote", "Salary not listed", "via Greenhouse") with no score; delete Culture Fit and North Star Align, or rename them to disclose they are re-blends of the ATS sub-scores already shown.

## [HIGH] GT-04
**What:** [VERIFIED] The ATS≥85 promise has never been met, and 80% of tailored resumes carry no persisted score at all. Zero resumes contain an `atsScore` key. Only 18 of 88 tailored resumes carry `sections->tailoringIterations` with a score; the highest score ever recorded across all of them is 54.88, and none reaches 85.
**Where:** aether."Resume".sections
**Fix:** Two issues: the loop terminates at 5 iterations far below target (a real ceiling, not a persistence bug — scores plateau at 40.12/40.12 within one resume), and there is no top-level `atsScore` column/key so the UI cannot show a resume's score without walking the iteration array. Persist a first-class score and investigate why the scorer caps in the 40s.

## [HIGH] GT-05
**What:** [VERIFIED] Fifteen production cover letters are signed with test-harness identities: 8 signed with a probe token ('GAP-P7-DEF-B Probe 1785452243543' / '...1784823962960') and 7 signed 'Administrator'. The most recent probe-signed letter is dated 2026-07-31 — this is live, not historical.
**Where:** aether."Application".coverLetter
**OPERATOR:** Approve deletion of the 15 contaminated Application rows.
**Fix:** The signature is taken from `User.name` with no validation. Given GT-01 none of these ever reached an employer, but the letters are user-visible. Purge the 15 contaminated rows and make the signer fall back to a validated profile name rather than whatever string the account carries.

## [HIGH] GT-06
**What:** [VERIFIED] Duplicate-application storm. 92 Applications cover only 49 distinct jobs; one single job has 32 Applications against it. Job dedup is entirely inert — `Job.dedupHash` is NULL on all 52 rows.
**Where:** aether."Application" (jobId); aether."Job".dedupHash
**Fix:** Add a unique constraint (or upsert) on (userId, jobId) for non-draft Applications, and populate `dedupHash` on Job insert — the column exists in the schema but nothing writes it. Also note only 17 distinct resumes back 92 applications, so most 'tailored' applications reuse a resume tailored for a different job.

## [HIGH] GT-07
**What:** [VERIFIED] The product has never been exercised by a second real user. Of 15 accounts, 14 have exactly zero Jobs, zero Applications, zero Resumes and zero AgentRuns. Every functional claim about this system rests on a single account — the owner's.
**Where:** aether."User"
**OPERATOR:** Approve purge of the 13 test/probe accounts from production.
**Fix:** Onboarding beyond signup has never been observed to work for anyone but the owner — every probe account stops at 'logged in'. Run one full cold-start journey on a fresh account before any launch claim. Separately, 13 of these are test-data pollution in production (task W-CLEAN).

## [HIGH] GT-08
**What:** [VERIFIED] The Approvals gate is mostly self-approving. Only 24 of 130 approved requests carry a `resolvedByUserId`/`resolvedFromIp`; the other 106 were resolved with no recorded human actor. Combined with GT-01 (0 executed), the human-in-the-loop control is neither exercised nor enforced.
**Where:** aether."ApprovalRequest".resolvedByUserId / resolvedFromIp
**Fix:** Make resolvedByUserId NOT NULL on any transition out of 'pending', so an auto-approval is either impossible or explicitly attributed to a system principal. Audit which code path resolves an approval without an actor.

## [MEDIUM] SRC-05
**What:** [VERIFIED] Wellfound is permanently blocked (Cloudflare 403) yet stays in the live registry, is re-attempted every 30 minutes, and is reported to the FE as `available: true`.
**Where:** apps/api/app/services/discovery/wellfound_adapter.py:38-46 (fetch → SourceBlockedError at :45) → scout_agent.py:75-88; availability logic apps/api/app/services/discovery/adapter_registry.py:138-145
**OPERATOR:** Only if Wellfound sourcing is actually wanted — it would need a commercial/API agreement with Wellfound.
**Fix:** Wellfound has no keyless public JSON API to restore — the URL the adapter fetches (`/role/l/<slug>`) is an HTML page, so `fetch_json` could never have parsed it even at HTTP 200. Either remove it from the live registry (as Seek is) or make `source_availability()` consult the last persisted JobSourceStatus so a permanently-blocked source stops reporting `available: true`. An operator-supplied Wellfound partner/API arrangement would be the only way to make it produce jobs.

## [MEDIUM] SRC-06
**What:** [VERIFIED] LinkedIn and Indeed are permanent no-ops: neither class defines `_fetch_live`, so both inherit the BaseAdapter stub and are skipped on every run forever. They exist only as fixture parsers.
**Where:** apps/api/app/services/discovery/base_adapter.py:102-106 (NotImplementedError stub); linkedin_adapter.py:13-18 and indeed_adapter.py:13-18 define only `_parse`
**OPERATOR:** YES if these sources are genuinely wanted — a LinkedIn Talent Solutions and/or Indeed partner agreement, both commercial.
**Fix:** Neither is fixable in code alone. LinkedIn Jobs data requires a LinkedIn Talent Solutions partnership; Indeed retired its open Publisher API and now requires an employer/partner agreement. Realistic options: keep them honestly unavailable, or reach the same inventory through a licensed aggregator (Adzuna already indexes many Indeed-syndicated AU listings). Do not build a scraper for either.

## [MEDIUM] SRC-07
**What:** [VERIFIED] Remotive and RemoteOK contribute structurally nothing for an AU BA/PM/Scrum candidate — they are small, US-skewed, remote-only boards. Their `fetched:0, status:ok` is honest, not a bug.
**Where:** apps/api/app/services/discovery/remotive_adapter.py:37-40 + :63 (filter_relevant); remoteok_adapter.py:27 + :54
**Fix:** Leave them in — they are free, compliant and occasionally yield a worldwide-remote role. But do not count them as AU coverage in any plan. Note Remotive's own legal notice in the payload caps polling at ~4x/day and prohibits re-syndication; the cron currently hits it 48x/day, which risks the access termination that notice threatens.

## [MEDIUM] SRC-08
**What:** [VERIFIED] `location='Melbourne'` is a dead parameter for every source that currently produces jobs. Only Adzuna (dark) uses it. Geographic targeting is done exclusively by a post-hoc regex, which accepts anything AU/NZ/APAC or unrestricted-remote — so 'Melbourne' in the profile buys nothing today.
**Where:** greenhouse_adapter.py:34, lever_adapter.py:41, ashby_adapter.py:28, remotive_adapter.py:37, remoteok_adapter.py:21 all accept `location` and never reference it; workable_adapter.py:39-45 hardcodes `"location": []`; only adzuna_adapter.py:79+89 uses it (`where = location or "Australia"` → `&where=Melbourne`)
**Fix:** Accept it as designed (per-company ATS boards have no location query), but stop implying otherwise in the UI. The genuine remedy is SRC-01: Adzuna is the only adapter that can push `where=Melbourne` upstream.

## [MEDIUM] AG-09
**What:** recruiterOutreach and reference are registered, runnable and reported "completed", but have NEVER produced a draft — the Contact table is empty (0 rows), so they are structurally incapable of output. Their two honest messages also contradict each other.
**Where:** apps/api/app/agents/recruiter_outreach_agent.py:123; apps/api/app/agents/reference_agent.py:132; drafting helper apps/api/app/agents/outreach_support.py:282-302
**Fix:** Align recruiterOutreach's zero-contact message with reference's ("No contacts yet") — the current wording implies contacts exist but are all threaded, which is false. Then seed a real contact and prove the drafting path end-to-end; right now neither agent's LLM path has ever executed in production (noLlmCall=true on 5/5 runs).

## [MEDIUM] AG-10
**What:** scheduling has run exactly once and produced nothing, and its headline W-CAL capability (Google Calendar free/busy) has never been exercised — the GoogleCredential table is empty.
**Where:** apps/api/app/agents/scheduling_agent.py:207; catalog tip at apps/api/app/routers/agents.py:298-306
**Fix:** The card promises "With Google Calendar connected it proposes windows your real free/busy shows as free" — with 0 GoogleCredential rows that branch has never run. Connect Calendar for the owner account and move one application to Interview to exercise it, or the W-CAL work (task #18, marked complete) remains unproven in production.

## [MEDIUM] AG-11
**What:** sentimentAnalysis's single run produced a hollow output: default tone "neutral", the exact midpoint score 50, empty signals[], and a withheld rationale — because the fabrication guard false-positived on "SEEK", a job board named in the email's own subject line.
**Where:** apps/api/app/agents/sentiment_analysis_agent.py:108 (run) / :175-179 (complete_json, get_model("REASONING"))
**Fix:** The guard is comparing against the wrong corpus for this agent (résumé/JD terms rather than the thread body). Ground the entailment check for sentimentAnalysis on the email thread text it actually read, so brand names present in the source stop being flagged as fabricated.

## [MEDIUM] AG-12
**What:** salaryIntelligence is deterministic, correct, and completely hollow — 0 of 52 discovered postings disclose a salary, so all 35 groups it produces contain nothing but nulls. It has never emitted a single salary figure.
**Where:** apps/api/app/agents/salary_intelligence_agent.py:123
**Fix:** Not an agent bug — the scraper never populates Job.salaryMin/salaryMax for any of the 5 live sources. Either extract pay from the posting body/structured fields in the discovery layer, or mark the card as data-blocked rather than active so the Agents screen stops implying it is producing salary intelligence.

## [MEDIUM] AG-13
**What:** The `supervisor`/Orchestration agent has no standalone run path — POST /agents/supervisor/run returns 404 — yet it is listed in GET /agents as agent #1 with status "completed", and the sidebar counts it in its "N agents ready" pulse.
**Where:** apps/api/app/routers/agents.py:1779 (`raise HTTPException(404, f"Unknown agent '{name}'")` — supervisor has no branch in _agent_callable); only invoked inline at agents.py:2571-2572 inside _pipeline_core; sidebar copy at apps/web/src/components/sidebar.tsx:165
**Fix:** The 'supervisor' node is a hardcoded plan literal (_PIPELINE_PLAN at agents.py:2551), not a planner — it does no sequencing decision. Either give it a real run path or stop presenting it as a 20th agent in the pulse count; today "20 agents ready" includes one that cannot be run and one (notification) plus one (submission) that never have been.

## [MEDIUM] CL-SCORE-003
**What:** [VERIFIED] The one quality number that exists (`grounding_confidence`) is computed exactly once, AFTER the letter is already final and immutable. It is a post-hoc label, structurally incapable of influencing the letter. Nothing else consumes it.
**Where:** apps/api/app/agents/cover_letter_agent.py:987-1003 (definition), :1037 (sole call site, inside build_approval_extras)
**Fix:** Move grounding_confidence (or a superset scorer) INSIDE the loop as the objective function, and persist the per-iteration series the way tailor_agent.py:497 persists `tailoringIterations`.

## [MEDIUM] CL-SCORE-004
**What:** [VERIFIED] The SAME letter is shown two DIFFERENT grounding percentages in two different places in the product, because two independent implementations with different corpora and different stopword lists both compute 'grounding'.
**Where:** apps/api/app/agents/cover_letter_agent.py:987-1003 + :1440-1451 (corpus) vs apps/api/app/routers/cover_letters.py:541-557 + :591-595 (corpus)
**Fix:** Collapse to one implementation and one corpus definition (the file comment at cover_letter_agent.py:990-993 already claims they are 'the SAME evidence-authenticity signal' — make that true), then have both the approval card and the studio read the identical persisted value.

## [MEDIUM] CL-SCORE-005
**What:** [VERIFIED] JD keyword coverage IS measured but is purely decorative — it is computed on read, never fed back into generation, and never gates anything. My live letter scored 3/10 and nothing in the system reacted.
**Where:** apps/api/app/routers/cover_letters.py:526-538 (_keyword_coverage), :618 (only consumer), apps/web/src/components/cover-letters/KeywordCoveragePanel.tsx:21-23
**Fix:** Make coverage the loop's primary objective after cleaning the keyword extractor (drop location/benefit/ATS-tag tokens), and feed the missing-keyword list into the retry prompt the way tailoring_loop.py:209 feeds `gapKeywords` — subject to the existing claim guard so closing a gap can never mean inventing experience.

## [MEDIUM] CL-SCORE-006
**What:** [VERIFIED] No cover-letter quality metric is persisted on the artifact. There is no CoverLetter table; letters live on Application, which has no score column of any kind. The only stored number is buried in the ApprovalRequest JSON payload, so it is lost the moment the approval is resolved/purged and cannot support any before/after or trend view.
**Where:** aether."Application" (9 columns) — apps/api/app/repositories/cover_letter.py:14-25
**Fix:** Add an additive JSONB column (e.g. Application.letterMetrics) written at create() time with the per-iteration scores + final score, mirroring Resume.sections.tailoringIterations. Backward-compatible ADD COLUMN with a default.

## [MEDIUM] CL-SCORE-007
**What:** [VERIFIED] There is NO before/after quality display for cover letters anywhere in apps/web — only three post-hoc, single-value indicators. The resume has an explicit Before → After banner. A 'before' is also conceptually impossible today because no metric is stored per version.
**Where:** apps/web/src/app/dashboard/cover-letters/page.tsx:271-290; apps/web/src/components/cover-letters/KeywordCoveragePanel.tsx:21-23; apps/web/src/components/approvals/ApprovalModal.tsx:179-184 — vs apps/web/src/app/dashboard/resume/page.tsx:393-402
**Fix:** Once CL-SCORE-006 persists a per-version score, render a version-over-version delta in the studio (v1 62% → v2 78%) — the honest cover-letter analogue of the resume's baseline→tailored banner, since a cover letter has no pre-existing 'before' document.

## [MEDIUM] TAIL-06
**What:** From iteration 2 onward the tailor service is handed the synthetic directive as its `job_description`, so both the top-K bullet SELECTOR and the JD-echo anti-fabrication guard stop seeing the real job posting.
**Where:** apps/api/app/services/tailoring_loop.py:209 `current_jd = self._build_directive(...)` → apps/api/app/services/resume_tailor.py:2111-2113 `select_bullets_to_tailor(structured, job_description, ...)` and :2193 `jd_ngrams = jd_ngram_index(job_description)` consumed at :2252 `jd_echoed_phrases(...)`
**Fix:** Keep the real JD as the scoring/guard input and pass the directive as a separate `directive=` kwarg on `ResumeTailorService.tailor`, so `select_bullets_to_tailor`, `jd_ngram_index` and `jd_stems` always see the genuine posting.

## [MEDIUM] TAIL-07
**What:** The before/after ATS panel for the RESUME exists but is session-only: it renders solely from the tailor-run HTTP response and is gone on reload. It is also the ONLY before/after display for the resume — the reload-survivable panel (GET /resumes/{id}/ats) shows a single 'after' number with no 'before'.
**Where:** apps/web/src/app/dashboard/resume/page.tsx:393-402 (data-testid="conversion-before-after", Before: {conversion.baselineATSScore}% → After: {conversion.tailoredATSScore}%); state at :90; only writers at :135 and :144; load() at :100-110 never restores it; single-score panel at :602-621
**Fix:** After TAIL-02 persists conversionMetrics into sections, hydrate `conversion` inside `load()` from the selected resume version; and render the persisted `tailoringIterations` (score-per-pass + gapKeywords chips) so the progress trail is actually visible.

## [MEDIUM] TAIL-08
**What:** The deployed Next.js bundle predates the current working tree, and the working tree itself has uncommitted changes to the exact files that render the before/after panel — so what is live is not what is in the repo.
**Where:** apps/web/.next/BUILD_ID (built 2026-07-31 16:57:04); uncommitted: apps/web/src/app/dashboard/resume/page.tsx, apps/web/src/lib/api/resumes.ts, apps/web/src/app/dashboard/jobs/page.tsx
**OPERATOR:** Operator must decide commit-vs-revert and trigger the web rebuild/restart — I am read-only.
**Fix:** Commit or revert the working-tree changes, then rebuild and restart aether-web so the deployed UI matches the repo.

## [MEDIUM] GAP-EMAIL-06
**What:** Even for a visible alert, triage only shows the model the first 400 characters of the body. A Seek digest's 20 postings live in an 8,920-character body, so ~95% of the extractable content is cut off before any model sees it.
**Where:** apps/api/app/agents/email_agent.py:262-266 — `f"Body: {self._latest_body(t)[:400]}"`
**Fix:** Extraction must not reuse the triage prompt. Run the parser (GAP-EMAIL-01) over the FULL stored body deterministically (regex/anchor-based, no LLM), and keep the 400-char truncation only for the cheap triage-labelling pass.

## [MEDIUM] GAP-EMAIL-07
**What:** The sync persists only the LATEST message of each Gmail thread. Alert digests that arrive as follow-on messages in an existing thread are silently discarded, so even a correct parser would see one message per thread rather than the week's alerts.
**Where:** apps/api/app/services/gmail_service.py:640-641 (`latest = messages[-1] if messages else {}`) and gmail_service.py:806-816 (the messages jsonb is built from that single normalized message only)
**Fix:** For the mining path, iterate Gmail at MESSAGE granularity (users().messages().list) rather than thread granularity, or normalize every element of full['messages'] instead of only the last.

## [MEDIUM] GAP-EMAIL-08
**What:** Turning Seek alert emails into Job rows collides with an existing compliance ruling. Seek is deliberately excluded from the live sourcing registry because scraping seek.com.au is ToS-prohibited; whether email-delivered Seek links may be persisted as Job rows and auto-applied to is unresolved.
**Where:** apps/api/app/services/discovery/adapter_registry.py:38-41 (_COMPLIANCE_GATED = {"seek": (SeekAdapter, "AETHER_ENABLE_SEEK")}) and adapter_registry.py:9-16 (ADR-P6-SEEK rationale)
**OPERATOR:** Owner/legal decision: confirm that persisting job title/company/location/URL extracted from Seek alert emails the user subscribed to is acceptable, and confirm that no HTTP fetch of seek.com.au job pages will be added as part of it.
**Fix:** Distinguish the two: parsing an email the user was legitimately sent, and storing title/company/location/URL from that email, is not scraping seek.com.au. Fetching each au.seek.com/job/<id> page to enrich the description IS. Ship the parser as email-only (no outbound fetch of Seek pages), and keep any description enrichment behind AETHER_ENABLE_SEEK.

## [MEDIUM] SUB-009
**What:** SubmissionAgent's success message says "Submitted your application for {title} at {company}" — a claim of transmission the system cannot make.
**Where:** apps/api/app/agents/submission_agent.py:107-111
**Fix:** Reword to what actually happened, e.g. "Marked your application for {title} at {company} as submitted and moved the card — apply on the company site to complete it."

## [MEDIUM] SUB-010
**What:** There is no email→job ingestion at all: an inbound email can never create a job card. Jobs come only from the scout agent's job-board adapters.
**Where:** apps/api/app/repositories/job.py:299 (the only INSERT INTO "Job" in the codebase); apps/api/app/agents/scout_agent.py:120 (its only caller)
**Fix:** If the 'email arrives → card appears' journey is required, add an EmailThread classifier branch that extracts a job posting (title/company/URL) and calls JobRepository.create with source='email'; today that branch does not exist.

## [MEDIUM] SUB-011
**What:** The agentConfig.autoApply flag is inert — nothing in the API reads it to trigger any behaviour — yet the Applications page renders a banner implying auto-apply is a live capability.
**Where:** apps/api/app/routers/workspaces.py:937, :954, :990 (the only three references in the whole API); apps/web/src/app/dashboard/applications/page.tsx:658, :745-757
**Fix:** Either wire autoApply to a real gated submission path (post-SUB-001) or remove the setting and the banner; a toggle that changes nothing is a false affordance on the product's highest-risk action.

## [MEDIUM] RT-PROP-005
**What:** The stream is scoped to ONE run id, so it can never be the primary change signal: a browser can only subscribe to runs whose id it already knows, and background cron/board-sweep run ids are never delivered to the browser except by polling GET /agents/runs first. There is no user-scoped channel despite the payload already naming one.
**Where:** apps/api/app/routers/agents.py:2171 route path `/runs/{run_id}/stream`; apps/api/app/services/agent_run_stream.py:434 `"channel": f"jobs:{user_id}"`
**Fix:** Add GET /events/stream (user-scoped, no run id), reusing sse_event/sse_comment/StreamSlots/SSE_HEADERS verbatim. Cheapest honest v1: the generator polls one lightweight watermark query (MAX("AgentRun"."completedAt") plus MAX("updatedAt") over Job/Application/Resume/StoryEntry for that userId) every 3s and emits `event: changed {scopes:[...], at:...}`. That is server-side polling, but it collapses N screens x N tabs into one connection and gives sub-3s UI latency. Upgrade path later: worker publishes to Redis, the generator subscribes instead of polling.

## [MEDIUM] RT-PROP-006
**What:** There is no shared client-side store, cache, or event bus. Each page owns its own useState and fetches independently, so nothing can invalidate anything else — an action on one screen cannot refresh another, and cross-screen counters drift.
**Where:** apps/web/src (whole app); apps/web/package.json dependencies
**Fix:** Add one ~40-line module-level pub/sub (Set<listener> + notify, no dependency) plus a `useRefreshSignal()` hook, and have the Sidebar — already mounted on every dashboard route and already polling GET /agents every 30s at sidebar.tsx:45 — publish a watermark = max(a.last_run) (topbar.tsx:202-211 already computes exactly this value, just once). Each screen then adds `useEffect(() => { void load(); }, [watermark, load])`. One poll for the whole app instead of one per screen, and it composes with RT-PROP-005: when /events/stream lands, only the publisher changes, not the 13 subscribers.

## [MEDIUM] Q2-NOATS-006
**What:** The COVER LETTER has no ATS score at all — no before, no after, no lift, nothing. The Cover Letter Studio shows only "Evidence Grounding: 74% grounded" and "Fabrication Guard: Safe". So the answer to "where is ATS shown for the cover letter, is it before/after" is: nowhere, and there is no before/after. Given the Resume Studio breadcrumb sits directly above it, a user reasonably assumes the same quality bar was applied to the letter.
**Where:** apps/api/app/routers/cover_letters.py:610-621 (insights payload: letterId, jobId, jobTitle, company, wordCount, needsResume, evidence, keywords, voice, versions); apps/web/src/app/dashboard/cover-letters/page.tsx (zero ATS references)
**Fix:** Either state plainly in the Studio that cover letters are graded on evidence grounding and keyword coverage, not ATS (they are usually not ATS-parsed the way resumes are — which is a legitimate reason), or run ATSEngine on the letter+JD and show it. Silence reads as "it was scored".

## [MEDIUM] Q5-GUARD-007
**What:** The Cover Letter Studio header shows a badge captioned "Fabrication Guard" reading "Safe". That word does not come from the FabricationGuard. It comes from aiDetectionLabel = "Safe" if risk < 20, where risk = max(1, (100 - authenticity)/2) and authenticity is a bag-of-words overlap ratio against the evidence corpus. So any letter whose content words are >60% present in the corpus is stamped "Fabrication Guard: Safe" regardless of what the actual guard concluded. The field is also still named aiDetectionRisk/aiDetectionLabel in the API and schema — a linear transform of word overlap that was originally surfaced as an AI-detection score; no AI detector is run anywhere.
**Where:** apps/api/app/routers/cover_letters.py:541-557 (_voice_metrics); apps/web/src/app/dashboard/cover-letters/page.tsx:280-291 (label "Fabrication Guard", value aiDetectionLabel, testid "ai-detection-indicator"); apps/web/src/components/cover-letters/api.ts:28 (aiDetectionRisk: z.number())
**Fix:** Surface the actual guard verdict (the letter already passes FabricationGuard before persistence — cover_letter_agent.py build_approval_extras:1021-1035 asserts it) as a real pass/fail field on the insights payload, and bind the badge to that. Rename the word-overlap number to what it is ("evidence overlap") and delete aiDetectionRisk/aiDetectionLabel, which no longer mean anything.

## [MEDIUM] Q5-TRACKER-008
**What:** The Applications tracker renders a badge reading "ATS 41" on each card. Application has no atsScore column, and the applications API does not return one — the client falls back to Job.atsScore, which fit_scorer writes as the score of the BASE resume against the JD. So the badge on a submitted application shows the score of the resume the user did NOT send, labelled as if it were the score of the tailored one they did.
**Where:** apps/web/src/components/applications/tracker-lib.ts:223 and :252-253 (jobAts fallback); apps/web/src/app/dashboard/applications/page.tsx:917-923 and :1104-1110 (renders "ATS {n}"); apps/api/app/agents/fit_scorer.py:65
**Fix:** Join Application.resumeId -> the tailored Resume and score that (or read the persisted AgentRun conversionMetrics for it), and label the badge "ATS (submitted resume)". If unavailable, show nothing rather than the base-resume number.

## [MEDIUM] Q5-DUPE-009
**What:** Job.fitScore and Job.atsScore are literally the same number for every row, because fit_scorer passes score.overall twice. The Analytics page nevertheless presents "ATS score distribution" and "Avg Fit Score" as if they were two independent quality dimensions, and the Jobs board's MatchRing tooltip calls fitScore "a 0-100 blend of keyword, semantic and experience fit" — the same thing the ATS distribution histogram is bucketing.
**Where:** apps/api/app/agents/fit_scorer.py:65; apps/api/app/routers/analytics.py:150-172 (ats_distribution over Job.atsScore) and :707-712 (avgFitScore over Job.fitScore); apps/web/src/app/dashboard/analytics/page.tsx:300-337
**Fix:** Collapse to one column, or make atsScore genuinely distinct (e.g. the tailored resume's score vs. the base resume's fitScore). Until then the Analytics page should not imply two dimensions.

## [MEDIUM] Q5-DEMAND-010
**What:** "Top Skills in Demand" shows percentages that are not demand. demand = round(count/max_skill*100) where count is how many of THIS USER's own 52 scraped job rows mention a term from a hardcoded 55-item lexicon, normalised so the most frequent term is always exactly 100. The Market Pulse panel tooltip calls the whole thing "A live snapshot of hiring-market activity in your target region" while marketDataConnected is false in the same payload.
**Where:** apps/api/app/routers/analytics.py:269-281 (_SKILL_LEXICON), :513-529 (demand computation); apps/web/src/components/analytics/MarketPulse.tsx:73 (tooltip), :148-170 (render)
**Fix:** Relabel to "Most-mentioned skills across your 52 sourced jobs" and show raw counts ("in 31 of 52 jobs") instead of a normalised %. Fix the panel tooltip to stop claiming market-wide coverage while marketDataConnected is false.

## [MEDIUM] Q3-TARGET-012
**What:** Zero of 208 production tailor runs has ever reached the advertised ATS >= 85 target; the best score ever achieved on this platform is 53.92, and every one of the 52 scored jobs sits below 60. The ATS-distribution histogram the user sees is entirely in the 20-60 range with the 80-90 and 90-100 buckets empty. The 85 target is therefore not a bar the system clears — it is a bar it has never once approached — yet it is the exit condition the whole loop is built around and the number quoted in every warning.
**Where:** apps/api/app/services/tailoring_loop.py:55 (DEFAULT_TARGET_SCORE = 85.0), :202 (break condition); apps/api/app/routers/analytics.py:150-172
**OPERATOR:** Decide whether 85 is a calibrated target on this engine's scale, or an aspirational number inherited from a spec.
**Fix:** Either the 85 target is wrong for this ATSEngine's scale (in which case recalibrate and stop quoting 85 at users), or the tailoring genuinely cannot move the needle (5 iterations shift the score by ~1-4 points; see the persisted iteration arrays, e.g. [50.05, 50.05, 50.05, 51.22, 52.38]) — in which case the loop's 5 iterations are mostly billed no-ops. Investigate which before shipping any further quality claim.

## [MEDIUM] GT-09
**What:** [VERIFIED] Email is read-only in practice. Zero of 278 EmailThreads carry a `draftReply`, zero are linked to an `applicationId`, and the single `email_send` approval ever created (2026-07-22) was never executed. No outbound email has ever left the system.
**Where:** aether."EmailThread".draftReply / applicationId; aether."ApprovalRequest" type='email_send'
**Fix:** The emailAgent only ever runs in triage mode; reply-draft and send modes have never been invoked in production. Also nothing ever correlates an inbound recruiter thread back to the Application it belongs to, so the 'application tracking from your inbox' story does not exist in data.

## [MEDIUM] GT-10
**What:** [VERIFIED] Six whole feature areas have zero rows and have never produced a single artifact: InterviewSchedule (0), Contact (0), OutreachTask (0), Offer (0), JobEmbedding (0), GoogleCredential (0).
**Where:** aether."InterviewSchedule", "Contact", "OutreachTask", "Offer", "JobEmbedding", "GoogleCredential"
**Fix:** Either these agents don't persist their output or they were only ever smoke-invoked. JobEmbedding=0 in particular means semantic job matching is not operating — the `matcher` agent's 52 runs all cost $0.0000, consistent with a non-LLM/heuristic path. Calendar (GoogleCredential=0) is unconfigured despite task V4 W-CAL being marked complete.

## [MEDIUM] GT-11
**What:** [VERIFIED] The fitScorer agent scores nothing 98% of the time. 680 completed runs, but only 14 ever scored >0 job (97 scores total), and the last useful run was 2026-07-31 05:31 — every run since returns `"scored": 0`.
**Where:** aether."AgentRun" agentName='fitScorer'
**Fix:** `"model": null` with tokensIn/Out = 0 means no LLM is being called at all — the run finds no candidate jobs to score (consistent with GT-02: no new jobs arriving) and exits as 'completed'. A 3.8s no-op every ~20 minutes is wasted scheduler capacity and inflates 'agent activity' metrics.

## [MEDIUM] GT-12
**What:** [VERIFIED] Application↔Job stage desync. 20 Applications sit in a non-draft state whose linked Job is NOT in status 'applied' — 19 'submitted' against Jobs still 'ready', 1 'submitted' against an 'archived' Job. The kanban and the job board disagree about the same 20 records.
**Where:** aether."Application".status vs aether."Job".status
**Fix:** Make the Application status transition and the Job status update a single transaction (or derive Job.status from its Applications). Separately, 5 of 8 JobStatus enum values are dead code — the pipeline jumps straight from insert to 'ready'.

## [MEDIUM] GT-13
**What:** [VERIFIED] 19 EmailThread rows reference a GmailAccount that no longer exists (orphan FK), and 2 more have a NULL gmailAccountId. Those 21 threads cannot be attributed to any inbox.
**Where:** aether."EmailThread".gmailAccountId
**Fix:** Gmail account disconnect deletes the GmailAccount row without cascading or reassigning its threads. Add ON DELETE handling or soft-delete the account row.

## [MEDIUM] GT-14
**What:** [VERIFIED] Background job failure rate is 21% (45 of 216 failed) and one `tailor` AgentRun has been stuck in status='running' since 2026-07-26 03:41 — 7 days with no completedAt and no reaper.
**Where:** aether."BackgroundJob"; aether."AgentRun" id=ca44687a029bb1f622b71fa06
**Fix:** Add a stale-run reaper that marks runs 'failed' after a timeout, so a hung run can't hold a slot or a quota indefinitely.

## [MEDIUM] GT-15
**What:** [VERIFIED] Cover letters carry no quality score anywhere. There is NO CoverLetter table in the schema — letters live in `Application.coverLetter` (text) with no accompanying score column, and `Application.answers` contains no score for any of the 5 rows that have it.
**Where:** aether schema (\dt shows no CoverLetter table); aether."Application".coverLetter / answers
**Fix:** If the UI shows a cover-letter score, it is computed on the fly and never persisted — meaning it cannot be trusted to match what the user saw, and there is no record to audit. Persist the score alongside the letter.

## [LOW] SRC-09
**What:** [VERIFIED] `/agents/scout/sources/availability` reports `adzuna: available=true, reason=null` even though it has no credentials and skips 100% of runs. Availability is computed from 'does the class override _fetch_live', not from whether the source can actually run.
**Where:** apps/api/app/services/discovery/adapter_registry.py:138-145
**Fix:** Add a per-adapter `is_configured()`/readiness hook (adzuna returns False when creds are absent, with reason 'requires ADZUNA_APP_ID/ADZUNA_APP_KEY'), and let `source_availability()` fold in the last persisted `blocked` status. Same defect covers Wellfound (SRC-05).

## [LOW] SRC-10
**What:** [VERIFIED] The user's slash-separated target role is never split, producing a nonsense first search term. build_scout_query splits only on commas, so 'Business Analyst/Project Manager/Scrum Master' survives as one 45-char token that no source can match.
**Where:** apps/api/app/services/discovery/query_builder.py:59-62
**Fix:** Split the profile target role on `/` and `|` as well as `,` in query_builder.py:59 before de-duplicating against ROLE_FAMILY_TERMS. Low impact today (the family terms that follow rescue most sources) but it is a real correctness bug that will bite Adzuna and Workable the moment they start producing.

## [LOW] AG-14
**What:** emailAgent claims label management in its catalog tip but has applied ZERO labels across all 41 successful runs; and 2 runs failed on modes the caller sent that the agent does not implement.
**Where:** apps/api/app/agents/email_agent.py:213 (mode dispatch); catalog tip at apps/api/app/routers/agents.py:281-283 ("…label management and per-thread insights")
**Fix:** Either exercise apply_labels once to prove it, or drop "label management" from the tip. Separately, find the caller sending mode='analyze'/'draft' (likely the FE or a test harness) and align it with the implemented mode names.

## [LOW] AG-15
**What:** One tailor AgentRun has been stuck in status='running' for 7 days with no completion or timeout reaper.
**Where:** aether."AgentRun" id=ca44687a029bb1f622b71fa06
**Fix:** Add a stale-run reaper (mark 'failed' after N× the agent's budget) so the sidebar's "agents running" indicator and the catalog health classifier are not skewed by an orphan.

## [LOW] AG-16
**What:** 14 test/probe user accounts exist in the production User table alongside the single real user.
**Where:** aether."User"
**Fix:** Task #25 (W-CLEAN). Purge with cascade care — none of them own AgentRun rows, so the agent history is unaffected.

## [LOW] AG-17
**What:** companyResearch's advertised opt-in LLM narrative has run exactly once in 4 runs; the other 3 returned narrative=null with noLlmCall=true.
**Where:** apps/api/app/agents/company_research_agent.py:176 (run) / :374-382 (narrative generation, get_model("REASONING"))
**Fix:** Expected behaviour (narrative is opt-in per run) — flagged only so the inventory is complete: the LLM half of this agent has one production data point, and the deterministic half carries the other three.

## [LOW] AG-18
**What:** Per-run model attribution is not recorded in billingAuditJson, so the DB cannot prove which model any deterministic agent ran on; and emailAgent triage classification is unstable across runs on the same inbox.
**Where:** aether."AgentRun"."billingAuditJson" (no model key); output->>'model' is null for all 10 deterministic agents
**Fix:** Copy output.model into billingAuditJson at _record_run (apps/api/app/routers/agents.py:791) so cost audits are self-contained. For triage instability, pin temperature to 0 for the classification call — the same 50 messages should not land in 2, 3, then 4 categories.

## [LOW] CL-SCORE-008
**What:** [VERIFIED] Every letter is wrapped in a fixed template shell whose repetition no quality gate detects. The opening sentence is deterministic and identical across 100% of production letters; a large minority also share the same paragraph-2 opener and the same closing formula. The structural gate checks only shape (3 paragraphs, banned openers, role named, CTA cue) — it cannot see boilerplate repetition or self-redundancy.
**Where:** apps/api/app/agents/cover_letter_agent.py:780-787 (build_body hook) and :1271-1298 (_structural_issues)
**Fix:** Add a repetition/redundancy component to the scorer proposed in CL-SCORE-001 (n-gram overlap between the deterministic hook and the model's hook_reason; cross-letter boilerplate frequency) and let a low score trigger a retry rather than shipping the duplicate clause.

## [LOW] CL-SCORE-009
**What:** [VERIFIED] The refine path (POST /cover-letters/{id}/refine) is likewise score-blind — a guard-only single retry, no metric computed on the revision, so a user 'refining' a letter has no signal whether it got better or worse.
**Where:** apps/api/app/routers/cover_letters.py:826-856
**Fix:** Score the revision with the same scorer and return it alongside the new version so the studio can show 'v2 78% → v3 71%, keep v2?'.

## [LOW] TAIL-09
**What:** The tailoring run silently executed on a different model than the one requested.
**Where:** async job result for c84469c1dba05dfdef70f90eb (routers/agents.py:592 asdict passthrough)
**Fix:** Surface the substitution to the user (a notice when model != requestedModel), or fail loudly if the requested model is unavailable.

## [LOW] GAP-EMAIL-09
**What:** 21 EmailThread rows are orphaned — 19 point at a GmailAccount id that no longer exists and 2 have a NULL account id — so any per-account mining or reporting will silently under- or mis-count.
**Where:** aether."EmailThread"."gmailAccountId" (schema added at apps/api/app/services/gmail_service.py:245)
**Fix:** Either re-point orphans at the primary account (the same backfill gmail_service.py:259-270 already performs for NULLs) or delete rows whose account is gone, and make disconnect_account (routers/emails.py:139-148) decide explicitly which of the two it does.

## [LOW] SUB-012
**What:** The submission write itself is not audited. AdminAuditLog records stage moves and approval decisions but has no action for an apply/submit.
**Where:** apps/api/app/routers/jobs.py:587-678 and apps/api/app/routers/applications.py:423-568 — neither calls write_audit
**Fix:** Add write_audit(user_id, 'application.submit', target_type='application', target_id=application_id, detail={job_id, resume_id, path}) inside submit_application_for_job and applications.submit_application, on the same cursor as the UPDATE.

## [LOW] RT-PROP-007
**What:** Email Center and Networking are strictly mount-only even though the emailAgent and recruiterOutreach agents write to their tables, and neither screen has any refresh affordance at all (no timer, no refresh button path through `load`).
**Where:** apps/web/src/app/dashboard/email/page.tsx:127 (fetchEmailInbox, deps []); apps/web/src/app/dashboard/networking/page.tsx:67 (fetchNetworkingSummary, deps [])
**Fix:** Extract the inline fetch into a `const load = useCallback(...)` first (so there is something to re-invoke), then apply the same usePolling adoption as RT-PROP-002. Without the extraction these two screens cannot be wired to any refresh signal.

## [LOW] Q1-JOBSTATE-011
**What:** On the Jobs board, a freshly tailored job's MatchRing is patched with the post-tailor score in React state only. On reload it silently reverts to the pre-tailor fit_scorer value from the DB, with no indication the displayed number now describes a different resume than the one the user just produced.
**Where:** apps/web/src/app/dashboard/jobs/page.tsx:653-671 (setJobs local patch); no persistence of tailoredATSScore to Job
**Fix:** Persist the tailored score (a new Job.tailoredAtsScore, or read it back from AgentRun.output on load) so the ring is stable across reloads, or drop the optimistic patch so the user is never shown a number that will silently change.

## [LOW] GT-16
**What:** [VERIFIED] The one 'pro' Subscription has a stripeCustomerId but NO stripeSubscriptionId, so it is not tied to a live Stripe subscription object. All 15 subscriptions lack stripeSubscriptionId.
**Where:** aether."Subscription"
**OPERATOR:** Verify in the Stripe dashboard whether a recurring subscription actually exists for the pro customer.
**Fix:** Either the pro entitlement was granted manually/by a one-off invoice rather than a recurring subscription, or the webhook that writes stripeSubscriptionId never fires. Renewal and cancellation cannot be reconciled against Stripe for any account today.

## [LOW] GT-17
**What:** [VERIFIED] The fabrication guard rejects the cover-letter agent on ordinary domain nouns, causing 109 hard failures. Rejected 'entities' include 'onboarding' (21), 'credit' (13), 'yield' (12), 'origination' (9), 'marketplace' (8), 'sales' (6), 'professional' (6), 'people' (2).
**Where:** aether."AgentRun" agentName='coverLetter' status='failed'
**Fix:** The guard's entity extractor is treating common English/industry nouns as fabricated proper nouns. Restrict it to capitalised multi-token entities or a known-entity allowlist; as written it blocks legitimate letters roughly as often as it catches anything.
