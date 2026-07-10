/**
 * Fetch-based wiring for the Approval Modal against the live agent API
 * (docs/implementation/implementation_guide.html):
 *
 *   POST /api/agents/approve/:taskId   — submit a human decision
 *   GET  /api/agents/status/:taskId    — poll checkpoint state
 *
 * This is the production `submit` implementation injected into the controller.
 * It is deliberately transport-only: no UI state, so it stays framework-agnostic.
 */

import type {
  ApprovalDecisionPayload,
  ApprovalRequest,
} from "./types.js";

export interface ApprovalClientOptions {
  /** API origin, e.g. "" for same-origin or "https://…". Defaults to "". */
  baseUrl?: string;
  /** Injected fetch (defaults to global fetch); eases testing. */
  fetchImpl?: typeof fetch;
  /** Bearer token for the JWT-protected endpoints. */
  getToken?: () => string | null | undefined;
}

/** Shape returned by GET /api/agents/status/:taskId. */
export interface AgentStatusResponse {
  taskId: string;
  status:
    | "PENDING"
    | "RUNNING"
    | "WAITING_APPROVAL"
    | "COMPLETE"
    | "FAILED";
  progress: number;
  checkpoint?: { message: string; approvalRequired: boolean };
  error?: string;
}

export class ApprovalClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly getToken: () => string | null | undefined;

  constructor(options: ApprovalClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? "";
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    this.getToken = options.getToken ?? (() => null);
  }

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = this.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  /** Submit a decision. Throws on non-2xx so the controller surfaces an error. */
  async submitDecision(payload: ApprovalDecisionPayload): Promise<void> {
    const res = await this.fetchImpl(
      `${this.baseUrl}/api/agents/approve/${encodeURIComponent(payload.taskId)}`,
      {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({
          decision: payload.decision,
          trustAgent: payload.trustAgent,
        }),
      },
    );
    if (!res.ok) {
      throw new Error(
        `Approval ${payload.decision} failed (${res.status} ${res.statusText})`,
      );
    }
  }

  /** Poll the task checkpoint. Throws on non-2xx. */
  async fetchStatus(taskId: string): Promise<AgentStatusResponse> {
    const res = await this.fetchImpl(
      `${this.baseUrl}/api/agents/status/${encodeURIComponent(taskId)}`,
      { method: "GET", headers: this.headers() },
    );
    if (!res.ok) {
      throw new Error(
        `Status fetch failed (${res.status} ${res.statusText})`,
      );
    }
    return (await res.json()) as AgentStatusResponse;
  }
}

/**
 * Guard: only a task genuinely paused at the checkpoint should open the modal.
 * Prevents a stale/COMPLETE task from surfacing a decision UI (fixture-as-live).
 */
export function isApprovable(status: AgentStatusResponse): boolean {
  return (
    status.status === "WAITING_APPROVAL" &&
    status.checkpoint?.approvalRequired === true
  );
}

/** Bind an {@link ApprovalClient} to the controller's `submit` signature. */
export function createSubmitFn(
  client: ApprovalClient,
): (payload: ApprovalDecisionPayload) => Promise<void> {
  return (payload) => client.submitDecision(payload);
}

/** Re-export for consumers that only need the request type here. */
export type { ApprovalRequest };
