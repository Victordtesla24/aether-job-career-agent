# v5 swarm — adversarial review outcome (2026-08-02)

All 6 build streams completed and are committed + pushed. Only **2 of 6 reviews ran**: the other
four died with `You've hit your session limit · resets 12pm (UTC)`. Both reviews that DID run
returned **FAIL**. Neither found fabricated data or placeholder credentials — the failures are
correctness, reachability and honesty defects.

**DO NOT DEPLOY until the BLOCKER below is fixed.**

## W-SUB (real submission) @0eb939a — FAIL

* **BLOCKER — the original lie is reintroduced.** The autonomous submission path "burns the
  single-shot execution claim and reintroduces the exact 'approval says executed but nothing was
  transmitted' state" (`services/application_submission`). This is the precise defect the whole
  workstream existed to remove: 86 Applications reading `submitted` that were never sent.
* **MAJOR — shared-tree contamination, confirmed.** Another worker's uncommitted changes were
  swept into this commit (`app/db.py` ensure_story_archive…). Exactly the `git add` index-inheritance
  hazard recorded earlier this session, now demonstrated a third time.
* MINOR — commit message claims `test_wsub_real_submission.py (24 cases)`; the file has **18**.
* MINOR — the advertised refusal path is unreachable dead code: `transmit_application` always passes
  `cover_letter_id=str(application_id)`, so `resolve_email_attachments` can never take the refusal branch.
* MINOR — inconsistent contract on `/approvals/{id}/execute`: the non-submission branch returns
  `transmitted: false`, the real-send branch returns a different shape.

## W-EMAIL-INTAKE @ef121bd — FAIL

* **MAJOR — unreachable by any user.** The agents screen hardcodes `emailAgent: { mode: "triage" }`
  (`dashboard/agents/page.tsx:68`) and the Email Center does the same, so the new intake mode cannot
  be invoked from the product at all. The 45 Job rows exist because the AGENT ran it directly.
* **MAJOR — undisclosed metric contamination.** The 45 `seek-alert` rows carry the alert card's
  salary/teaser line as `Job.description` — **average length 15 characters**. That field feeds
  `fit_scorer._job_text` (`fit_scorer.py:85`), so every score computed over these rows is derived
  from a 15-char stub rather than a job description. This silently degrades the scoring the whole
  qualification architecture now depends on.
* **MAJOR — provenance filter broken in production right now.** `GET /jobs?source=seek-alert`
  returns **422 "Unknown source 'seek-alert'"** on the live API
  (`routers/jobs.py:39-69 _validate_source_filter`, landed in 0eb939a).
* MINOR — report/code mismatch on the Michael Page skip rationale.
* MINOR — `_ALERT_QUERY_PARAMS` strips `token` and `from`, which are **load-bearing** on some real
  ATS URLs (e.g. Greenhouse `?token=`), so canonicalisation can break real apply links.

## Not reviewed (quota exhausted)

W-STORY-REBUILD @8c18fdc, W-TAILOR-CONVERGE @a6fae64, W-CLEAN @2b7dc6b, W-RT @8b27160 carry **no
independent review**. Their self-reported success must not be treated as verified.

## Verified independently against the production DB regardless of review status

* Story bank: 60 stories, all 60 substantive (>200 chars of STAR content).
* Fixture/probe markers in Applications: **0** remaining.
* Jobs: 111. Resumes: 114, of which **1** carries a persisted ATS score — the persistence fix
  applies to NEW tailoring runs only and is still unproven end to end.
