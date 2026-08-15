// @vitest-environment jsdom
/**
 * U5 closing round 4 — the EMAIL half of the mandate, end-to-end and honestly
 * retryable.
 *
 * MUST-FIX 1 (round-4 re-review): an application whose posting publishes an
 * application address is queued as an approval of type `application_submit`
 * with `payload.kind = "submission"` (apps/api/app/services/
 * application_submission.py `queue_submission_approval`), and
 * `POST /approvals/{id}/execute` REALLY transmits that one
 * (apps/api/app/routers/approvals.py `_execute_application_submit` ->
 * `transmit_application`). The Approvals UI gated its only `executeApproval`
 * call on `type === "email_send"`, so approving an email-channel application
 * flipped the row to `approved` and sent NOTHING, while
 * `notTransmittedReason` told the user "Approve it in Approvals to email it
 * to the employer". Execution must be routed by the application's resolved
 * channel (an email destination), not by the approval type alone — from all
 * three decision surfaces: card, modal, bulk.
 *
 * MUST-FIX 2: a send that FAILS releases the server-side execution claim
 * (`release_execution`), leaving the approval `approved` with nothing sent —
 * and the default `pending` filter hid that row completely, so the failure
 * copy pointed at a retry that did not exist. Approved-but-unsent requests
 * must surface with a visible state chip and a working `Retry send` that
 * re-invokes the same (idempotent) execute path.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../../lib/api/approvals";

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../lib/api/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/approvals")>();
  return { ...actual, fetchApprovals: (...args: unknown[]) => fetchApprovalsMock(...args) };
});

const decideApprovalMock = vi.hoisted(() => vi.fn());
const executeApprovalMock = vi.hoisted(() => vi.fn());
const fetchApprovalMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../components/approvals/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../components/approvals/api")>();
  return {
    ...actual,
    fetchApproval: (...args: unknown[]) => fetchApprovalMock(...args),
    decideApproval: (...args: unknown[]) => decideApprovalMock(...args),
    executeApproval: (...args: unknown[]) => executeApprovalMock(...args),
  };
});

// eslint-disable-next-line import/first
import ApprovalsPage from "../page";

/** An application the employer accepts BY EMAIL — the row `queue_submission_approval`
 *  writes when `resolve_job_apply_recipient` found a genuine published address. */
function emailSubmission(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-submission",
    userId: "u1",
    applicationId: "app-1",
    type: "application_submit",
    status: "pending",
    payload: {
      kind: "submission",
      recipient: "careers@examplecorp.com",
      recipient_source: "description_mailto",
      job_title: "Senior Delivery Lead",
      company: "ExampleCorp",
    },
    createdAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    resolvedAt: null,
    ...overrides,
  };
}

/** An `application_submit` that approves an ARTIFACT (a tailored résumé, a
 *  cover letter). The backend transmits nothing for these — the UI must not
 *  execute them (negative control for the widened gate). */
function artifactApproval(overrides: Partial<Approval> = {}): Approval {
  return emailSubmission({
    id: "appr-artifact",
    payload: { kind: "cover_letter", job_title: "Senior Delivery Lead", company: "ExampleCorp" },
    ...overrides,
  });
}

function resetHistory() {
  window.history.replaceState(null, "", "/dashboard/approvals");
}

beforeEach(() => {
  resetHistory();
  fetchApprovalsMock.mockResolvedValue([]);
  fetchApprovalMock.mockReset();
  decideApprovalMock.mockReset();
  executeApprovalMock.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  fetchApprovalsMock.mockReset();
  resetHistory();
  vi.restoreAllMocks();
});

describe("approving an EMAIL-channel application submission really sends it (MUST-FIX 1)", () => {
  it("fires executeApproval from the single-card approve", async () => {
    const row = emailSubmission();
    fetchApprovalsMock.mockResolvedValue([row]);
    decideApprovalMock.mockResolvedValue(emailSubmission({ status: "approved" }));
    executeApprovalMock.mockResolvedValue(undefined);

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("approve-btn"));

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledWith("appr-submission"));
  });

  it("fires executeApproval from the review modal's approve", async () => {
    fetchApprovalsMock.mockResolvedValue([emailSubmission()]);
    decideApprovalMock.mockResolvedValue(emailSubmission({ status: "approved" }));
    executeApprovalMock.mockResolvedValue(undefined);

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("review-btn"));
    fireEvent.click(await screen.findByTestId("modal-approve-btn"));

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledWith("appr-submission"));
  });

  it("fires executeApproval from bulk approve, and never for an artifact approval", async () => {
    const second = emailSubmission({ id: "appr-submission-2" });
    fetchApprovalsMock.mockResolvedValue([emailSubmission(), second, artifactApproval()]);
    decideApprovalMock.mockImplementation(async (id: string) =>
      id === "appr-artifact"
        ? artifactApproval({ status: "approved" })
        : emailSubmission({ id, status: "approved" }),
    );
    executeApprovalMock.mockResolvedValue(undefined);

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("bulk-approve-btn"));

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledTimes(2));
    expect(executeApprovalMock).toHaveBeenCalledWith("appr-submission");
    expect(executeApprovalMock).toHaveBeenCalledWith("appr-submission-2");
    expect(executeApprovalMock).not.toHaveBeenCalledWith("appr-artifact");
  });

  it("never executes an application_submit that carries no submission payload", async () => {
    fetchApprovalsMock.mockResolvedValue([artifactApproval()]);
    decideApprovalMock.mockResolvedValue(artifactApproval({ status: "approved" }));

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("approve-btn"));

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalled());
    expect(executeApprovalMock).not.toHaveBeenCalled();
  });
});

describe("a failed send stays visible and is really retryable (MUST-FIX 2)", () => {
  /** Queue state: `pending` (the default filter) is empty, and the only
   *  approved row is one whose send never completed — `executionState` null
   *  means the server released its execution claim, i.e. NOTHING was sent. */
  function strandedQueue(state: Approval["executionState"] = null) {
    const stranded = emailSubmission({
      status: "approved",
      resolvedAt: new Date().toISOString(),
      executionState: state,
    });
    fetchApprovalsMock.mockImplementation(async (status: string) =>
      status === "approved" ? [stranded] : [],
    );
    return stranded;
  }

  it("surfaces the approved-but-unsent request under the default pending filter", async () => {
    strandedQueue();

    render(<ApprovalsPage />);

    expect(await screen.findByTestId("retry-send-btn")).toBeTruthy();
    expect((await screen.findByTestId("unsent-badge")).textContent).toMatch(/not sent/i);
  });

  it("does NOT offer a retry for a request whose send provably completed", async () => {
    strandedQueue("executed");

    render(<ApprovalsPage />);

    await waitFor(() => expect(fetchApprovalsMock).toHaveBeenCalledWith("approved"));
    await waitFor(() => expect(screen.queryByTestId("retry-send-btn")).toBeNull());
    expect(screen.queryByTestId("unsent-badge")).toBeNull();
  });

  it("retry re-invokes the execute path and lands on an honest terminal state", async () => {
    const stranded = emailSubmission({
      status: "approved",
      resolvedAt: new Date().toISOString(),
      executionState: null,
    });
    let sent = false;
    fetchApprovalsMock.mockImplementation(async (status: string) =>
      status === "approved"
        ? [sent ? { ...stranded, executionState: "executed" as const } : stranded]
        : [],
    );
    executeApprovalMock.mockImplementation(async () => {
      sent = true;
    });

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("retry-send-btn"));

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledWith("appr-submission"));
    // Honest terminal state: the row is no longer advertised as unsent, and
    // the retry affordance is gone because there is nothing left to retry.
    await waitFor(() => expect(screen.queryByTestId("retry-send-btn")).toBeNull());
    expect(screen.queryByTestId("unsent-badge")).toBeNull();
  });

  it("a 200 manual_step outcome is SHOWN, never rendered as nothing", async () => {
    // Owner-reported (2026-08-15, Easygo): the site path answers 200 with
    // transmitted:false when the agent hit an honest obstacle, and the old
    // retry discarded that body — the click looked like NOTHING happened.
    strandedQueue();
    executeApprovalMock.mockResolvedValue({
      status: "manual_step",
      transmitted: false,
      reason: "unknown_required_question",
      detail: "Aether needs your answer to: Country",
    });

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("retry-send-btn"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/not sent/i);
    expect(alert.textContent).toMatch(/needs your answer to: country/i);
    expect(alert.textContent).toMatch(/applications page/i);
  });

  it("a retry that fails again says nothing was sent and keeps the affordance", async () => {
    strandedQueue();
    executeApprovalMock.mockRejectedValue(new Error("Gmail authorization expired"));

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("retry-send-btn"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/nothing was sent/i);
    expect(alert.textContent).toMatch(/gmail/i);
    expect(screen.getByTestId("retry-send-btn")).toBeTruthy();
  });

  it("the single-card failure copy names the Retry send affordance, which is then on screen", async () => {
    // Server sequence, exactly: the row is pending until it is decided, then
    // it is approved-with-nothing-executed (the send failed and the claim was
    // released), so it leaves the pending list and enters the approved one.
    const stranded = emailSubmission({
      status: "approved",
      resolvedAt: new Date().toISOString(),
      executionState: null,
    });
    let decided = false;
    fetchApprovalsMock.mockImplementation(async (status: string) => {
      if (status === "approved") return decided ? [stranded] : [];
      return decided ? [] : [emailSubmission()];
    });
    decideApprovalMock.mockImplementation(async () => {
      decided = true;
      return emailSubmission({ status: "approved" });
    });
    executeApprovalMock.mockRejectedValue(new Error("No Gmail account connected"));

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("approve-btn"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/retry send/i);
    expect(await screen.findByTestId("retry-send-btn")).toBeTruthy();
  });

  it("the bulk failure copy names the Retry send affordance, which is then on screen", async () => {
    const ids = ["appr-submission", "appr-submission-2"];
    const decided = new Set<string>();
    fetchApprovalsMock.mockImplementation(async (status: string) => {
      const rows = ids.map((id) =>
        emailSubmission({
          id,
          ...(decided.has(id)
            ? { status: "approved" as const, resolvedAt: new Date().toISOString() }
            : {}),
        }),
      );
      return rows.filter((r) => (status === "approved" ? decided.has(r.id) : !decided.has(r.id)));
    });
    decideApprovalMock.mockImplementation(async (id: string) => {
      decided.add(id);
      return emailSubmission({ id, status: "approved" });
    });
    executeApprovalMock.mockRejectedValue(new Error("No Gmail account connected"));

    render(<ApprovalsPage />);
    fireEvent.click(await screen.findByTestId("bulk-approve-btn"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/retry send/i);
    expect(alert.textContent).not.toMatch(/decisions? failed/i);
    // One retryable row per failed send — the copy's "affected requests
    // below" is literally true, not a pointer at an empty screen.
    expect(await screen.findAllByTestId("retry-send-btn")).toHaveLength(2);
    expect(screen.getAllByTestId("unsent-badge")).toHaveLength(2);
  });
});
