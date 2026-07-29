# GAP-P4-003 RCA — Application Funnel Stage Progression

**Date:** 2026-07-26  
**Status:** Investigated — no stage-progression code defect confirmed

## Observed funnel

The authenticated Phase 4 observation recorded this live funnel:

```
50 jobs found → 42 applied → 2 screened → 0 interviewed → 0 offers
```

The 0% `screened_to_interview` and `interview_to_offer` values are therefore
mathematically correct for the currently recorded application states. They are
not a UI-only display failure.

## Reproducible calculation

The backend defines funnel stages cumulatively in
`apps/api/app/routers/analytics.py`:

- applied: distinct application job IDs with a non-`draft` status;
- screened: application status in `screening`, `interview`, or `offer`;
- interviewed: application status in `interview` or `offer`;
- offers: application status `offer`.

`GET /analytics/conversion` calculates the stage rates directly from those
counts and returns `0.0` if a denominator is zero. The application-board Sankey
uses the same cumulative status definitions in
`apps/api/app/routers/applications.py`, so neither surface fabricates a rate or
uses an incompatible exact-status bucket.

## Stage progression mechanism

There is deliberately no process that infers an employer response or advances a
submitted application automatically:

1. `POST /applications/{application_id}/submit` only records that the user
   applied on the employer's site and changes `draft` to `submitted`.
2. `POST /applications/{application_id}/move` is the explicit, authenticated
   user-controlled transition for `submitted → screening → interview → offer`
   (and supported backward corrections). It writes an `application.stage_move`
   audit event atomically with the status update.
3. Approval resolution can promote a draft to `submitted`; it does not promote
   an application to screening, interview, or offer.
4. The ARQ board-sweep worker automates tailoring and cover-letter generation
   only. It explicitly states that it never submits applications and treats any
   job with an Application row as complete; it has no path to advance employer
   outcome stages.
5. The interview workspace is intentionally empty until an application has
   already progressed to `interview`; it is not an interview-scheduling or ATS
   ingestion integration.

## RCA

**Classification: expected behavior / product-integration gap, not a backend or
UI progression bug.** The product has no connected source of employer outcome
events (ATS webhook, inbox/recruiter-message classifier, calendar scheduling
integration, or user-recorded outcome). Advancing a status automatically from
`submitted` would invent an employer response and violate the human-in-the-loop
and truthfulness requirements.

The two existing `screening` applications demonstrate that the funnel can
represent an advanced state. Zero `interview` and `offer` rows explain the zero
rates; the API and board display those source states faithfully.

## Operational next action

Keep zero rates and show an honest next action: record a verified employer
response, or connect an approved outcome-event source before moving a card.
Do **not** add a timer- or agent-based Submitted→Screened→Interview transition.

For future independently reproducible evidence, run the following against an
authorized database/session for the same user and time period, retain only
redacted aggregates, and compare it to `/analytics/funnel` and
`/analytics/conversion`:

```sql
SELECT "status", COUNT(*) AS application_rows,
       COUNT(DISTINCT "jobId") AS distinct_jobs
FROM "Application"
WHERE "userId" = :user_id
GROUP BY "status"
ORDER BY "status";
```

Then verify:

- `applied = COUNT(DISTINCT jobId WHERE status <> 'draft')`
- `screened = COUNT(status IN ('screening', 'interview', 'offer'))`
- `interviewed = COUNT(status IN ('interview', 'offer'))`
- `offers = COUNT(status = 'offer')`

This investigation did not mutate production application records.

## Evidence

- `docs/delivery/PHASE4-GAP-ANALYSIS.md`, lines 197–208 (reported funnel and
  missing prior raw-record recomputation).
- `apps/api/app/routers/analytics.py`, `funnel()` and `conversion()`.
- `apps/api/app/routers/applications.py`, `move_application()` and
  `submit_application()`.
- `apps/api/app/workers/board_sweep.py`, module contract and eligibility rules.
- `apps/api/app/workers/settings.py`, active ARQ registration/cron schedule.
- `packages/db/src/schema.prisma`, `ApplicationStatus` enum.

A production database aggregate query was prepared but could not be executed
within this agent run because the command runner required external approval.
No unverified database count is asserted in this report beyond the authenticated
Phase 4 observation above.
