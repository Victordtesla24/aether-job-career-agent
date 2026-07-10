/**
 * Data contract for the global Approval Modal (design/screens/approval-modal.html
 * and design/screens/mobile-approval.html). This overlay is shown whenever an agent
 * task reaches the WAITING_APPROVAL checkpoint and needs a human decision.
 *
 * Backend contract (docs/implementation/implementation_guide.html):
 *   GET  /api/agents/status/:taskId  -> { status, progress, result?, checkpoint? }
 *   POST /api/agents/approve/:taskId -> submit a human decision at the checkpoint
 */

/** Severity of a single AI-reasoning line, driving its icon/colour. */
export type ReasoningSeverity = "positive" | "warning" | "negative";

/** One line in the "AI reasoning" list. */
export interface ReasoningItem {
  severity: ReasoningSeverity;
  text: string;
}

/** The agent that produced the action awaiting approval. */
export interface ApprovalAgent {
  /** Human-readable agent name, e.g. "Tailoring Agent". */
  name: string;
  /** Short description of what the agent wants to do. */
  action: string;
}

/** The concrete subject of the approval (a specific job application). */
export interface ApprovalSubject {
  /** Short badge label, e.g. company initials "CV". */
  badge: string;
  /** Role title, e.g. "Senior ML Engineer". */
  title: string;
  /** Company · location · source, e.g. "Canva · Sydney · via LinkedIn". */
  subtitle: string;
}

/** Optional generated-content preview (e.g. cover letter). */
export interface ApprovalPreview {
  label: string;
  body: string;
}

/**
 * Full payload rendered by the modal. Mirrors the agent status `checkpoint`
 * plus the resolved subject/reasoning needed to make an informed decision.
 */
export interface ApprovalRequest {
  /** Agent task id — the `:taskId` used by the approve/status endpoints. */
  taskId: string;
  agent: ApprovalAgent;
  subject: ApprovalSubject;
  /** Confidence score 0–100 (mono-formatted in the UI). */
  confidence: number;
  /** Plain-language explanation of why a human gate fired. */
  whyApproval: string;
  reasoning: ReasoningItem[];
  preview?: ApprovalPreview;
}

/** The three terminal user decisions the modal can emit. */
export type ApprovalDecision = "approve" | "reject" | "edit";

/** Body POSTed to /api/agents/approve/:taskId. */
export interface ApprovalDecisionPayload {
  taskId: string;
  decision: ApprovalDecision;
  /** "Trust this agent for similar decisions going forward" checkbox. */
  trustAgent: boolean;
}

/** Lifecycle of the modal. */
export type ApprovalStatus =
  | "closed"
  | "open"
  | "submitting"
  | "resolved"
  | "error";

/** Immutable snapshot consumed by any view (React, DOM, etc.). */
export interface ApprovalModalState {
  status: ApprovalStatus;
  request: ApprovalRequest | null;
  trustAgent: boolean;
  /** Set once a decision resolves successfully. */
  decision: ApprovalDecision | null;
  error: string | null;
}

/**
 * Async sink for a decision. In production this is backed by
 * `POST /api/agents/approve/:taskId`; in tests it is injected.
 */
export type ApprovalSubmitFn = (
  payload: ApprovalDecisionPayload,
) => Promise<void>;
