# ORCHESTRATOR RULING — U5 review item F3 (2026-08-14T01:30Z, binding)

F3 (lever/smartrecruiters in AUTOMATABLE_CHANNELS with only a generic untested parser) is CONFIRMED as a
real defect, and the SANCTIONED RESOLUTION is DEMOTION, not parser-building in this slice:

1. REMOVE lever + smartrecruiters from AUTOMATABLE_CHANNELS. For launch they are ASSISTED channels:
   the pipeline still prepares the tailored resume + cover letter and surfaces an honest "ready to submit —
   this platform needs your click" state with the direct application URL (consistent with the honest-copy
   fixes already landed in 04f80e2/156659c). NEVER auto-submit through parse_form_schema's generic
   best-effort path on a real employer site.
2. ashby + greenhouse REMAIN automatable (dedicated parsers + tests exist).
3. Add the invariant test the reviewer demanded, inverted to pin the ruling: AUTOMATABLE_CHANNELS must be
   a subset of platforms with dedicated parser coverage — a platform added without a dedicated parser + tests
   must FAIL the invariant sweep.
4. Dedicated lever/smartrecruiters parsers + their tests = Track-2 slice U5c (queued; full TDD there), after
   which they re-enter AUTOMATABLE_CHANNELS legitimately.

RATIONALE: no-half-baked mandate — an untested generic parser auto-submitting a subscriber's REAL job
application is the worst failure mode this product can have. Honest assisted mode is the complete,
shippable version of today's capability. This ruling is the closing bar for F3; reviewers verify the
demotion + invariant test, not parser expansion.
