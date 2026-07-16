// @vitest-environment jsdom
/**
 * GAP-P6-CONV-001 / GATE-10 regression guard.
 *
 * Live QA (uat/reports/evidence/phase6/qa-E-verification.json item 4,
 * screenshot live-resume-conversion-section.png) found the conversion-estimate
 * section on /dashboard/resume rendered the "Estimated interview conversion
 * improvement" figure and the API's `methodology` string as plain <p> text --
 * no MetricTooltip, no info-icon, no aria-describedby popover -- even though
 * MetricTooltip is already wired onto equivalent estimate metrics elsewhere
 * (analytics, jobs, MarketPulse, DashboardStats). GATE-10 requires the
 * conversion estimate to disclose its formula/assumptions via a MetricTooltip
 * and remain labeled an ESTIMATE.
 *
 * This test drives an actual tailor run through the real ResumePage
 * component (network calls mocked) and asserts the conversion-metrics
 * section contains a MetricTooltip trigger whose popover surfaces the API's
 * methodology text, with the "Estimated" label still visible.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../../lib/api/jobs";

// vi.mock factories are hoisted above all other module-level code, so the
// fixtures they close over must be created via vi.hoisted rather than plain
// top-level consts (which would still be in their temporal dead zone).
const { METHODOLOGY, CONVERSION_METRICS, JOB } = vi.hoisted(() => {
  const methodology =
    "Like-for-like ATS delta (shared context) x population baseline (2.5%)";
  return {
    METHODOLOGY: methodology,
    CONVERSION_METRICS: {
      baselineATSScore: 61,
      tailoredATSScore: 78,
      estimatedConversionLift: "+4.2%",
      methodology,
      confidence: "model-estimated",
    },
    JOB: {
      id: "job-1",
      title: "Senior Program Manager",
      company: "Acme Corp",
      location: "Melbourne, AU",
      remote: false,
      description: "Own delivery across a portfolio of platform initiatives.",
      requirements: [],
      source: "manual",
      sourceUrl: null,
      status: "matched",
      fitScore: 82,
      atsScore: 74,
      saved: false,
      postedAt: null,
    } satisfies Job,
  };
});

vi.mock("../../lib/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => (path === "/jobs" ? [JOB] : [])),
}));

vi.mock("../../lib/api/resumes", () => ({
  fetchResumes: vi.fn().mockResolvedValue([]),
  fetchResumeDiff: vi.fn().mockResolvedValue({ resume_id: "r1", parent_id: null, changes: [] }),
  downloadResume: vi.fn().mockResolvedValue(undefined),
  runTailorAgent: vi.fn().mockResolvedValue({
    resume_id: "r1",
    changes: 3,
    rejected: [],
    conversionMetrics: CONVERSION_METRICS,
  }),
}));

import ResumePage from "../../app/dashboard/resume/page";
import { fetchResumes } from "../../lib/api/resumes";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Resume conversion-estimate MetricTooltip (GAP-P6-CONV-001)", () => {
  it("wires a MetricTooltip disclosing the API methodology onto the conversion-estimate section", async () => {
    render(<ResumePage />);

    await waitFor(() => expect(fetchResumes).toHaveBeenCalled());

    const select = (await screen.findByLabelText(
      "Select a job to tailor for",
    )) as HTMLSelectElement;
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /Senior Program Manager/i })).not.toBeNull(),
    );
    fireEvent.change(select, { target: { value: JOB.id } });

    fireEvent.click(screen.getByTestId("run-tailor-btn"));

    const section = await screen.findByTestId("conversion-metrics", {}, { timeout: 2000 });

    // "Estimated" labeling must remain visible in the section.
    expect(section.textContent).toMatch(/estimated/i);

    const trigger = await within(section).findByTestId(
      "metric-tooltip-trigger",
      {},
      { timeout: 500 },
    );
    expect(trigger).not.toBeNull();

    const describedBy = trigger.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const popover = document.getElementById(describedBy as string);
    expect(popover).not.toBeNull();
    expect(popover?.getAttribute("role")).toBe("tooltip");

    // The tooltip must surface the API's methodology string, not a
    // hardcoded/placeholder explanation.
    expect(popover?.textContent).toContain(METHODOLOGY);
  });
});
