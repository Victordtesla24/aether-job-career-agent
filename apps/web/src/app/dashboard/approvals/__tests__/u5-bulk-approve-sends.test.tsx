// @vitest-environment jsdom
/**
 * U5 closing round — re-review MUST-FIX C2 (behavioral, not just copy):
 * `bulkDecide` used to loop `decideApproval` alone, so a bulk-approved
 * `email_send` request was left `approved` with `executedAt` never set and
 * NO send affordance anywhere in the product. That is exactly the "prepared
 * only" violation W-SUB and U5 exist to eliminate. (Round 4 added the one
 * per-card send there is: `Retry send`, rendered ONLY for an approved
 * request whose send provably did not happen — see
 * `u5-email-submission-send-and-retry.test.tsx`. An approve DECISION is
 * still the only way a first send is ever fired.)
 *
 * Fix: bulk-approve fires `sendIfSendable` for every approved
 * `email_send` item, sequentially, with the SAME per-item error handling as
 * a single-card approve — a failed send must never be silently swallowed
 * inside the "N of M decisions failed" count, because the DECISION
 * succeeded; only the SEND failed.
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

function resetHistory() {
  window.history.replaceState(null, "", "/dashboard/approvals");
}

beforeEach(() => {
  resetHistory();
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

describe("bulk-approve executes the send for every approved email_send item (C2)", () => {
  it("fires executeApproval for the email item and NOT for the site item", async () => {
    const emailItem = approval({ id: "appr-email", type: "email_send" });
    const siteItem = approval({ id: "appr-site", type: "application_submit" });
    fetchApprovalsMock.mockResolvedValue([emailItem, siteItem]);
    decideApprovalMock.mockImplementation(async (id: string) =>
      approval({ id, status: "approved", type: id === "appr-email" ? "email_send" : "application_submit" }),
    );
    executeApprovalMock.mockResolvedValue(undefined);

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledWith("appr-email"));
    expect(executeApprovalMock).not.toHaveBeenCalledWith("appr-site");
    expect(executeApprovalMock).toHaveBeenCalledTimes(1);
  });

  it("sends sequentially per item, exactly like sendIfSendable on a single approve", async () => {
    const first = approval({ id: "appr-1", type: "email_send" });
    const second = approval({ id: "appr-2", type: "email_send" });
    fetchApprovalsMock.mockResolvedValue([first, second]);
    decideApprovalMock.mockImplementation(async (id: string) =>
      approval({ id, status: "approved", type: "email_send" }),
    );
    const order: string[] = [];
    executeApprovalMock.mockImplementation(async (id: string) => {
      order.push(id);
    });

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledTimes(2));
    expect(order).toEqual(["appr-1", "appr-2"]);
  });

  it("reports a failed send honestly without hiding it inside the decision-failure count", async () => {
    const emailItem = approval({ id: "appr-email", type: "email_send" });
    const siteItem = approval({ id: "appr-site", type: "application_submit" });
    fetchApprovalsMock.mockResolvedValue([emailItem, siteItem]);
    decideApprovalMock.mockImplementation(async (id: string) =>
      approval({ id, status: "approved", type: id === "appr-email" ? "email_send" : "application_submit" }),
    );
    executeApprovalMock.mockRejectedValue(new Error("No Gmail account connected"));

    render(<ApprovalsPage />);
    const bulkApproveBtn = await screen.findByTestId("bulk-approve-btn");
    fireEvent.click(bulkApproveBtn);

    const alert = await screen.findByRole("alert");
    // Both decisions succeeded (2/2) -- only the SEND failed. A message that
    // says "1 of 2 decisions failed" would be false: the decision succeeded.
    expect(alert.textContent).toMatch(/send/i);
    expect(alert.textContent).not.toMatch(/decisions? failed/i);
  });

  it("does not call execute for a bulk REJECT of an email_send item", async () => {
    const emailItem = approval({ id: "appr-email", type: "email_send" });
    const siteItem = approval({ id: "appr-site", type: "application_submit" });
    fetchApprovalsMock.mockResolvedValue([emailItem, siteItem]);
    decideApprovalMock.mockImplementation(async (id: string) =>
      approval({ id, status: "rejected", type: id === "appr-email" ? "email_send" : "application_submit" }),
    );

    render(<ApprovalsPage />);
    const bulkRejectBtn = await screen.findByTestId("bulk-reject-btn");
    fireEvent.click(bulkRejectBtn);

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalledTimes(2));
    expect(executeApprovalMock).not.toHaveBeenCalled();
  });
});
