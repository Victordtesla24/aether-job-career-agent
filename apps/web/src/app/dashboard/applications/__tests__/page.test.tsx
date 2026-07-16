// @vitest-environment jsdom
/**
 * GAP-P6-WIRE-001 regression guard (Cluster B, /dashboard/applications).
 *
 * probe-06-interactions.json flagged "Board View", "Sankey Flow" and
 * "Timeline" as RENDERED-BUT-NO-EFFECT: clicking them produced no network
 * call and no observable state change. This test renders the real
 * ApplicationsPage, drives each of the three view-toggle tabs, and asserts
 * the visible view actually swaps (kanban board -> sankey chart -> timeline
 * list) so a regression that silently disconnects a tab's onClick handler
 * from the rendered view is caught here, not just in a prop-level test.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import ApplicationsPage from "../page";

const APP_FIXTURE = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "submitted",
  coverLetter: null,
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: "https://boards.example.com/acme/1",
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
  answers: {},
  fitScore: 88,
};

const SANKEY_FIXTURE = {
  stages: [
    { key: "discovered", label: "Discovered", value: 847, color: "#4F46E5" },
    { key: "applied", label: "Applied", value: 412, color: "#818CF8" },
  ],
  dropoffs: [{ after: "discovered", count: 435, reason: "not pursued" }],
  insight: "Most drop-off happens before application.",
};

apiRequest.mockImplementation(async (path: string) => {
  if (path === "/applications") return [APP_FIXTURE];
  if (path === "/jobs") return [];
  if (path.startsWith("/approvals")) return [];
  if (path === "/workspaces/settings") {
    return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
  }
  if (path === "/applications/funnel/sankey") return SANKEY_FIXTURE;
  throw new Error(`unexpected apiRequest(${path})`);
});

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("Application Tracker view toggles (GAP-P6-WIRE-001)", () => {
  it("Board View / Sankey Flow / Timeline each render a distinct, non-dead view", async () => {
    render(<ApplicationsPage />);

    // Default view: Board — the kanban columns render, seeded from the fixture.
    await screen.findByTestId("applications-kanban");
    expect(screen.getByTestId("view-board").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Senior Product Owner")).not.toBeNull();

    // Sankey Flow: clicking swaps the DOM to the sankey chart and fetches
    // the canonical funnel data — a real network call + real state change.
    fireEvent.click(screen.getByTestId("view-sankey"));
    expect(screen.getByTestId("view-sankey").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByTestId("applications-kanban")).toBeNull();
    await screen.findByTestId("sankey-svg");
    expect(apiRequest).toHaveBeenCalledWith(
      "/applications/funnel/sankey",
      expect.anything(),
    );

    // Timeline: swaps again to a chronological list of the same applications.
    fireEvent.click(screen.getByTestId("view-timeline"));
    expect(screen.getByTestId("view-timeline").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByTestId("sankey-svg")).toBeNull();
    const timeline = await screen.findByTestId("timeline-view");
    expect(timeline.textContent).toContain("Senior Product Owner");

    // Back to Board — the toggle round-trips cleanly.
    fireEvent.click(screen.getByTestId("view-board"));
    await screen.findByTestId("applications-kanban");
    expect(screen.queryByTestId("timeline-view")).toBeNull();
  });
});
