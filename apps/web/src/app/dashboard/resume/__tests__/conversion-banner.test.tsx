// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §12 / W-J item 7 — before/after ATS banner characterization
 * (Resume Studio).
 *
 * §12 asks for a before/after ATS score banner alongside tailoring. It
 * ALREADY EXISTS and works: `resume/page.tsx` renders
 * `data-testid="conversion-before-after"` — "Before: {baselineATSScore}% →
 * After: {tailoredATSScore}%" — driven by the real `conversionMetrics` a
 * completed tailor run returns (`lib/api/resumes.ts` `TailorRunResult`).
 *
 * This is a CHARACTERIZATION test — it pins existing, correct behaviour and
 * is expected to PASS BY DESIGN, not reproduce a defect. The prior
 * test-author run explicitly skipped writing this test, citing a stay-out
 * boundary on `apps/web/src/app/dashboard/resume/**` that applied to ITS
 * brief only; that path is not in this fixer run's stay-out list (only
 * `dashboard/jobs/page.tsx` + Jobs card/apply components, `apps/api/**`,
 * `app/login/**`, `components/topbar.tsx` are), so it is written here per
 * the W-J item 7 instruction to pin it.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
}));

const fetchResumes = vi.fn();
const runTailorAgent = vi.fn();
const fetchResumeDiff = vi.fn();
const downloadResume = vi.fn();
vi.mock("../../../../lib/api/resumes", () => ({
  fetchResumes: (...args: unknown[]) => fetchResumes(...args),
  runTailorAgent: (...args: unknown[]) => runTailorAgent(...args),
  fetchResumeDiff: (...args: unknown[]) => fetchResumeDiff(...args),
  downloadResume: (...args: unknown[]) => downloadResume(...args),
}));

// eslint-disable-next-line import/first
import ResumePage from "../page";

const JOB = { id: "job-1", title: "Delivery Lead", company: "Acme Co" };

apiRequest.mockImplementation(async (path: string) => {
  if (path === "/jobs") return [JOB];
  throw new Error(`unexpected apiRequest(${path})`);
});
fetchResumes.mockResolvedValue([]);
fetchResumeDiff.mockResolvedValue({ resume_id: "r1", parent_id: null, changes: [] });

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
  fetchResumes.mockClear();
  runTailorAgent.mockClear();
});

describe("W-J item 7 — before/after ATS banner (Resume Studio, characterization)", () => {
  it("renders the real baseline -> tailored ATS scores once a tailor run completes (passes by design)", async () => {
    runTailorAgent.mockResolvedValue({
      resume_id: "resume-after-tailor",
      changes: 3,
      rejected: [],
      conversionMetrics: {
        baselineATSScore: 55,
        tailoredATSScore: 91,
        estimatedConversionLift: "+3.2x",
        methodology: "measured",
        confidence: "high",
        // ADR-GMV4-004(2): declare provenance explicitly rather than relying
        // on absence to mean "trusted" — this fixture asserts the trusted
        // (measured) path, so it must say so.
        baselineDegraded: false,
        tailoredDegraded: false,
        scoringDegraded: false,
      },
      noChangesApplied: false,
    });

    render(<ResumePage />);

    // No banner before any tailor run has completed.
    expect(screen.queryByTestId("conversion-before-after")).toBeNull();

    const select = await screen.findByTestId("tailor-job-select");
    fireEvent.change(select, { target: { value: "job-1" } });

    const btn = screen.getByTestId("run-tailor-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);

    await waitFor(() => expect(runTailorAgent).toHaveBeenCalledWith("job-1"));

    const banner = await screen.findByTestId("conversion-before-after");
    expect(banner.textContent).toMatch(/55/);
    expect(banner.textContent).toMatch(/91/);
  });
});
