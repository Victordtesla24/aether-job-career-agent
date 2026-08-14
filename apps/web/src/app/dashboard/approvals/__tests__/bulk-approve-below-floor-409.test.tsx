// @vitest-environment jsdom
/**
 * ticket/bulkapprove-409 — production defect: 16× "POST /approvals/{id}/approve
 * → 409 Conflict" at 20:12Z (evidence: /var/log/aether/api.log), user saw
 * "16 of 16 bulk approve decisions failed — the rest were applied".
 *
 * `bulkDecide`'s `catch {}` swallowed every decideApproval error anonymously,
 * so the U2c below-quality-floor 409 (an informed-consent gate, NOT a
 * failure — see apps/api/app/routers/approvals.py
 * `_require_below_floor_acknowledgement`) was counted as a generic decision
 * failure with zero explanation and no recourse, and the summary claimed
 * "the rest were applied" even when nothing was applied at all.
 *
 * Fix mirrors the established contract from b1eef41 (dashboard inline
 * Approve, apps/web/src/app/dashboard/page.tsx) EXACTLY: detect the 409 via
 * `e instanceof ApiError && e.status === 409 &&
 * /acknowledge_below_floor/.test(e.message)`, extract the reason via
 * `/Below quality floor:[^"]*?floor\.?/i`, and offer ONE acknowledgement
 * retry — `decideApproval(id, "approve", { acknowledgeBelowFloor: true })` —
 * gated behind an explicit `window.confirm`. No silent auto-acknowledge.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../../lib/api/approvals";
import { ApiError } from "../../../../lib/api/client";

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../lib/api/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/approvals")>();
  return { ...actual, fetchApprovals: (...args: unknown[]) => fetchApprovalsMock(...args) };
});

const decideApprovalMock = vi.hoisted(() => vi.fn());
const executeApprovalMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../components/approvals/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../components/approvals/api")>();
  return {
    ...actual,
    decideApproval: (...args: unknown[]) => decideApprovalMock(...args),
    executeApproval: (...args: unknown[]) => executeApprovalMock(...args),
  };
});

// eslint-disable-next-line import/first
import ApprovalsPage from "../page";

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: { job_title: "Senior ML Engineer", company: "Canva" },
    createdAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    resolvedAt: null,
    ...overrides,
  };
}

/** The real production 409 body shape (apps/api/app/services/quality_gate.py
 *  `summary` + apps/api/app/routers/approvals.py `_require_below_floor_acknowledgement`). */
function belowFloorError(id: string): ApiError {
  return new ApiError(
    `POST /approvals/${id}/approve failed (409): {"detail":"Below quality floor: 2 dimensions did not ` +
      `clear the 80% floor — Keyword Match (61.4% vs 80% floor); Experience Match (70.0% vs 80% floor). ` +
      'This artifact is below the quality floor on 2 dimension(s) — Keyword Match, Experience Match. It ' +
      "has NOT been withheld: you can read it, edit it and approve it. But approving it has to be a " +
      "deliberate choice, so re-send this decision with acknowledge_below_floor=true " +
      '("I understand this content scored below the quality floor").\"}',
    409,
  );
}

function resetHistory() {
  window.history.replaceState(null, "", "/dashboard/approvals");
}

beforeEach(() => {
  resetHistory();
  decideApprovalMock.mockReset();
  executeApprovalMock.mockReset();
});

afterEach(() => {
  cleanup();
  fetchApprovalsMock.mockReset();
  resetHistory();
  vi.restoreAllMocks();
});

describe("bulk-approve honestly handles the U2c below-quality-floor 409 (ticket/bulkapprove-409)", () => {
  it("classifies below-floor 409s separately from real failures and retries with acknowledgement on confirm", async () => {
    const targets = [
      approval({ id: "appr-1" }),
      approval({ id: "appr-2" }),
    ];
    fetchApprovalsMock.mockResolvedValue(targets);
    decideApprovalMock.mockImplementation(async (id: string, _decision: string, context?: unknown) => {
      if (context && (context as { acknowledgeBelowFloor?: boolean }).acknowledgeBelowFloor) {
        return approval({ id, status: "approved" });
      }
      throw belowFloorError(id);
    });
    // First confirm: the bulk pre-confirm. Second confirm: the below-floor
    // acknowledgement dialog this fix adds.
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    // 2 initial attempts (both 409) + 2 acknowledged retries = 4 calls total.
    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(4));
    expect(decideApprovalMock.mock.calls[0]).toEqual(["appr-1", "approve"]);
    expect(decideApprovalMock.mock.calls[1]).toEqual(["appr-2", "approve"]);
    expect(decideApprovalMock.mock.calls[2][2]).toEqual({ acknowledgeBelowFloor: true });
    expect(decideApprovalMock.mock.calls[3][2]).toEqual({ acknowledgeBelowFloor: true });

    // The human was shown the real reason from the server, not a raw HTTP
    // envelope, and never a generic "decision failed".
    expect(confirmSpy).toHaveBeenCalledTimes(2);
    const ackDialogText = confirmSpy.mock.calls[1][0] as string;
    expect(ackDialogText).toMatch(/below the quality floor/i);
    expect(ackDialogText).not.toMatch(/POST|\/approvals\/|409/);

    // No "decisions failed" copy anywhere — these were gate-blocked, not failed.
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeNull());
    const alert = screen.getByRole("alert");
    expect(alert.textContent).not.toMatch(/decisions? failed/i);
    expect(alert.textContent).toMatch(/approved with your acknowledgement/i);
  });

  it("declining the acknowledgement dialog leaves the below-floor requests pending with honest copy (no auto-acknowledge)", async () => {
    const targets = [approval({ id: "appr-1" }), approval({ id: "appr-2" })];
    fetchApprovalsMock.mockResolvedValue(targets);
    decideApprovalMock.mockImplementation(async (id: string) => {
      throw belowFloorError(id);
    });
    const confirmSpy = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(true) // bulk pre-confirm
      .mockReturnValueOnce(false); // decline the below-floor acknowledgement

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    // Only the initial (refused) attempts — no acknowledged retry was sent.
    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(2));
    expect(decideApprovalMock).not.toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      { acknowledgeBelowFloor: true },
    );
    expect(confirmSpy).toHaveBeenCalledTimes(2);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toMatch(/decisions? failed/i);
    expect(alert.textContent).toMatch(/left pending/i);
    expect(alert.textContent).toMatch(/approve individually/i);
  });

  it('when every decision is a genuine failure (not below-floor), the summary says "all N ... failed" and never claims "the rest were applied"', async () => {
    const targets = [approval({ id: "appr-1" }), approval({ id: "appr-2" })];
    fetchApprovalsMock.mockResolvedValue(targets);
    decideApprovalMock.mockRejectedValue(new Error("stale request"));
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(2));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/all 2 bulk approve decisions failed/i);
    expect(alert.textContent).not.toMatch(/rest were applied/i);
  });

  it("a genuine partial failure (not below-floor) keeps the existing 'X of N ... — the rest were applied' phrasing", async () => {
    const targets = [approval({ id: "appr-1" }), approval({ id: "appr-2" })];
    fetchApprovalsMock.mockResolvedValue(targets);
    decideApprovalMock.mockImplementation(async (id: string) => {
      if (id === "appr-1") throw new Error("stale request");
      return approval({ id, status: "approved" });
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(2));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/1 of 2 bulk approve decisions failed — the rest were applied/i);
  });

  it("fires sendIfSendable for a below-floor item approved via the acknowledgement retry", async () => {
    const emailItem = approval({ id: "appr-email", type: "email_send" });
    fetchApprovalsMock.mockResolvedValue([emailItem]);
    // A single sendable pending item does not clear the >1 threshold for the
    // bulk toolbar, so pair it with a second, non-sendable target.
    const other = approval({ id: "appr-2", type: "application_submit" });
    fetchApprovalsMock.mockResolvedValue([emailItem, other]);
    decideApprovalMock.mockImplementation(async (id: string, _decision: string, context?: unknown) => {
      if (id === "appr-email") {
        if (context && (context as { acknowledgeBelowFloor?: boolean }).acknowledgeBelowFloor) {
          return approval({ id, status: "approved", type: "email_send" });
        }
        throw belowFloorError(id);
      }
      return approval({ id, status: "approved", type: "application_submit" });
    });
    executeApprovalMock.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledWith("appr-email"));
  });
});
