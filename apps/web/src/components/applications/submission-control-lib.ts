/**
 * U5d-2 — the per-card submit control: state vocabulary + the click sequence.
 *
 * USER MANDATE (2026-08-14): every application card gets a channel-aware
 * control, and the click IS the user's approval for THAT application.
 *
 * WHAT LIVES HERE AND WHAT DOES NOT. The card's *state* is decided by the
 * backend (`apps/api/app/services/submission_control.py`) and arrives on the
 * row as `submissionControl`; this module does not re-derive it. Deriving a
 * submission state on the client is exactly how the Submitted column ended up
 * asserting 346 submissions the database could not support
 * (`uat/reports/evidence/agents-uplift/u5d/FORENSICS.md`). What lives here is
 * the part the server genuinely cannot observe: the browser's own in-flight
 * request, and the sequence that request performs.
 *
 * THE SEQUENCE, and why it is two calls and not one:
 *
 *   1. `POST /applications/{id}/request-submission` — records the user's
 *      approval (create + approve, the same repository the Approvals screen
 *      uses). Transmits nothing.
 *   2. `POST /approvals/{id}/execute` — the EXISTING execute endpoint and its
 *      single-shot `claim_execution` guard. This is the ONLY place in the
 *      product where a real submission can happen, and the per-card control
 *      deliberately goes through it rather than gaining a private route.
 *   3. re-read the application row.
 *
 * STEP 3 IS NOT OPTIONAL. The card reaches "Submitted ✓" if and ONLY IF the
 * re-read row carries a real `transmittedAt`. Step 2's response is treated as
 * advisory: a transport that answered `{transmitted: true}` without the row
 * agreeing would still not paint a success here.
 */
import {
  executeApproval as defaultExecuteApproval,
  fetchApplication as defaultFetchApplication,
  requestSubmission as defaultRequestSubmission,
  type Application,
  type SubmissionControl,
} from "../../lib/api/applications";

/** The transient states the SERVER cannot observe — owned by this client. */
export type LocalSubmissionState = "idle" | "submitting" | "failed";

export type CardSubmissionOutcome =
  | { kind: "transmitted"; application: Application; ref: string | null }
  | { kind: "manual_step"; application: Application | null; reason: string; detail: string }
  | { kind: "failed"; detail: string };

export interface CardSubmissionDeps {
  requestSubmission?: typeof defaultRequestSubmission;
  executeApproval?: typeof defaultExecuteApproval;
  fetchApplication?: typeof defaultFetchApplication;
}

/**
 * `true` only when the row itself proves a transmission.
 *
 * The single predicate every "Submitted ✓" render in this screen must pass
 * through, so there is one place to audit rather than one per component.
 */
export function hasTransmissionProof(app: Pick<Application, "transmittedAt"> | null): boolean {
  return Boolean(app && app.transmittedAt);
}

/**
 * The state to RENDER, given the server's control block and the local
 * in-flight state.
 *
 * The local state can only ever add `submitting`/`failed` on top of a
 * server state; it can never upgrade a card to `submitted`. That direction is
 * closed by construction: this function returns the server's own state for
 * everything else, and `submitted` is only ever produced by the server, which
 * only produces it from a persisted `transmittedAt`.
 */
export function cardStateFor(
  control: SubmissionControl | null | undefined,
  local: LocalSubmissionState = "idle",
): string {
  if (local === "submitting") return "submitting";
  if (local === "failed") return "failed";
  return control?.state ?? "draft";
}

/** Whether this control's action is one the user can press right now. */
export function isPressable(control: SubmissionControl | null | undefined): boolean {
  if (!control) return false;
  return control.action === "submit" || control.action === "send_email";
}

/**
 * Run the full click sequence for ONE application.
 *
 * Never throws: every failure becomes an honest `failed` outcome carrying the
 * real message, because a rejected promise on this path would leave the card
 * with no way to say what went wrong. Nothing here can report a submission the
 * re-read row does not support.
 */
export async function runCardSubmission(
  applicationId: string,
  deps: CardSubmissionDeps = {},
): Promise<CardSubmissionOutcome> {
  const request = deps.requestSubmission ?? defaultRequestSubmission;
  const execute = deps.executeApproval ?? defaultExecuteApproval;
  const read = deps.fetchApplication ?? defaultFetchApplication;

  let approvalId: string;
  try {
    approvalId = (await request(applicationId)).approvalId;
  } catch (error) {
    return { kind: "failed", detail: messageOf(error, "Could not record your approval.") };
  }

  let executed: Awaited<ReturnType<typeof defaultExecuteApproval>>;
  try {
    executed = await execute(approvalId);
  } catch (error) {
    return {
      kind: "failed",
      detail: messageOf(error, "The submission did not complete — nothing was sent."),
    };
  }

  // The row is the authority, not the response. Read it back before claiming
  // anything at all.
  let application: Application | null = null;
  try {
    application = await read(applicationId);
  } catch {
    application = null;
  }

  if (hasTransmissionProof(application)) {
    return {
      kind: "transmitted",
      application: application as Application,
      ref: application?.transmissionRef ?? null,
    };
  }
  if (executed.status === "manual_step" || application?.manualStepReason) {
    return {
      kind: "manual_step",
      application,
      reason: executed.reason ?? application?.manualStepReason ?? "manual_step_required",
      detail:
        executed.detail ??
        application?.manualStepDetail ??
        "This application needs a step Aether will not take for you.",
    };
  }
  // Executed, but the row shows no proof. Say exactly that.
  return {
    kind: "failed",
    detail:
      executed.detail ??
      "Aether cannot show evidence this application was transmitted, so it is not marked as submitted.",
  };
}

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
