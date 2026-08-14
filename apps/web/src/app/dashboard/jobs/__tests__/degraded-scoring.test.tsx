// @vitest-environment jsdom
/**
 * §22 STEP 2 (GOLD-MASTER-V4) — regression-lock coverage for the
 * degraded-scoring UI on Job Discovery (GMV4-ats-001/002).
 *
 * The backend already has 12 python tests for the degraded-scoring
 * behaviour; the frontend had ZERO. This file pins the places
 * `jobs/page.tsx` must tell the user semantic similarity was NOT
 * genuinely measured for a job's insights instead of silently
 * plotting/printing a neutral placeholder as if it were real:
 *
 *   1. the 10-Dimensional Fit Score grid (page.tsx ~1327-1370) — each
 *      `Dimension.degraded` dimension gets `dimension-not-measured-badge`
 *      and an em-dash instead of its (placeholder) `score`.
 *   2. the RadarChart (page.tsx ~213-246) — a degraded dimension's
 *      placeholder `score` must NOT be plotted; it's floored instead.
 *   3. the panel-level honest note (page.tsx ~1372-1379,
 *      `insights-semantic-degraded-note`), whitelist-computed off
 *      `Insights.semanticPath` (same round-3 fail-open fix as Resume
 *      Studio's `semanticTrusted`).
 *
 * These tests PASS against current code (79c4164) — they are
 * regression locks, not fail-first reproductions. Teeth are proven
 * separately (see uat/reports/evidence/models-live/ for the RED-output
 * evidence).
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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

const AU_JOB = {
  id: "job-au",
  title: "AU Product Manager",
  company: "Sydney Co",
  location: "Sydney NSW",
  remote: false,
  description: "",
  source: "seek",
  sourceUrl: "https://seek.com.au/job/1",
  status: "matched",
  fitScore: 82,
  saved: false,
  createdAt: "2026-07-15T00:00:00Z",
};

/** Insights fixture: `degraded=true` mirrors what the backend sends when
 *  semantic similarity was not genuinely measured — the three
 *  semantic-derived dimensions carry a neutral placeholder `score` (50)
 *  and `degraded: true`; one semantic-independent dimension stays a real
 *  measurement throughout, as a same-payload negative control. */
function insightsFixture(degraded: boolean, semanticScoreOverride?: number) {
  const semanticScore = semanticScoreOverride ?? (degraded ? 50 : 78);
  return {
    jobId: AU_JOB.id,
    scored: true,
    overall: 74,
    keywordMatch: 80,
    semantic: semanticScore,
    semanticPath: degraded ? "degraded" : "local",
    semanticDegraded: degraded,
    // R-04 (round 3): `atsMeasured` is now emitted on EVERY insights payload
    // and read fail-closed by the page (absent => not measured), so a fixture
    // must state it — the same discipline `lib/scoring/provenance.ts` already
    // applies to `conversionMetrics`. Both cases here are engine-measured; it
    // is the SEMANTIC half that degrades, which is what this file is about.
    atsMeasured: true,
    experience: 70,
    skillsMatched: 4,
    skillsTotal: 5,
    matchedSkills: ["TypeScript"],
    missingSkills: ["Kubernetes"],
    skillGap: "Kubernetes",
    narrative: "Strong match.",
    dimensions: [
      { label: "Keyword Match", score: 80, degraded: false },
      { label: "Industry Match", score: semanticScore, degraded },
      { label: "Culture Fit", score: semanticScore, degraded },
      { label: "North Star Align", score: semanticScore, degraded },
    ],
    riskSignals: [],
    isAustralia: true,
  };
}

const DEFAULT_AVAILABILITY = [
  { source: "greenhouse", available: true, reason: null },
  { source: "lever", available: true, reason: null },
  { source: "remotive", available: true, reason: null },
  { source: "remoteok", available: true, reason: null },
  { source: "seek", available: false, reason: "compliance-gated" },
  { source: "linkedin", available: false, reason: "fixture-only" },
  { source: "indeed", available: false, reason: "fixture-only" },
];

function installApiRequestMock(insights: ReturnType<typeof insightsFixture>) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith("/jobs?")) return [AU_JOB];
    if (path === `/jobs/${AU_JOB.id}/insights`) return insights;
    if (path === "/agents") return [{ name: "scout", last_run: "2026-07-15T00:00:00Z" }];
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  fetchScoutSources.mockReset();
  fetchSourceAvailability.mockReset();
});

function beforeEachSetup() {
  getToken.mockResolvedValue("test-token");
  apiBaseUrl.mockReturnValue("http://test.local");
  fetchScoutSources.mockResolvedValue([]);
  fetchSourceAvailability.mockResolvedValue(DEFAULT_AVAILABILITY);
}

/** Renders JobsPage and waits for the AU job's fit-score grid to appear. */
async function renderWithInsights(insights: ReturnType<typeof insightsFixture>) {
  beforeEachSetup();
  installApiRequestMock(insights);
  render(<JobsPage />);
  await waitFor(() => expect(screen.getAllByText("AU Product Manager").length).toBeGreaterThan(0));
  await screen.findAllByTestId("fit-dimension");
  return screen.getByTestId("fit-score");
}

describe("Job Discovery — 10-Dimensional Fit Score grid degraded-scoring UI (GMV4-ats-001/002)", () => {
  it("flags each affected dimension when semanticDegraded is true", async () => {
    const fitScore = await renderWithInsights(insightsFixture(true));

    const rows = within(fitScore).getAllByTestId("fit-dimension");
    const byLabel = (label: string) => rows.find((r) => r.textContent?.includes(label))!;

    for (const label of ["Industry Match", "Culture Fit", "North Star Align"]) {
      const row = byLabel(label);
      expect(within(row).getByTestId("dimension-not-measured-badge")).toBeTruthy();
      const valueSpan = row.querySelector(".mono");
      expect(valueSpan?.textContent).toBe("—");
      expect(valueSpan?.textContent).not.toMatch(/50/);
    }

    // Negative control: the semantic-independent dimension in the SAME
    // payload stays a genuine, un-badged number.
    const control = byLabel("Keyword Match");
    expect(within(control).queryByTestId("dimension-not-measured-badge")).toBeNull();
    expect(control.querySelector(".mono")?.textContent).toBe("80");
  });

  it("does not plot the placeholder in the radar chart when a dimension is degraded", async () => {
    const chart1 = await renderWithInsights(insightsFixture(true, 50));
    const svg1 = chart1.querySelector('svg[aria-label="10-dimensional fit radar"]')!;
    const shape1 = svg1.querySelector('polygon[stroke="#FF6B35"]')!.getAttribute("points");
    cleanup();

    // A wildly different placeholder value on the SAME degraded dimensions
    // must plot IDENTICALLY — the number is a meaningless placeholder, so
    // the chart must be invariant to it, not plot it as if real.
    const chart2 = await renderWithInsights(insightsFixture(true, 91));
    const svg2 = chart2.querySelector('svg[aria-label="10-dimensional fit radar"]')!;
    const shape2 = svg2.querySelector('polygon[stroke="#FF6B35"]')!.getAttribute("points");

    expect(shape1).toBe(shape2);

    // Positive control: when NOT degraded, differing real scores DO change
    // the plotted shape — proves the invariance above isn't just a chart
    // that never reacts to `dimensions` at all.
    cleanup();
    const chart3 = await renderWithInsights(insightsFixture(false, 50));
    const svg3 = chart3.querySelector('svg[aria-label="10-dimensional fit radar"]')!;
    const shape3 = svg3.querySelector('polygon[stroke="#FF6B35"]')!.getAttribute("points");
    cleanup();
    const chart4 = await renderWithInsights(insightsFixture(false, 91));
    const svg4 = chart4.querySelector('svg[aria-label="10-dimensional fit radar"]')!;
    const shape4 = svg4.querySelector('polygon[stroke="#FF6B35"]')!.getAttribute("points");
    expect(shape3).not.toBe(shape4);
  });

  it("renders the honest note when insights are degraded, and not when they are trusted", async () => {
    const degradedFitScore = await renderWithInsights(insightsFixture(true));
    expect(within(degradedFitScore).getByTestId("insights-semantic-degraded-note").textContent).toMatch(
      /Semantic similarity could not be measured for this analysis/,
    );
    cleanup();

    const trustedFitScore = await renderWithInsights(insightsFixture(false));
    expect(within(trustedFitScore).queryByTestId("insights-semantic-degraded-note")).toBeNull();
  });
});
