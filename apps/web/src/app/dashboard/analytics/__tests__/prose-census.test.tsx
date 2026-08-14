// @vitest-environment jsdom
/**
 * THE PROSE CENSUS — ANALYTICS-VIZ's pinned regression.
 *
 * User mandate (2026-08-14): "analytics UI page must ONLY contain
 * visualisations, graphs, diagrams, interactive visuals, animations and
 * pictures — remove everything else." The orchestrator's binding reading: ZERO
 * standalone prose blocks anywhere on the page; honesty qualifiers are
 * PRESERVED but demoted to ≤1-line captions/legends attached to the visual
 * they qualify, and a qualifier of a visible number may never be hover-only.
 *
 * A mandate that lives only in a review comment is a mandate that comes back.
 * This file walks the REAL rendered page — all three tab panels at once, since
 * every panel stays mounted (`hidden`), which is what makes a single render a
 * complete census — and enforces four rules mechanically.
 *
 *   RULE 1  Every prose block carries an ALLOWED ROLE.
 *           "Prose" is any `<p>` whose trimmed text reaches PROSE_MIN_CHARS.
 *           Below that a `<p>` is a label ("Offers", "Jobs by source"), not a
 *           paragraph, and the mandate is about paragraphs. The threshold is
 *           the test's one judgement call and it is deliberately generous:
 *           60 characters is already past any label this product ships.
 *
 *   RULE 2  A caption is ONE LINE. Code-authored captions may not exceed
 *           CAPTION_MAX_CHARS. Strings the SERVER wrote are exempt via
 *           `data-prose-source="server"` — the kit's standing rule is that a
 *           caller's honesty string is rendered verbatim and never rewritten,
 *           so the only alternative to exempting them would be to paraphrase
 *           the server, which is worse than a two-line caption.
 *
 *   RULE 3  A caption is ATTACHED. Every `data-prose="caption"` must sit
 *           inside a container that also holds a VISUAL. A qualifier floating
 *           in a section with nothing to qualify is a paragraph wearing a
 *           caption's clothes.
 *
 *   RULE 4  No bulleted paragraphs. A list item may be a chip, a legend entry
 *           or a row of data; it may not be a sentence, which is how the old
 *           policy panel's "why this tier" block was written.
 *
 * THE ALLOWED ROLES, and why each is not "prose beside a visual":
 *   caption  a ≤1-line qualifier attached to the visual it qualifies
 *   legend   what a mark, tone or dash MEANS (C-5's word half)
 *   insight  the executive band's one deterministic measured line per tile
 *   tooltip  copy inside a hover/focus popover (extra, never the only home of
 *            a qualifier — see the U-AX law above)
 *   empty    the DESIGNED absent state (D-θ): it exists only where a mark has
 *            nothing to draw, and is the visual's substitute, not its neighbour
 *   status   a load/error state: transient, replaced by the visual the moment
 *            data arrives
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import AnalyticsPage from "../page";

/** Past this many characters a `<p>` has stopped being a label. */
const PROSE_MIN_CHARS = 60;
/** A caption is one line. Server-authored strings are exempt (RULE 2). */
const CAPTION_MAX_CHARS = 200;

const ALLOWED_ROLES = ["caption", "legend", "insight", "tooltip", "empty", "status"] as const;

/** Anything that draws. A caption must live beside one of these (RULE 3). */
const VISUAL_SELECTOR = [
  "svg",
  "canvas",
  "[data-chart-frame]",
  "[data-chart]",
  '[data-testid="spark"]',
  '[data-testid="chart-plot"]',
  '[data-testid="chart-svg"]',
  '[role="img"]',
  "[data-mark]",
].join(",");

const FUNNEL_FIXTURE = {
  period: "all",
  jobs_found: 8358,
  applied: 287,
  screened: 12,
  interviewed: 2,
  offers: 0,
};

const CONVERSION_FIXTURE = {
  period: "all",
  found_to_applied: 3.4,
  applied_to_screened: 4.2,
  screened_to_interview: 16.7,
  interview_to_offer: 0,
  interview_conversion_rate: 0.7,
  interview_conversion_healthy: false,
};

const ATS_FIXTURE = {
  buckets: [
    { range: "0-9", count: 0 },
    { range: "60-69", count: 4 },
    { range: "70-79", count: 9 },
    { range: "80-89", count: 6 },
  ],
  total: 19,
};

const ROI_FIXTURE = { total_cost_usd: 8.16, total_runs: 8781, avg_duration_ms: 166000 };

const DASHBOARD_FIXTURE = {
  totalApplications: 460,
  interviews: 2,
  offers: 0,
  jobsFound: 8358,
  avgFitScore: 61,
  agentRuns: 8781,
  agentCostUsd: 8.16,
};

const POLICY_FIXTURE = {
  tier: "heightened",
  triggers: ["conversion_below_20pct_target", "dimension_below_80pct_floor:cultureFit"],
  behaviour:
    "Heightened rigor: résumé tailoring runs up to 7 scoring iterations (instead of 5) targeting an ATS score of 88 (instead of 85), and the cover-letter agent takes up to 3 retries before it gives up.",
  knobs: { maxIterations: 7, targetScore: 88, coverLetterRetries: 3 },
  thresholds: { interviewConversionTarget: 0.2, dimensionFloor: 80, minSampleSize: 5 },
  metricSnapshot: {
    sampleSize: 287,
    conversionRate: 0.7,
    interviewCount: 2,
    dimensionScores: { cultureFit: 72.5, roleAlignment: 84 },
    dimensionSampleSize: 42,
    dimensionsEvaluated: 2,
    available: true,
    unavailableReason: null,
  },
  perAgent: [],
};

const HISTORY_FIXTURE = {
  available: true,
  reason: null,
  runsWithoutPolicy: 8781,
  thresholds: { interviewConversionTarget: 20, dimensionFloor: 80, minSampleSize: 5 },
  points: [
    {
      at: "2026-08-01T00:00:00Z",
      tier: "standard",
      runs: 2,
      conversionRate: 0,
      sampleSize: 2,
      interviewCount: 0,
      dimensionsBelowFloor: [],
      dimensionsEvaluated: 0,
      triggers: [],
    },
    {
      at: "2026-08-10T00:00:00Z",
      tier: "heightened",
      runs: 18,
      conversionRate: 0.7,
      sampleSize: 287,
      interviewCount: 2,
      dimensionsBelowFloor: ["cultureFit"],
      dimensionsEvaluated: 2,
      triggers: ["conversion_below_20pct_target"],
    },
  ],
};

const COHORTS_FIXTURE = {
  target: 20,
  minSampleSize: 5,
  cohorts: [
    {
      tier: "standard",
      label: "Standard rigor",
      submitted: 24,
      interviewed: 2,
      conversionRate: 8.33,
      sufficientSample: true,
      meetsTarget: false,
      gapPoints: 11.67,
    },
    {
      tier: "heightened",
      label: "Heightened rigor",
      submitted: 3,
      interviewed: 0,
      conversionRate: null,
      sufficientSample: false,
      meetsTarget: null,
      gapPoints: null,
    },
  ],
  untagged: {
    submitted: 290,
    interviewed: 0,
    reason: "submitted before the rigor policy was instrumented",
  },
};

/** A RESOLVED market pulse — the Market tab's prose only exists once this
 *  payload lands, so a fixture that leaves it loading would census a skeleton
 *  and pass by accident. */
const MARKET_PULSE_FIXTURE = {
  sources: [
    { label: "Adzuna", value: 60, color: "#FF6B35" },
    { label: "Seek", value: 40, color: "#818CF8" },
  ],
  sourcesTotal: 8358,
  sourcesLabel: "jobs sourced",
  topSkills: [],
  timezone: "Australia/Melbourne",
  activityHeatmap: [[0, 1, 2, 3, 4, 0, 0]],
  probability: {
    score: 42,
    measured: true,
    label: "Job Search Progress",
    note: "Derived from your own recorded activity across discovery, tailoring and submission.",
    methodology: "Weighted index over four recorded signals.",
    unmeasuredReason: "Not measured — no signal has data yet.",
    marketDataConnected: false,
    factors: [
      { label: "Discovery", value: 80 },
      { label: "Tailoring", value: null },
    ],
  },
  employerActivity: [{ company: "Acme", event: "posted 3 roles", when: "2d ago", signal: "hot" }],
  recruiterTrends: { series: [3, 5, 4, 6], rows: [] },
  marketVsYou: {
    comparisons: [
      {
        label: "Applications per month",
        market: 24,
        you: 31,
        unit: "",
        connected: true,
        dataAsOf: "2026-08-13T00:00:00Z",
        marketNote: "Adzuna Australia, last 30 days.",
        footnote: "Your figure counts every application record.",
      },
      {
        label: "Interview rate",
        market: null,
        you: 0.7,
        unit: "%",
        connected: false,
        dataAsOf: null,
        marketNote: null,
        footnote: null,
      },
      // A genuinely MEASURED zero on both sides — the case a `width: 0%` bar
      // renders identically to "never measured" (law C-1).
      {
        label: "Advertised salary (mean)",
        market: 0,
        you: 0,
        unit: "A$",
        connected: true,
        dataAsOf: "2026-08-13T00:00:00Z",
        marketNote: "Market = the mean advertised salary Adzuna Australia reports (AUD).",
        footnote: null,
      },
    ],
    summary:
      "Market data: Adzuna Australia — 1,204 live postings (last 30 days) for your target role in Melbourne. Adzuna reports a mean advertised salary of A$147,925 for that same search.",
  },
  trendIndicators: [
    { label: "Roles posted", value: "1,204", delta: 4, deltaKind: "percent", direction: "up", series: [3, 5, 4, 6] },
  ],
};

apiRequest.mockImplementation(async (path: string) => {
  if (path.startsWith("/analytics/funnel")) return FUNNEL_FIXTURE;
  if (path === "/analytics/ats-distribution") return ATS_FIXTURE;
  if (path === "/analytics/agent-roi") return ROI_FIXTURE;
  if (path.startsWith("/analytics/conversion")) return CONVERSION_FIXTURE;
  if (path.startsWith("/analytics/dashboard")) return DASHBOARD_FIXTURE;
  if (path === "/analytics/market-pulse") return MARKET_PULSE_FIXTURE;
  if (path === "/analytics/agent-policy/history") return HISTORY_FIXTURE;
  if (path === "/analytics/agent-policy/cohorts") return COHORTS_FIXTURE;
  if (path === "/analytics/agent-policy") return POLICY_FIXTURE;
  throw new Error(`unexpected apiRequest(${path})`);
});

beforeAll(() => {
  // jsdom ships no matchMedia; the chart kit asks it about reduced motion.
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});

afterEach(() => {
  cleanup();
  apiRequest.mockClear();
});

/** The role this element is covered by — its own, or an ancestor's. */
function roleOf(element: Element): string | null {
  const tagged = element.closest("[data-prose]");
  return tagged ? tagged.getAttribute("data-prose") : null;
}

function isServerAuthored(element: Element): boolean {
  return element.closest('[data-prose-source="server"]') !== null;
}

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Every text-bearing `<p>` the page renders, minus the sr-only data tables —
 *  those are the charts' TEXT EQUIVALENT, required by the kit and never on
 *  screen, so counting them as prose would punish accessibility. */
function proseBlocks(container: HTMLElement): HTMLElement[] {
  return (Array.from(container.querySelectorAll("p")) as HTMLElement[])
    .filter((p) => !p.closest(".sr-only"))
    .filter((p) => text(p).length >= PROSE_MIN_CHARS);
}

async function renderPage(): Promise<HTMLElement> {
  const { container } = render(<AnalyticsPage />);
  // Every panel stays mounted, so waiting for the last-arriving panel is
  // enough to census all three tabs at once.
  await screen.findByTestId("policy-cohorts");
  await screen.findByTestId("market-pulse");
  return container;
}

describe("RULE 1 — zero standalone prose blocks", () => {
  it("gives every prose block on all three tabs an allowed role", async () => {
    const container = await renderPage();
    const untagged = proseBlocks(container)
      .filter((p) => {
        const role = roleOf(p);
        return role === null || !(ALLOWED_ROLES as readonly string[]).includes(role);
      })
      .map((p) => ({ role: roleOf(p), chars: text(p).length, text: text(p).slice(0, 120) }));

    expect(untagged).toEqual([]);
  });

  it("censuses a page whose panels really did resolve (a skeleton would pass vacuously)", async () => {
    const container = await renderPage();
    // The three tab panels are all in the DOM at once.
    expect(container.querySelectorAll('[role="tabpanel"]')).toHaveLength(3);
    // And there is real prose to have judged — this test would be worthless if
    // the fixture rendered a page with no text at all.
    expect(proseBlocks(container).length).toBeGreaterThan(3);
  });
});

describe("RULE 2 — a caption is one line", () => {
  it("keeps every code-authored caption, legend and insight under the one-line ceiling", async () => {
    const container = await renderPage();
    const tooLong = proseBlocks(container)
      .filter((p) => {
        const role = roleOf(p);
        return role === "caption" || role === "legend" || role === "insight";
      })
      .filter((p) => !isServerAuthored(p))
      .filter((p) => text(p).length > CAPTION_MAX_CHARS)
      .map((p) => ({ chars: text(p).length, text: text(p).slice(0, 160) }));

    expect(tooLong).toEqual([]);
  });

  it("renders the server's own honesty strings VERBATIM rather than paraphrasing them to fit", async () => {
    const container = await renderPage();
    const server = Array.from(container.querySelectorAll('[data-prose-source="server"]'));
    expect(server.length).toBeGreaterThan(0);
    // The policy's behaviour sentence is 190+ chars of server copy and is on
    // screen unedited, attached to the knobs it describes.
    expect(screen.getByTestId("agent-policy-behaviour").textContent).toBe(
      POLICY_FIXTURE.behaviour,
    );
    // ROUND 2 (F2): the market panel's server copy is its ROWS' notes, each
    // verbatim and each attached to the comparison it qualifies — no longer
    // one paragraph floating under all three.
    const row0 = MARKET_PULSE_FIXTURE.marketVsYou.comparisons[0];
    expect(screen.getByTestId("market-comparison-note-0").textContent).toBe(
      `${row0.marketNote} ${row0.footnote}`,
    );
  });
});

/**
 * ROUND 2 / F2 — the panel-level `marketVsYou.summary` paragraph is deleted.
 * The exemption that let a 300-character server string sit under three
 * comparisons ("server-authored copy is rendered verbatim") is still the right
 * rule; what it may not do is keep a FLOATING paragraph alive, so this pins
 * the shape the panel now has instead.
 */
describe("the market panel has no floating summary paragraph", () => {
  it("renders no panel-level summary block at all", async () => {
    await renderPage();
    expect(screen.queryByTestId("market-vs-you-summary")).toBeNull();
    const panel = screen.getByTestId("market-vs-you");
    expect(panel.textContent).not.toContain(MARKET_PULSE_FIXTURE.marketVsYou.summary);
  });

  it("keeps every figure that paragraph carried on the row that owns it, as a drawn mark plus a visible note", async () => {
    await renderPage();
    const row = screen.getByTestId("market-comparison-row-0");
    // The number is drawn (a real mark, not only a numeral)...
    expect(row.querySelector("[data-mark]")).not.toBeNull();
    // ...it is legible as text beside the mark...
    expect(row.textContent).toContain("24");
    // ...and its qualifier is ON the row, not behind a hover.
    const note = within(row).getByTestId("market-comparison-note-0");
    expect(note.getAttribute("data-prose")).toBe("caption");
    expect(note.closest('[data-testid="metric-tooltip-popover"]')).toBeNull();
    expect(note.textContent).toContain("Adzuna Australia");
  });

  it("keeps a measured zero apart from an unmeasured row (law C-1)", async () => {
    await renderPage();

    // Not connected: no mark of any kind on the market side, and the row says
    // so in words rather than drawing a zero-length bar.
    const disconnected = screen.getByTestId("market-comparison-row-1");
    expect(disconnected.textContent).toMatch(/market data: not connected/i);
    // Its own side IS measured (0.7%), so that half draws.
    expect(disconnected.querySelector('[data-mark="value"]')).not.toBeNull();

    // Measured 0 on both sides: hairline ticks, not absent bars.
    const zeroRow = screen.getByTestId("market-comparison-row-2");
    expect(zeroRow.querySelectorAll('[data-mark="zero"]')).toHaveLength(2);
    expect(zeroRow.querySelector('[data-mark="value"]')).toBeNull();
  });
});

describe("RULE 3 — a caption is attached to what it qualifies", () => {
  it("places every caption inside a container that also holds a visual", async () => {
    const container = await renderPage();
    const orphans = (Array.from(container.querySelectorAll('[data-prose="caption"]')) as HTMLElement[])
      .filter((caption) => {
        // Walk out to the nearest panel/section/figure and ask whether
        // anything in it actually draws.
        const host =
          caption.closest("figure") ??
          caption.closest("section") ??
          caption.closest('[data-testid]') ??
          container;
        return host.querySelector(VISUAL_SELECTOR) === null;
      })
      .map((c) => text(c).slice(0, 120));

    expect(orphans).toEqual([]);
  });
});

describe("RULE 4 — no bulleted paragraphs", () => {
  it("never renders a list item as a sentence", async () => {
    const container = await renderPage();
    const sentences = (Array.from(container.querySelectorAll("li")) as HTMLElement[])
      .filter((li) => !li.closest(".sr-only"))
      .filter((li) => li.closest("[data-prose]") === null)
      // A list item holding a definition list, a table or a mark is a DATA
      // ROW, not a paragraph — the policy-tier points are exactly that, and
      // counting their `<dl>` text as prose would forbid structured data for
      // being long. What the rule forbids is a bare run of sentence text,
      // which is how the old "why this tier" block was written.
      .filter((li) => li.querySelector("dl, table, svg, [data-mark]") === null)
      .filter((li) => text(li).length >= PROSE_MIN_CHARS)
      .map((li) => text(li).slice(0, 120));

    expect(sentences).toEqual([]);
  });
});

/**
 * ROUND 2 / F1 — the "Dashboard summary" StatBlock grid is deleted, and the
 * SHAPE that let it exist is pinned shut behind it.
 *
 * Deleting the grid closes the instance. It does not close the class: the four
 * rules above census PROSE, and seven bare numerals in a grid are not prose, so
 * a chartless block could be re-added tomorrow without a single rule going red.
 * That is precisely how F1 survived round 1 — every prose rule passed while a
 * zero-chart section sat under the executive band restating it.
 *
 * So the mandate's other half ("ONLY visualisations… remove everything else")
 * gets its own mechanical rule, at the granularity the defect had: a TOP-LEVEL
 * BLOCK of a view. Anything a reader scrolls past as a distinct slab must draw
 * something. Inside a block, a numeral beside its own mark is fine — the stage
 * conversion `<dl>` sits in the same section as the bullet chart that judges it
 * against target, and that is the attachment the mandate asks for.
 */
describe("RULE 5 — every top-level block in a view DRAWS", () => {
  it("no longer renders the bare-numeral Dashboard summary grid", async () => {
    const container = await renderPage();
    expect(screen.queryByTestId("dashboard-summary")).toBeNull();
    expect(text(container)).not.toContain("Dashboard summary");
  });

  /*
   * A PINNED CENSUS, not a pass/fail with an escape hatch.
   *
   * Running this rule page-wide found a SECOND block of F1's exact class that
   * no finding named: `agent-roi` on Quality & ROI WAS five bare-numeral tiles
   * with no mark of any kind — and on the default "all" period its spend and
   * its two cost-per ratios were the same figures the band's spend tile draws
   * above, which is word for word the complaint F1 made about the deleted
   * Dashboard summary.
   *
   * ROUND 3 — THE RULING LANDED, AND THIS LIST IS BACK AT `[]`.
   *
   * The judge's must-fix: delete the duplicated figures (total spend, agent
   * runs — both drawn by the band's spend tile above) and re-express what is
   * genuinely this panel's own as a real visual. Which is what shipped: the
   * two cost-per ratios share ONE scale (dollars), so they are now a two-row
   * `<BulletChart>` with the honest "—" states and their reasons on the rows,
   * and the third scalar (seconds) is the chart's caption rather than a bar on
   * a dollar axis. The escalation note above is kept as the record of why the
   * previous round refused to guess.
   *
   * Pinning the census rather than skipping the tab is what keeps this from
   * being the F2 mistake (a mechanism used to pass a test instead of to satisfy
   * the rule): the list is EXACT, so a new chartless block fails this test, and
   * so does re-adding the one that was just removed.
   */
  const CHARTLESS_BLOCKS: string[] = [];

  it("leaves no chartless top-level block in any view (F3 closed)", async () => {
    const container = await renderPage();
    const chartless = (Array.from(container.querySelectorAll('[role="tabpanel"]')) as HTMLElement[])
      .flatMap((panel) =>
        (Array.from(panel.children) as HTMLElement[])
          // A block that renders nothing claims nothing; the rule is about
          // blocks that put content on screen without drawing it.
          .filter((block) => text(block).length > 0)
          .filter((block) => block.querySelector(VISUAL_SELECTOR) === null)
          .map((block) => {
            const view = panel.getAttribute("data-testid");
            // Identify by the block's own heading, so the pin survives a copy
            // edit inside the block but never survives a NEW block appearing.
            const heading = block.querySelector("h1, h2, h3");
            return `${view} → ${heading === null ? text(block).slice(0, 60) : text(heading).split("(")[0].trim()}`;
          }),
      );

    expect(chartless).toEqual(CHARTLESS_BLOCKS);
  });
});

describe("the honesty content that used to be prose is still on screen", () => {
  it("keeps the conversion gap and its policy claim as an attached caption, not a hover", async () => {
    await renderPage();
    const gap = screen.getByTestId("interview-conversion-gap");
    expect(gap.getAttribute("data-prose")).toBe("caption");
    expect(gap.textContent).toContain("19.3 points to target");
    expect(gap.textContent?.toLowerCase()).toContain("agent performance policy");
  });

  it("keeps the pre-instrumentation cohort count visible, as a caption AND as a ribbon segment", async () => {
    await renderPage();
    const untagged = screen.getByTestId("policy-cohort-untagged");
    expect(untagged.getAttribute("data-prose")).toBe("caption");
    expect(untagged.textContent).toContain("290");
    const cohorts = screen.getByTestId("policy-cohorts");
    expect(within(cohorts).getByTestId("bullet-coverage-legend").textContent).toContain("290");
  });

  it("keeps the funnel's superset qualifier on the chart's face, not only in its hover title", async () => {
    await renderPage();
    const funnel = screen.getByTestId("funnel-chart");
    expect(within(funnel).getByTestId("chart-footnote").textContent).toContain(
      "cumulative all-time discovery",
    );
  });

  it("replaced the policy panel's bullet paragraphs with chips, keeping every trigger legible", async () => {
    await renderPage();
    const triggers = screen.getByTestId("agent-policy-triggers");
    const chips = within(triggers).getAllByTestId("agent-policy-trigger-chip");
    expect(chips).toHaveLength(2);
    expect(triggers.textContent).toContain("conversion");
    expect(triggers.textContent).toContain("cultureFit");
  });
});
