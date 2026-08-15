/** Approval-modal API calls (decision context body + single-approval fetch). */
import {
  executeApproval as executeSubmission,
  type ExecuteSubmissionResult,
} from "../../lib/api/applications";
import { ApprovalSchema, type Approval } from "../../lib/api/approvals";
import { apiRequest } from "../../lib/api/client";

export interface DecisionContext {
  /** Human-edited preview from the Edit & Approve flow. */
  editedPreview?: string;
  /** "Trust this agent for similar decisions going forward". */
  trustAgent?: boolean;
  /**
   * U2c: the human's explicit "yes, I know it is below the quality floor".
   * The API REFUSES (409) to approve a below-floor artifact without it, and
   * records it on the payload so the decision stays attributable.
   */
  acknowledgeBelowFloor?: boolean;
}

function toBody(context: DecisionContext): Record<string, unknown> | undefined {
  const body: Record<string, unknown> = {};
  if (context.editedPreview !== undefined) body.edited_preview = context.editedPreview;
  if (context.trustAgent !== undefined) body.trust_agent = context.trustAgent;
  if (context.acknowledgeBelowFloor !== undefined) {
    body.acknowledge_below_floor = context.acknowledgeBelowFloor;
  }
  return Object.keys(body).length > 0 ? body : undefined;
}

export async function fetchApproval(id: string): Promise<Approval> {
  return ApprovalSchema.parse(await apiRequest<unknown>(`/approvals/${id}`));
}

export async function decideApproval(
  id: string,
  decision: "approve" | "reject",
  context: DecisionContext = {},
): Promise<Approval> {
  return ApprovalSchema.parse(
    await apiRequest<unknown>(`/approvals/${id}/${decision}`, {
      method: "POST",
      body: toBody(context),
    }),
  );
}

/**
 * Execute the high-risk action behind an *approved* request (MV-approval-modal-008).
 * Approving an approval only flips its status — for most types that's the
 * whole story (submission integrations land in a later phase), but for
 * `email_send` this is the ONLY call that actually sends the Gmail message;
 * approving alone never sends anything (see apps/api/app/routers/approvals.py
 * `execute_gated_action`/`_execute_email_send`).
 *
 * Returns the server's parsed outcome (delegating to the U5d-2 client in
 * `lib/api/applications`), because a site submission legitimately answers
 * 200 with `transmitted: false` (manual_step / no_confirmation / unproven)
 * and the caller must be able to SHOW that instead of rendering the click
 * as nothing — the owner-reported "nothing is happening" defect
 * (2026-08-15, Easygo). Callers that only care that the call fired may
 * still ignore the result.
 */
export async function executeApproval(id: string): Promise<ExecuteSubmissionResult> {
  return executeSubmission(id);
}
