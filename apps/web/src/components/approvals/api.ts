/** Approval-modal API calls (decision context body + single-approval fetch). */
import { ApprovalSchema, type Approval } from "../../lib/api/approvals";
import { apiRequest } from "../../lib/api/client";

export interface DecisionContext {
  /** Human-edited preview from the Edit & Approve flow. */
  editedPreview?: string;
  /** "Trust this agent for similar decisions going forward". */
  trustAgent?: boolean;
}

function toBody(context: DecisionContext): Record<string, unknown> | undefined {
  const body: Record<string, unknown> = {};
  if (context.editedPreview !== undefined) body.edited_preview = context.editedPreview;
  if (context.trustAgent !== undefined) body.trust_agent = context.trustAgent;
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
 */
export async function executeApproval(id: string): Promise<void> {
  await apiRequest<unknown>(`/approvals/${id}/execute`, { method: "POST" });
}
