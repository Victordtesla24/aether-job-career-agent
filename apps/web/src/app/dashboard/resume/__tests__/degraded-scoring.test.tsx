// @vitest-environment jsdom
/**
 * §22 STEP 2 (GOLD-MASTER-V4) — regression-lock coverage for the
 * degraded-scoring UI on Resume Studio (GMV4-ats-001/002).
 *
 * The backend already has 12 python tests for the degraded-scoring
 * behaviour; the frontend had ZERO. This file pins the two places
 * `resume/page.tsx` must tell the user semantic similarity was NOT
 * genuinely measured instead of silently showing a neutral placeholder
 * (e.g. `50.0`) as if it were a real score:
 *
 *   1. the ATS Score grid's "Semantic similarity (40%)" row
 *      (page.tsx ~213-223, ~610-650), and
 *   2. the ATS Conversion Impact panel's before/after/lift
 *      (page.tsx ~373-419).
 *
 * `semanticTrusted`/`conversionDegraded` are WHITELIST-computed off
 * `ats.semantic_path` / `conversion.scoringDegraded` (round-3 fix) —
 * an absent field must read as untrusted (round-2 was a fail-open
 * truthy-read bug: `!ats.semantic_degraded` reads `undefined` as
 * "not degraded"). Test 3 below is that regression guard.
 *
 * These tests PASS against current code (79c4164) — they are
 * regression locks, not fail-first reproductions. Teeth are proven
 * separately (see uat/reports/evidence/models-live/ for the RED-output
 * evidence) by rendering local components that reproduce the OLD
 * (round-1 raw-number, round-2 fail-open) behaviour and showing the
 * same assertions fail against them.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const RESUME = {
  id: "r1",
  userId: "u1",
  version: 2,
  label: "Tailored v2",
  sections: { bullets: [] },
  sourceJobId: "job-1",
  parentId: "r0",
  formatHash: "hash-1",
  approvalStatus: "approved",
  createdAt: "2026-07-15T00:00:00Z",
  updatedAt: "2026-07-15T00:00:00Z",
};

/** Base ATS payload; each test overrides `semantic_path`/omits it. */
function atsFixture(overrides: Record<string, unknown>) {
  return {
    overall: 74,
    keyword_match: 80,
    semantic_similarity: 50,
    experience_gap: 88,
    matched_keywords: ["react"],
    missing_keywords: [],
    requires_review: false,
    job_title: "Delivery Lead",
    company: "Acme Co",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  fetchResumes.mockReset();
  fetchResumeDiff.mockReset();
  runTailorAgent.mockReset();
});

/** Loads the page, opens the single tailored version, returns the ATS panel. */
async function openAtsPanel(atsPayload: Record<string, unknown>) {
  fetchResumes.mockResolvedValue([RESUME]);
  fetchResumeDiff.mockResolvedValue({ resume_id: "r1", parent_id: "r0", changes: [] });
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/jobs") return [JOB];
    if (path === "/resumes/r1/ats") return atsPayload;
    throw new Error(`unexpected apiRequest(${path})`);
  });

  render(<ResumePage />);
  const card = await screen.findByTestId("resume-version-card");
  fireEvent.click(card);
  return screen.findByTestId("ats-score-panel");
}

function semanticValueSpan(panel: HTMLElement) {
  const labelSpan = within(panel).getByText("Semantic similarity (40%)");
  return labelSpan.parentElement!.querySelector(".mono");
}

describe("Resume Studio — ATS grid degraded-scoring UI (GMV4-ats-001/002)", () => {
  it('renders the real semantic score when semantic_path is "local"', async () => {
    const panel = await openAtsPanel(atsFixture({ semantic_path: "local", semantic_similarity: 77 }));

    expect(within(panel).queryByTestId("semantic-not-measured-badge")).toBeNull();
    expect(within(panel).queryByTestId("semantic-degraded-note")).toBeNull();
    expect(semanticValueSpan(panel)?.textContent).toBe("77");
  });

  it('shows "not measured" and an em-dash instead of a number when semantic_path is "degraded"', async () => {
    const panel = await openAtsPanel(atsFixture({ semantic_path: "degraded", semantic_similarity: 50 }));

    expect(within(panel).getByTestId("semantic-not-measured-badge")).toBeTruthy();
    const value = semanticValueSpan(panel);
    expect(value?.textContent).toBe("—");
    expect(value?.textContent).not.toMatch(/50/);
    expect(within(panel).getByTestId("semantic-degraded-note").textContent).toMatch(
      /Semantic similarity could not be measured for this score/,
    );
  });

  it("treats an ABSENT semantic_path as untrusted (fail-open regression guard)", async () => {
    // An older cached `ats` response predating the field — `semantic_path`
    // key is not present at all, not merely `undefined`.
    const ats = atsFixture({ semantic_similarity: 50 });
    delete (ats as Record<string, unknown>).semantic_path;
    expect("semantic_path" in ats).toBe(false);

    const panel = await openAtsPanel(ats);

    expect(within(panel).getByTestId("semantic-not-measured-badge")).toBeTruthy();
    const value = semanticValueSpan(panel);
    expect(value?.textContent).toBe("—");
    expect(within(panel).getByTestId("semantic-degraded-note")).toBeTruthy();
  });
});

describe("Resume Studio — ATS Conversion Impact panel degraded-scoring UI", () => {
  it("badges the conversion panel and withholds the lift when scoringDegraded is true", async () => {
    fetchResumes.mockResolvedValue([]);
    fetchResumeDiff.mockResolvedValue({ resume_id: "r1", parent_id: null, changes: [] });
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/jobs") return [JOB];
      throw new Error(`unexpected apiRequest(${path})`);
    });
    runTailorAgent.mockResolvedValue({
      resume_id: "resume-after-tailor",
      changes: 2,
      rejected: [],
      conversionMetrics: {
        baselineATSScore: 60,
        tailoredATSScore: 88,
        estimatedConversionLift: "+2.0x",
        methodology: "measured",
        confidence: "medium",
        scoringDegraded: true,
      },
      noChangesApplied: false,
    });

    render(<ResumePage />);
    const select = await screen.findByTestId("tailor-job-select");
    fireEvent.change(select, { target: { value: "job-1" } });
    fireEvent.click(screen.getByTestId("run-tailor-btn"));
    await waitFor(() => expect(runTailorAgent).toHaveBeenCalledWith("job-1"));

    const panel = await screen.findByTestId("conversion-metrics");
    expect(within(panel).getByTestId("conversion-not-measured-badge")).toBeTruthy();

    const banner = within(panel).getByTestId("conversion-before-after");
    expect(banner.textContent).not.toMatch(/60/);
    expect(banner.textContent).not.toMatch(/88/);
    expect((banner.textContent?.match(/—/g) ?? []).length).toBe(2);

    const lift = within(panel).getByTestId("conversion-lift");
    expect(lift.textContent).not.toMatch(/2\.0x/);

    expect(within(panel).getByTestId("conversion-degraded-note").textContent).toMatch(
      /Semantic similarity could not be measured for the before\/after re-score/,
    );
  });
});
