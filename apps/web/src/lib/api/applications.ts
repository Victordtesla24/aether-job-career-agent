/** Typed applications API client (P2 frontend wiring). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

/**
 * U5d-2 — the per-application submit control.
 *
 * `state` and `action` are BACKEND-decided (see
 * `apps/api/app/services/submission_control.py`); the two transient states the
 * server cannot observe — `submitting` and `failed` — are added by this client
 * and only for the lifetime of its own in-flight request. `state` is a plain
 * string rather than a closed enum on purpose: an API build that adds a new
 * honest state must degrade to "render its label and offer nothing" here,
 * never throw a parse error that blanks the whole board.
 */
export const SubmissionControlSchema = z.object({
  state: z.string(),
  action: z.enum([
    "submit",
    "send_email",
    "open_posting",
    "reconfirm",
    "fix_artifacts",
    "none",
  ]),
  label: z.string(),
  detail: z.string(),
  channel: z.string(),
  applyUrl: z.string().nullish(),
  href: z.string().nullish(),
  missing: z.array(z.string()).default([]),
});

export type SubmissionControl = z.infer<typeof SubmissionControlSchema>;

export const ApplicationSchema = z.object({
  id: z.string(),
  jobId: z.string(),
  resumeId: z.string(),
  status: z.enum(["draft", "submitted", "screening", "interview", "offer", "rejected", "withdrawn"]),
  coverLetter: z.string().nullish(),
  jobTitle: z.string(),
  company: z.string(),
  applyUrl: z.string().nullish(),
  createdAt: z.string(),
  updatedAt: z.string(),
  // W-SUB — the truth about transmission, which `status` alone cannot carry.
  //
  // `status: "submitted"` has always meant "marked as submitted"; it has NEVER
  // meant "Aether emailed this to the employer", because until W-SUB nothing
  // in the product could send an application at all. These fields make the
  // difference visible instead of letting the stage label imply a send:
  //   transmitted      — did a message actually leave the system?
  //   submissionState  — "transmitted" | "not_transmitted"
  //   transmittedTo/At — checkable evidence for a positive claim
  //   autoSubmittable  — does the posting publish an address we could send to?
  // Nullish-tolerant so an older API build (or a cached response) degrades to
  // "unknown" rather than throwing — the UI treats absent as "don't claim".
  transmitted: z.boolean().nullish(),
  submissionState: z.enum(["transmitted", "not_transmitted"]).nullish(),
  transmittedAt: z.string().nullish(),
  transmittedTo: z.string().nullish(),
  transmissionChannel: z.string().nullish(),
  transmissionRef: z.string().nullish(),
  autoSubmittable: z.boolean().nullish(),
  applyEmail: z.string().nullish(),
  applyEmailSource: z.string().nullish(),
  // U5 — the honest "or an actionable manual step" half of the NO-PREPARED-ONLY
  // invariant (apps/api/app/services/apply_executor.py record_manual_step /
  // apply_channel_resolver.py). Additive nullable DB columns
  // (applyChannel/manualStepReason/manualStepDetail/manualStepAt), SELECTed by
  // both read endpoints via apps/api/app/routers/applications.py `_COLUMNS`
  // and pinned there by apps/api/tests/test_u5_applications_read_manual_step.py
  // — without that SELECT the whole manual-step UI below is dead code and a
  // blocked application reads to the user as silently "prepared only".
  // Still declared nullish, deliberately: an older API build that omits them
  // must read as "unknown, don't claim a manual step" (the same honest-degrade
  // rule `transmitted` uses above) rather than fail the parse.
  applyChannel: z.string().nullish(),
  manualStepReason: z.string().nullish(),
  manualStepDetail: z.string().nullish(),
  manualStepAt: z.string().nullish(),
  // U5d — the honest reclassification of a row that CLAIMS a submission with
  // no transmission evidence. Since U5d-2 this is also stamped at WRITE time
  // by every bookkeeping path, so "recorded_not_transmitted" now means "the
  // writer itself said it transmitted nothing", not "a census guessed later".
  submissionTruthState: z.string().nullish(),
  submissionTruthNote: z.string().nullish(),
  // U5d-2 — the per-card submit control, computed ONCE on the server from the
  // persisted columns (apps/api/app/services/submission_control.py). The UI
  // renders what it is given: deriving a card state client-side is how the
  // Submitted column ended up asserting 346 submissions the database could not
  // support. Nullish-tolerant so an older API build degrades to "no control"
  // rather than throwing.
  submissionControl: SubmissionControlSchema.nullish(),
});

export type Application = z.infer<typeof ApplicationSchema>;

export async function fetchApplications(options: RequestOptions = {}): Promise<Application[]> {
  return z.array(ApplicationSchema).parse(await apiRequest<unknown>("/applications", options));
}

/** Single application detail — resume version + cover letter (audit defect D7). */
export async function fetchApplication(
  id: string,
  options: RequestOptions = {},
): Promise<Application> {
  return ApplicationSchema.parse(await apiRequest<unknown>(`/applications/${id}`, options));
}

/** Mark a draft application as submitted, recording the real apply URL used. */
export async function submitApplication(
  id: string,
  appliedUrl?: string | null,
  options: RequestOptions = {},
): Promise<Application> {
  return ApplicationSchema.parse(
    await apiRequest<unknown>(`/applications/${id}/submit`, {
      ...options,
      method: "POST",
      body: { applied_url: appliedUrl ?? null },
    }),
  );
}

const RequestSubmissionSchema = z.object({
  approvalId: z.string(),
  applicationId: z.string(),
  channel: z.string(),
  transmitted: z.literal(false),
  detail: z.string(),
});

export type RequestSubmissionResult = z.infer<typeof RequestSubmissionSchema>;

/**
 * U5d-2 — record the user's approval for THIS application. Step 1 of 2.
 *
 * The click on the card IS the approval (USER MANDATE 2026-08-14), so this
 * creates AND approves an `application_submit` ApprovalRequest server-side,
 * through the same repository the Approvals screen uses. It transmits nothing
 * — `transmitted` is a `z.literal(false)`, so a build that ever started
 * returning `true` here would fail the parse rather than let the UI paint a
 * success. Step 2 is {@link executeApproval}, the EXISTING execute endpoint.
 */
export async function requestSubmission(
  id: string,
  options: RequestOptions = {},
): Promise<RequestSubmissionResult> {
  return RequestSubmissionSchema.parse(
    await apiRequest<unknown>(`/applications/${id}/request-submission`, {
      ...options,
      method: "POST",
    }),
  );
}

const ExecuteSubmissionSchema = z.object({
  status: z.string(),
  transmitted: z.boolean(),
  applicationId: z.string().nullish(),
  channel: z.string().nullish(),
  reason: z.string().nullish(),
  detail: z.string().nullish(),
  transmittedAt: z.string().nullish(),
  transmissionRef: z.string().nullish(),
});

export type ExecuteSubmissionResult = z.infer<typeof ExecuteSubmissionSchema>;

/**
 * U5d-2 — step 2 of 2: execute the approval the click just recorded.
 *
 * This is the EXISTING `POST /approvals/{id}/execute` endpoint and its
 * single-shot `claim_execution` guard — deliberately not a new route, so the
 * per-card control cannot become a second way to submit that bypasses the gate.
 *
 * Its answer is ADVISORY. The card only ever reaches "Submitted ✓" by
 * re-reading the application row and finding a real `transmittedAt`, because
 * the row is the only thing that can prove a transmission happened.
 */
export async function executeApproval(
  approvalId: string,
  options: RequestOptions = {},
): Promise<ExecuteSubmissionResult> {
  return ExecuteSubmissionSchema.parse(
    await apiRequest<unknown>(`/approvals/${approvalId}/execute`, {
      ...options,
      method: "POST",
    }),
  );
}

const ApplySweepStatusSchema = z.object({ sweepEnabled: z.boolean() });

/**
 * Live read of the operator's `AETHER_APPLY_SWEEP_ENABLED` kill-switch
 * (`app.workers.apply_sweep.sweep_enabled()`, `GET
 * /applications/apply-sweep-status`) — SHOULD-FIX 6 (round-3 re-review): the
 * "automatic […] submission is not enabled on this deployment yet" copy
 * (tracker-lib.ts `notTransmittedReason` / `automaticSubmissionDisclaimer`)
 * used to be hardcoded with zero coupling to the real env var, true only by
 * accident and false the moment an operator turns the sweep on. Callers
 * should treat a rejected promise as `false` (the honest, code default) —
 * never fabricate the enabled state from a failed status check.
 */
export async function fetchApplySweepStatus(
  options: RequestOptions = {},
): Promise<boolean> {
  const data = await apiRequest<unknown>("/applications/apply-sweep-status", options);
  return ApplySweepStatusSchema.parse(data).sweepEnabled;
}
