# MANUAL-VERIFICATION — Stage 2 Triage & Fix Clusters (orchestrator, 2026-07-17)

Findings clustered by ROOT CAUSE so one fix closes many (§5). Each finding is still verified individually on prod by a non-author. Priority: BLOCKER clusters → HIGH → MEDIUM → LOW. Entitlement stays Pro through Stage 2/3; reverts before exit gates.

Severity counts at triage: 14 BLOCKER / 28 HIGH / 38 MEDIUM / 36 LOW = 116 (pre paid-re-test).

## Adjudication axis (orchestrator ruling)
Findings split into: **DEFECT** (broken/dishonest/misleading to paying users → MUST fix) vs **SCOPE** (feature less complete than wireframe, needs a build-out decision, may be documented/descoped honestly rather than built). §0.5 forbids placeholder/mock/misleading content reachable by users, so any DISHONEST surface (fake success, hardcoded-fake-data-shown-as-real, dead control that claims to work, unfilled placeholder, misleading marketing) is a DEFECT regardless of build cost. "Missing wireframe feature that is simply absent (no dishonest surface)" is SCOPE.

---

## CLUSTER A — CoverLetter agent quality (BLOCKER, fixer-hard) — apps/api/app/agents/cover_letter_agent.py
- MV-cover-letter-studio-001 (BLOCKER): `enforce_first_person()` (l.302-359) corrupts hook → "My background as an I am a direct match…" on EVERY generation (name/title both "Administrator" collide).
- MV-cover-letter-studio-002 (BLOCKER): `/cover-letters/{id}/refine` duplicates salutation/hook/sign-off.
- MV-cover-letter-studio-003 (BLOCKER/security): prompt-injection from job description leaks into refined output.
- MV-cover-letter-studio-004 (BLOCKER): fabricated candidate name in sign-off (hallucination guard miss).
- MV-approval-modal-009 (HIGH): same grammar bug shipping invisibly through approval.
- MV-cover-letter-studio-005 (MED): raw internal error string surfaced on timeout.
- MV-cover-letter-studio-006 (MED): JD keyword extraction low-quality tokens.
Root: single agent module. One fixer-hard, TDD per defect.

## CLUSTER B — Approval payload/modal wiring (BLOCKER) — CoverLetterAgent.run() payload (l.659-670) + apps/web approvals
- MV-approval-modal-001 (BLOCKER): approval payload omits letter preview/why/reasoning/confidence → reviewer sees near-empty modal (can't see what they approve).
- MV-approval-modal-002 (HIGH): Edit&Approve permanently disabled for real approvals.
- MV-approval-modal-007 (LOW): cover-letter copy on email_send approvals. -008 (LOW): execute endpoint unwired. -004 (LOW): confidence not clamped. -005/-006 (MED): back-button/deep-link error race.
Tightly related to A (same agent writes the payload). fixer-hard, likely same owner as A.

## CLUSTER C — Fixture/fabricated content reachable by users (BLOCKER) — investigate origin
- MV-application-tracker-001 (BLOCKER): app detail shows cover-letter text byte-identical to pytest fixtures (default/retry.json) w/ fabricated achievement across unrelated jobs.
- MV-story-bank-005 (HIGH): log evidence of past fixture-masquerade (current live behavior clean — likely stale seed rows, not live leak). 
RCA first (scout): is it seed data (delete rows) or a live code path (fix). fixer-hard after RCA.
**RCA DONE (fixes/MV-application-tracker-001/RCA.json): VERDICT = STALE SEED DATA, not live code.** 8 draft Application rows contain fixture cover-letter text (fingerprint "cut evidence effort from roughly 3 hours to about 15 minutes per scenario"), owned sarkar.vikram(4)+admin(4), created 2026-07-13..17 during test/demo. Prod AETHER_LLM_MODE=auto NEVER serves fixtures (llm_client.py:988-1065 raises 503; fixtures only in `replay` mode). FIX = data cleanup: back up + DELETE the 8 rows (ids in RCA.json) + add guard test asserting no Application.coverLetter matches fixture fingerprints + runbook pre-deploy AETHER_LLM_MODE!=replay/record check. Orchestrator ADJUDICATION: these 8 drafts contain fabricated-achievement fixture text reachable by users (§0.5 violation) → authorized for deletion with backup. NOT a cover-letter-agent code bug (that's cluster A, separate).

## CLUSTER D — Free-tier paywall ⟷ marketing reconciliation (BLOCKER, architectural — fable-5 adjudicates approach) 
- MV-pricing-001 (BLOCKER) + MV-analytics-001 (BLOCKER) + MV-dashboard-003/MV-mobile-dashboard-003/MV-agents-001/MV-analytics-002 (coverage) + MV-dashboard-001.
- MV-agent-monitor-004 (MED/SECURITY): SubscriptionGate FAILS OPEN on entitlement-check error = paywall bypass. (Security defect regardless of D's business decision — fix independently.)
RULING NEEDED: pricing page advertises free "5 runs/no card" + data model provisions free runsAllowed=5, but frontend SubscriptionGate blocks ALL /dashboard/* for free users AND backend _require_active_subscription blocks all metered runs. Evidence (runsAllowed=5 provisioned + marketing) says free SHOULD get 5 runs. Options: (D1) honor free tier — narrow the gate to allow free-tier metered quota + free read-only pages; (D2) fix marketing — stop advertising free features, make "free" honestly a trial/teaser. D1 aligns data-model+marketing+§0.5; D2 is smaller but changes the product's stated offer. LEANING D1 (align to the advertised+provisioned intent) + fix fail-open. Needs a written ADR + arch blueprint before code.

## CLUSTER E — UI-facade / dead controls / client-only fakes (HIGH/MED, per-screen frontend fixes)
Dishonest surfaces (DEFECT, must fix): dead buttons that report success or look functional, client-only "create" that never persists, hardcoded-fake-data shown as real.
- settings: MV-settings-001 (dead toggles report saved), -002 (fake Sync spinner). 
- agent-monitor: MV-agent-monitor-001 (dead Pause-All/Manual-Override), -002 (hardcoded progress %), -003 (conflicting figures).
- networking: MV-networking-001 (fake Add-Contact no persist), -002 (field-mismatch blank data), -003 (fake LinkedIn import), -004 (dead Review-drafts), -005 (no detail view), -009/-010.
- offer-comparison: MV-offer-comparison-001 (fake Add-Offer), -002 ($0 neg-coach), -003 (modal backdrop gap), -004 (decorative weights).
- email-center: MV-email-center-001 (AI scoring hardcoded null), -002 (draft/send unreachable), -003 (empty Priority tab), -005 (hardcoded stats + wrong connect-Gmail copy), -007.
- story-bank: MV-story-bank-001 (fake Import-from-Portfolio), -002 (layout blowup), -003 (no delete confirm), -006 (fixed PDF ignores user resume).
- resume-studio: MV-resume-studio-001 (decorative approval gate), -003 (silent no-op billed), -004 (static integrity text).
- job-discovery: MV-job-discovery-002 (bulk-apply bypasses tailor+confirm gate), -001 (garbage skill tokens).
- interview-center: MV-interview-center-001 (screen never calls backend), -002 (bare), -003 (no create UI anywhere), -004 (orphan validation). [borderline SCOPE — but the screen dishonestly presents an empty state over a working backend with no way to use it → DEFECT: at minimum wire read + a create path, or honestly remove the nav entry].
Each screen = its own fixer-medium task (frontend wiring), TDD (playwright/vitest). Cluster by screen.

## CLUSTER F — Legal/content honesty (HIGH/MED, fixer-medium) — apps/web legal pages + footer
- MV-terms-001 (no public links to terms + no signup consent), -002 (unfilled [Operator ABN]/[Business Name] placeholders — §0.5), -003 (fake support-contact path), -004 (USD/Delaware vs AUD/GST).
- MV-privacy-policy-001 (no legal links on public pages), -002 (no AU privacy law), -003 (fake data-export contact).
One fixer: fill placeholders w/ real operator details (NEED operator input on ABN/business-name → may be HUMAN-GATED for the real values; can wire links + AU-law refs + reconcile currency now), add footer legal links + signup consent, reconcile the promised contact path (either build a contact mechanism or change copy to a real one).

## CLUSTER G — Pricing/billing honesty (HIGH, fixer-medium)
- MV-pricing-002 (model-tier marketing vs real OpenRouter deepseek/qwen), -003 (no manage-subscription UI), -004 (checkout error handling), -005; MV-settings-003 (billing entitlement fetched but never rendered); MV-cover-letter-studio-007 (serving model doc mismatch).
Reconcile marketing copy with real serving models + surface real plan/manage-subscription UI.

## CLUSTER H — Auth affordances (MED, fixer-medium)
- MV-login-001 (authed→login no redirect), -002 (deep-link return), -003 (no logout — arguably HIGH: a paid app with no sign-out), -004 (no password reset); MV-signup-001 (bcrypt 72-byte truncation — SECURITY, treat HIGH), -002 (authed→signup), -003, -004.

## CLUSTER I — Security-specific (fold into owning cluster, verify explicitly)
- MV-cover-letter-studio-003 (prompt-injection → A), MV-signup-001 (bcrypt → H), MV-agent-monitor-004 (fail-open → D). Each gets an explicit security test.

## CLUSTER J — Observability (MED) — MV-system-001: add request timestamps / journald logging.

## CLUSTER K — Admin + misc LOW (fixer-medium, batch)
- MV-admin-* no-wireframe coverage-gaps: mostly DOC (create minimal wireframes or mark descoped) — SCOPE, not code defects; the guard behavior is correct. MV-admin-settings-002 (422-before-401 ordering, minor), MV-admin-users-002 (data-export claim → doc/claim).
- Remaining LOW visual/validation across screens: batch after higher clusters.

## Sequencing
1. RCA cluster C (fixture origin) — scout, immediately (cheap, informs whether it's data or code).
2. Blueprint cluster D (paywall reconciliation) — arch/fable-5 ADR (architectural decision).
3. fixer-hard: cluster A+B (cover-letter agent+approval payload) — highest-value defect.
4. fixer-medium parallel: cluster F (legal), cluster G (pricing honesty), cluster H (auth).
5. fixer-medium per-screen: cluster E screens (settings, networking, offer, email, agent-monitor, story-bank, resume, job-discovery, interview).
6. cluster J (observability), cluster K (admin/misc/LOW).
Each: PLAN→TESTS-FIRST→IMPLEMENT→TEST→REVIEW(≠author)→COMMIT fix(MV-...)→DEPLOY→PROD-VERIFY(≠author)→LEDGER. Then Stage 3 adversarial, revert entitlement, exit gates.
