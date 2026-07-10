/**
 * Framework-agnostic controller ("headless hook") for the global Approval Modal.
 *
 * It owns all interaction logic — open/close, the three decisions, the trust
 * toggle, submit lifecycle, keyboard semantics, focus order and ARIA wiring — so
 * the same behaviour can be bound to a React component, a mobile sheet, or the
 * current vanilla harness without duplication. The store exposes a
 * `subscribe`/`getSnapshot` pair compatible with React's `useSyncExternalStore`.
 */

import type {
  ApprovalDecision,
  ApprovalModalState,
  ApprovalRequest,
  ApprovalStatus,
  ApprovalSubmitFn,
} from "./types.js";

/** Stable ids used for ARIA wiring and the focus order. */
export const APPROVAL_IDS = {
  dialog: "approval-modal",
  title: "approval-modal-title",
  description: "approval-modal-why",
  close: "approval-modal-close",
  trust: "approval-modal-trust",
  reject: "approval-modal-reject",
  edit: "approval-modal-edit",
  approve: "approval-modal-approve",
} as const;

/** Tab order inside the dialog (used by the focus trap). */
export const FOCUS_ORDER: readonly string[] = [
  APPROVAL_IDS.close,
  APPROVAL_IDS.trust,
  APPROVAL_IDS.reject,
  APPROVAL_IDS.edit,
  APPROVAL_IDS.approve,
];

export interface ApprovalAriaProps {
  role: "dialog";
  "aria-modal": true;
  "aria-labelledby": string;
  "aria-describedby": string;
}

export interface ApprovalControllerOptions {
  submit: ApprovalSubmitFn;
  /** Which control receives focus when the modal opens. Defaults to "approve". */
  initialFocus?: keyof typeof APPROVAL_IDS;
  /** Notified after a decision resolves successfully. */
  onResolved?: (decision: ApprovalDecision, request: ApprovalRequest) => void;
  /** Notified when the modal fully closes (dismiss or post-resolve). */
  onClose?: () => void;
}

type Listener = () => void;

const CLOSED_STATE: ApprovalModalState = {
  status: "closed",
  request: null,
  trustAgent: false,
  decision: null,
  error: null,
};

export class ApprovalModalController {
  private state: ApprovalModalState = CLOSED_STATE;
  private readonly listeners = new Set<Listener>();
  private readonly submit: ApprovalSubmitFn;
  private readonly initialFocus: string;
  private readonly onResolved?: ApprovalControllerOptions["onResolved"];
  private readonly onClose?: ApprovalControllerOptions["onClose"];

  constructor(options: ApprovalControllerOptions) {
    this.submit = options.submit;
    this.initialFocus = APPROVAL_IDS[options.initialFocus ?? "approve"];
    this.onResolved = options.onResolved;
    this.onClose = options.onClose;
  }

  // ── store plumbing (useSyncExternalStore-compatible) ──────────────────────
  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): ApprovalModalState => this.state;

  private setState(patch: Partial<ApprovalModalState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  // ── lifecycle ─────────────────────────────────────────────────────────────
  open(request: ApprovalRequest): void {
    this.setState({
      status: "open",
      request,
      trustAgent: false,
      decision: null,
      error: null,
    });
  }

  /** Dismiss without a decision. No-op while a decision is in flight. */
  close(): void {
    if (this.state.status === "submitting") return;
    this.state = CLOSED_STATE;
    for (const listener of this.listeners) listener();
    this.onClose?.();
  }

  toggleTrust(next?: boolean): void {
    if (this.state.status !== "open" && this.state.status !== "error") return;
    this.setState({
      trustAgent: next ?? !this.state.trustAgent,
    });
  }

  // ── decisions ─────────────────────────────────────────────────────────────
  approve(): Promise<void> {
    return this.decide("approve");
  }

  reject(): Promise<void> {
    return this.decide("reject");
  }

  editApprove(): Promise<void> {
    return this.decide("edit");
  }

  private async decide(decision: ApprovalDecision): Promise<void> {
    const { request, status } = this.state;
    if (!request) return;
    // Guard against double-submit and acting on a resolved/closed modal.
    if (status !== "open" && status !== "error") return;

    const trustAgent = this.state.trustAgent;
    this.setState({ status: "submitting", error: null });
    try {
      await this.submit({ taskId: request.taskId, decision, trustAgent });
      this.setState({ status: "resolved", decision });
      this.onResolved?.(decision, request);
    } catch (err) {
      this.setState({
        status: "error",
        error: err instanceof Error ? err.message : "Submission failed",
      });
    }
  }

  // ── a11y & keyboard ───────────────────────────────────────────────────────
  getAriaProps(): ApprovalAriaProps {
    return {
      role: "dialog",
      "aria-modal": true,
      "aria-labelledby": APPROVAL_IDS.title,
      "aria-describedby": APPROVAL_IDS.description,
    };
  }

  /** Element id that should receive focus when the modal mounts. */
  getInitialFocusId(): string {
    return this.initialFocus;
  }

  /**
   * Cycle focus within the dialog. Returns the id that should be focused next,
   * implementing a wrap-around Tab trap. `currentId` is the currently focused id.
   */
  nextFocusId(currentId: string, shiftKey = false): string {
    const idx = FOCUS_ORDER.indexOf(currentId);
    if (idx === -1) return FOCUS_ORDER[0];
    const delta = shiftKey ? -1 : 1;
    const nextIdx = (idx + delta + FOCUS_ORDER.length) % FOCUS_ORDER.length;
    return FOCUS_ORDER[nextIdx];
  }

  /**
   * Handle a keydown by name (e.g. "Escape", "Tab"). Returns true if the event
   * was consumed and the caller should `preventDefault()`.
   */
  handleKeydown(key: string, shiftKey = false): boolean {
    if (this.state.status === "closed" || this.state.status === "resolved") {
      return false;
    }
    if (key === "Escape") {
      this.close();
      return true;
    }
    if (key === "Tab") {
      // Focus movement is applied by the view; we consume Tab to keep the trap.
      return true;
    }
    void shiftKey;
    return false;
  }

  // ── convenience getters ────────────────────────────────────────────────────
  get status(): ApprovalStatus {
    return this.state.status;
  }

  get isOpen(): boolean {
    return this.state.status !== "closed";
  }
}

/** Factory mirroring a hook call site. */
export function createApprovalModalController(
  options: ApprovalControllerOptions,
): ApprovalModalController {
  return new ApprovalModalController(options);
}
