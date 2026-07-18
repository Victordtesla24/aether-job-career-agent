// @vitest-environment jsdom
/**
 * /dashboard/approvals page — Cluster J (MV-approval-modal-003/005/006/008,
 * MV-mobile-approval-002).
 *
 * - MV-approval-modal-003: a long/unbroken job_title must never blow out the
 *   card layout (page-wide horizontal overflow).
 * - MV-approval-modal-005: browser Back while the review modal is open must
 *   close the modal, not exit the whole Approvals screen.
 * - MV-approval-modal-006 / MV-mobile-approval-002: an invalid ?review=<id>
 *   deep link must show a persistent, honest error that the concurrent
 *   pending-list load can never clobber.
 * - MV-approval-modal-008: POST /approvals/{id}/execute is the only call
 *   that actually sends an email_send approval's message — approving one
 *   must fire it.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../../lib/api/approvals";

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../lib/api/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/approvals")>();
  return { ...actual, fetchApprovals: (...args: unknown[]) => fetchApprovalsMock(...args) };
});

const fetchApprovalMock = vi.hoisted(() => vi.fn());
const decideApprovalMock = vi.hoisted(() => vi.fn());
const executeApprovalMock = vi.hoisted(() => vi.fn());
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

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: { job_title: "Senior ML Engineer", company: "Canva" },
    createdAt: "2026-07-17T09:00:00Z",
    resolvedAt: null,
    ...overrides,
  };
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
});

afterEach(() => {
  cleanup();
  fetchApprovalsMock.mockReset();
  resetHistory();
});

describe("long/unbroken job_title containment (MV-approval-modal-003)", () => {
  it("wraps a long unbroken job_title with break-words on a min-w-0 flex item, not truncate/nowrap", async () => {
    const longTitle = "A".repeat(300);
    fetchApprovalsMock.mockResolvedValue([
      approval({ payload: { job_title: longTitle, company: "Acme" } }),
    ]);

    render(<ApprovalsPage />);

    const card = await screen.findByTestId("approval-card");
    const titleEl = card.querySelector("h2");
    expect(titleEl).toBeTruthy();
    expect(titleEl!.textContent).toContain(longTitle);
    // Wrap-safe CSS on the title element itself...
    expect(titleEl!.className).toMatch(/break-words|break-all/);
    expect(titleEl!.className).not.toMatch(/\btruncate\b/);
    // ...and min-w-0 so the flex item can actually shrink instead of forcing
    // the whole row (and therefore the page) to its content width.
    expect(titleEl!.className).toMatch(/\bmin-w-0\b/);
  });
});

describe("browser Back closes the review modal (MV-approval-modal-005)", () => {
  it("closes the modal on Back instead of leaving /dashboard/approvals", async () => {
    fetchApprovalsMock.mockResolvedValue([approval()]);
    render(<ApprovalsPage />);

    const reviewBtn = await screen.findByTestId("review-btn");
    fireEvent.click(reviewBtn);

    expect(await screen.findByTestId("approval-modal")).toBeTruthy();
    expect(window.location.search).toMatch(/review=/);

    window.history.back();

    await waitFor(() => expect(screen.queryByTestId("approval-modal")).toBeNull());
    // Still on the Approvals screen — Back did not navigate away.
    expect(screen.getByTestId("pending-count")).toBeTruthy();
  });

  it("splices a bare history entry under a deep-linked review so Back closes it too", async () => {
    window.history.replaceState(null, "", "/dashboard/approvals?review=appr-1");
    fetchApprovalsMock.mockResolvedValue([approval()]);
    fetchApprovalMock.mockResolvedValue(approval());

    render(<ApprovalsPage />);

    expect(await screen.findByTestId("approval-modal")).toBeTruthy();

    window.history.back();

    await waitFor(() => expect(screen.queryByTestId("approval-modal")).toBeNull());
    expect(window.location.pathname).toBe("/dashboard/approvals");
  });
});

describe("invalid deep-link error is never clobbered by the list load (MV-approval-modal-006 / MV-mobile-approval-002)", () => {
  it("keeps the honest 'not found' error visible even when the pending-list load resolves afterwards", async () => {
    window.history.replaceState(null, "", "/dashboard/approvals?review=bad-id");
    fetchApprovalMock.mockRejectedValue(new Error("404"));
    let resolveList: (rows: Approval[]) => void = () => {};
    fetchApprovalsMock.mockReturnValue(
      new Promise<Approval[]>((resolve) => {
        resolveList = resolve;
      }),
    );

    render(<ApprovalsPage />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/could not be found/i);

    // Now let the concurrent list load win the race by resolving AFTER the
    // deep-link error was already set — this is the exact clobbering race.
    resolveList([]);
    await waitFor(() => expect(screen.getByTestId("approvals-empty-state")).toBeTruthy());

    expect(screen.getByRole("alert").textContent).toMatch(/could not be found/i);
  });
});

describe("execute wiring for email_send approvals (MV-approval-modal-008)", () => {
  it("fires POST /approvals/{id}/execute right after approving an email_send request", async () => {
    fetchApprovalsMock.mockResolvedValue([approval({ type: "email_send" })]);
    decideApprovalMock.mockResolvedValue(approval({ type: "email_send", status: "approved" }));
    executeApprovalMock.mockResolvedValue(undefined);

    render(<ApprovalsPage />);
    const approveBtn = await screen.findByTestId("approve-btn");
    fireEvent.click(approveBtn);

    await waitFor(() => expect(executeApprovalMock).toHaveBeenCalledWith("appr-1"));
  });

  it("does not call execute for a non-email_send approval type", async () => {
    fetchApprovalsMock.mockResolvedValue([approval({ type: "application_submit" })]);
    decideApprovalMock.mockResolvedValue(
      approval({ type: "application_submit", status: "approved" }),
    );

    render(<ApprovalsPage />);
    const approveBtn = await screen.findByTestId("approve-btn");
    fireEvent.click(approveBtn);

    await waitFor(() => expect(decideApprovalMock).toHaveBeenCalled());
    expect(executeApprovalMock).not.toHaveBeenCalled();
  });

  it("surfaces an honest error when the approval succeeds but the email send (execute) fails", async () => {
    fetchApprovalsMock.mockResolvedValue([approval({ type: "email_send" })]);
    decideApprovalMock.mockResolvedValue(approval({ type: "email_send", status: "approved" }));
    executeApprovalMock.mockRejectedValue(new Error("No Gmail account connected"));

    render(<ApprovalsPage />);
    const approveBtn = await screen.findByTestId("approve-btn");
    fireEvent.click(approveBtn);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/approved/i);
    expect(alert.textContent).toMatch(/gmail/i);
  });
});
