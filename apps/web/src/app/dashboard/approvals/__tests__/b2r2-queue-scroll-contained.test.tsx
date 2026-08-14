// @vitest-environment jsdom
/**
 * S-UI B2 ROUND 2, judge item 2 (closes OBS-B2-01) — the Approvals queue is
 * scroll-contained, so the page ends (D-ε) no matter how deep the backlog is.
 *
 * B2 gave Jobs a scrolling list pane and Applications scrolling kanban columns,
 * but left Approvals growing with its queue: 2,652px at 1600 and 3,804px at 390
 * with 11 pending, ≈220px per card, against a doctrine that says a page ends by
 * ~2,500px and everything else scrolls in a container. Three sibling pages in
 * one batch spoke two layout languages, and the call was deferred rather than
 * made. This is the decision, pinned:
 *
 *   1. the queue lives in ONE scroll container with a bounded, viewport-derived
 *      max-height — so the document stops growing at ~one viewport;
 *   2. it is `max-height`, not `height` — a two-item queue must not render as
 *      two items floating in an empty well;
 *   3. every request still renders inside it (containment must never be
 *      achieved by dropping rows);
 *   4. the container is a keyboard-operable labelled region, because a
 *      scrollable region that only a mouse can scroll is a trap.
 *
 * jsdom has no layout engine, so the pixel proof is the measured page height in
 * the B2 round-2 evidence; what is asserted here is the structure that produces
 * it, which is the thing a later refactor can silently undo.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../../lib/api/approvals";

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../lib/api/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/approvals")>();
  return { ...actual, fetchApprovals: (...args: unknown[]) => fetchApprovalsMock(...args) };
});

// eslint-disable-next-line import/first
import ApprovalsPage from "../page";

function approval(i: number): Approval {
  return {
    id: `appr-${i}`,
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: { job_title: `Senior ML Engineer ${i}`, company: `Canva ${i}` },
    // Relative to the real clock so the fixture never ages past the 48h
    // isExpired() window (see page.test.tsx for why that matters).
    createdAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    resolvedAt: null,
  };
}

/** The exact backlog depth the judge measured the unbounded page at. */
const ELEVEN_PENDING = Array.from({ length: 11 }, (_, i) => approval(i));

beforeEach(() => {
  window.history.replaceState(null, "", "/dashboard/approvals");
  fetchApprovalsMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  fetchApprovalsMock.mockReset();
  window.history.replaceState(null, "", "/dashboard/approvals");
});

describe("Approvals queue is scroll-contained (D-ε)", () => {
  it("puts an 11-deep backlog in one bounded scroll container, with every card still in it", async () => {
    fetchApprovalsMock.mockResolvedValue(ELEVEN_PENDING);
    render(<ApprovalsPage />);

    const queue = await waitFor(() => screen.getByTestId("approvals-queue"));

    // Containment, not truncation: all 11 requests are inside the container.
    expect(within(queue).getAllByTestId("approval-card").length).toBe(11);

    // A real scroll container, and one whose scroll cannot chain into the page.
    expect(queue.className).toMatch(/\boverflow-y-auto\b/);
    expect(queue.className).toMatch(/\boverscroll-contain\b/);
    // `min-h-0` is load-bearing: without it a flex/grid child refuses to shrink
    // below its content and the inner overflow never engages.
    expect(queue.className).toMatch(/\bmin-h-0\b/);

    // Bounded by the viewport, capped, and expressed as a MAX so a short queue
    // does not become an empty well.
    expect(queue.style.maxHeight).toContain("dvh");
    expect(queue.style.maxHeight).toMatch(/min\(/);
    expect(queue.style.height).toBe("");
  });

  it("keeps the container keyboard-operable and honestly labelled", async () => {
    fetchApprovalsMock.mockResolvedValue(ELEVEN_PENDING);
    render(<ApprovalsPage />);

    const queue = await waitFor(() => screen.getByTestId("approvals-queue"));
    expect(queue.getAttribute("role")).toBe("region");
    expect(queue.getAttribute("tabindex")).toBe("0");
    // The name states what this filter is actually showing — not a total it
    // cannot see.
    expect(queue.getAttribute("aria-label")).toBe("Approval requests, 11 shown");
  });

  it("does not wrap the empty state in a scroll well", async () => {
    fetchApprovalsMock.mockResolvedValue([]);
    render(<ApprovalsPage />);

    await waitFor(() => screen.getByTestId("approvals-empty-state"));
    expect(screen.queryByTestId("approvals-queue")).toBeNull();
  });
});
