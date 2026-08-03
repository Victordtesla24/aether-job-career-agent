// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §12.3 / W-J item 6 — re-fetch after tailoring.
 *
 * `startTailoring()` (page.tsx ~509-536) POSTs `/agents/tailor/run` and
 * receives a `TailorRunResult` whose `conversionMetrics` (when present)
 * carries a fresh `tailoredATSScore` (`apps/web/src/lib/api/resumes.ts:52`).
 * But `conversionMetrics` is never read anywhere in `jobs/page.tsx` (grep
 * confirms zero references), and `startTailoring` never re-fetches the job
 * list or patches `jobs` state with a new score — only `tailorResults` (the
 * changes/rejected counters) and `applyStep` (the 2-step UI state) are
 * updated. The match-score ring (`MatchRing value={selected.fitScore}` /
 * `value={job.fitScore}`) is driven purely off the `jobs` array loaded once
 * at mount, so it keeps showing the PRE-tailor score after a successful
 * tailor run, with no manual reload available to fix it short of a full
 * page refresh.
 *
 * §12.3 requires the displayed score to update after a tailor action
 * completes, without a manual reload.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const fetchScoutSources = vi.fn();
const fetchSourceAvailability = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
  fetchSourceAvailability: (...args: unknown[]) => fetchSourceAvailability(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

const JOB = {
  id: "job-tailor-1",
  title: "Delivery Lead",
  company: "Acme Co",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "greenhouse",
  sourceUrl: "https://greenhouse.io/job/tailor-1",
  status: "matched",
  fitScore: 55,
  saved: false,
  createdAt: "2026-07-15T00:00:00Z",
};

function insightsFor(jobId: string) {
  return {
    jobId,
    scored: true,
    overall: 55,
    keywordMatch: 55,
    semantic: 55,
    experience: 55,
    skillsMatched: 2,
    skillsTotal: 5,
    matchedSkills: [],
    missingSkills: [],
    skillGap: "",
    narrative: "",
    dimensions: [],
    riskSignals: [],
    isAustralia: true,
  };
}

apiRequest.mockImplementation(
  async (path: string, options?: { method?: string; body?: unknown }) => {
    if (path.startsWith("/jobs?")) return [JOB];
    const insightsMatch = /^\/jobs\/([^/]+)\/insights$/.exec(path);
    if (insightsMatch) return insightsFor(insightsMatch[1]);
    if (path === "/agents") return [];
    if (path === "/agents/tailor/run" && options?.method === "POST") {
      // Legacy synchronous shape (status !== "enqueued") so `resolveRun`
      // passes it straight through without any extra polling mock needed.
      return {
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
      };
    }
    throw new Error(`unexpected apiRequest(${path})`);
  },
);
getToken.mockResolvedValue("test-token");
apiBaseUrl.mockReturnValue("http://test.local");
fetchScoutSources.mockResolvedValue([]);
fetchSourceAvailability.mockResolvedValue([]);

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

describe("W-J item 6 — displayed match score after a tailor run (§12.3)", () => {
  it("updates the displayed score to the fresh tailoredATSScore once tailoring completes, without a manual reload", async () => {
    render(<JobsPage />);

    const card = await screen.findByTestId("job-card");
    await waitFor(() => expect(within(card).getByText("55")).toBeTruthy());

    const tailorBtn = await screen.findByTestId("tailor-resume");
    fireEvent.click(tailorBtn);

    // Wait for the tailor run to resolve — the 2-step "tailored" panel
    // appears once `startTailoring` finishes.
    await screen.findByTestId("apply-step2");

    // §12.3: the fresh tailoredATSScore (91) from the just-completed run
    // must now be reflected somewhere on the card — it isn't. `jobs` state
    // (and therefore `job.fitScore` / `selected.fitScore`, which drive the
    // MatchRing) is never patched or re-fetched by `startTailoring`, and
    // `conversionMetrics` is never read at all in jobs/page.tsx.
    expect(within(card).queryByText("91")).toBeTruthy();
  });
});
