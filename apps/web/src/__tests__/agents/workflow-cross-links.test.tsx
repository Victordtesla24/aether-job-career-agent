// @vitest-environment jsdom
/**
 * U-STORY-3a — CROSS-MAP PORTS + the "Show connections" LINKAGE OVERLAY.
 *
 * USER MANDATE (2026-08-14): "story extraction and resume tailoring / cover
 * letter agents are on separate workflows on the UI — users must be able to
 * KNOW THE LINKAGES VISUALLY to know what happened to their job search and
 * application and when."
 *
 * THE BINDING EDGE MODEL. Two classes of relationship exist, and only one of
 * them is buildable today:
 *   - STRUCTURAL ("Story Bank feeds Resume Tailoring") — true of the system,
 *     sourced from the checked-in linkage table, every edge carrying file:line
 *     provenance. Drawn as system wiring: quiet, labelled, and NEVER animated,
 *     because nothing is flowing along it right now;
 *   - CAUSAL, run-level ("this run consumed stories X and Y at 10:42") — needs
 *     a parent run id the API does not record yet. NOT in this slice, not faked
 *     here, and not pre-built as dead UI.
 *
 * WHAT THESE TESTS PIN (each one a way the feature could lie or exclude):
 *   1. a node whose counterpart lives on ANOTHER map shows a port naming that
 *      counterpart and its map, in the exact words the mandate asked for;
 *   2. the port is a real button — keyboard reachable, Enter-activatable — and
 *      moves focus to the counterpart node and flashes it;
 *   3. a linkage whose endpoints happen to share one map draws NO port (it is
 *      not a cross-map fact), and an endpoint the payload does not contain
 *      draws nothing at all;
 *   4. the overlay is OFF by default, ON from `?links=1`, and toggling it
 *      writes that state back to the URL so the view is shareable;
 *   5. every drawn linkage line is inert: `data-motion="none"`, no SVG
 *      animation element anywhere in the overlay, and never the coral reserved
 *      for a genuinely live run;
 *   6. selecting a node highlights its full in+out cross-map neighbourhood and
 *      dims everything else;
 *   7. the plain-language legend states both classes honestly, promising no
 *      date for the run traces;
 *   8. the stage-transition edge layer is untouched — the map's own honesty
 *      rules (a planned edge is dashed, only a live stage pulses) still hold
 *      with the overlay on.
 *
 * Written BEFORE the implementation.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OrchestrationMap from "../../components/agents/OrchestrationMap";
import { buildMapModel } from "../../components/agents/orchestration-map-model";
import {
  LINKAGE_LEGEND,
  LINKAGE_TOGGLE_LABEL,
  WORKFLOW_LINKAGES,
  buildLinkageLines,
  crossMapLinks,
  neighborhoodOf,
  portsFor,
  type Box,
} from "../../components/agents/workflow-linkage";
import type { OrchestrationMapData, OrchestrationMapEntry } from "../../lib/api/agentPolicy";

const NOW = Date.parse("2026-08-14T09:00:00Z");

function agent(agentKey: string, backend: string | null, name?: string) {
  return {
    agentKey,
    name: name ?? agentKey,
    backend,
    status: (backend ? "real" : "planned") as "real" | "planned",
    runnable: Boolean(backend),
    metricsConsumed: [],
    thresholds: [],
    lastRunPolicyTier: null,
    lastRunAt: null,
    lastRunStatus: null,
    trend: null,
  };
}

/** The production map keys, names and placements — three separate workflows. */
const PIPELINE: OrchestrationMapEntry = {
  key: "application-pipeline",
  name: "Application Pipeline",
  subtitle: "The path one job posting travels from discovery to a tracked application.",
  stages: [
    { stage: "Discovery", agents: [agent("jobDiscovery", "scout", "Job Discovery Agent")] },
    { stage: "Tailoring", agents: [agent("resumeTailoring", "tailor", "Resume Tailoring Agent")] },
    { stage: "Cover Letter", agents: [agent("coverLetter", "coverLetter", "Cover Letter Agent")] },
    {
      stage: "Submission",
      agents: [
        agent("submission", "submission", "Submission Agent"),
        agent("emailAgent", "emailAgent", "Email Agent"),
      ],
    },
  ],
};

const LEARNING: OrchestrationMapEntry = {
  key: "learning-loop",
  name: "Learning Loop",
  subtitle: null,
  stages: [
    { stage: "Orchestration", agents: [agent("orchestration", "supervisor", "Orchestration Agent")] },
    {
      stage: "Signal Capture",
      agents: [
        agent("storyExtraction", "storyExtractor", "Story Extraction Agent"),
        agent("sentimentAnalysis", "sentimentAnalysis", "Sentiment Analysis Agent"),
      ],
    },
    {
      stage: "Learning",
      agents: [agent("learningFeedback", "learningFeedback", "Learning Feedback Agent")],
    },
  ],
};

const ENRICHMENT: OrchestrationMapEntry = {
  key: "enrichment",
  name: "Context & Enrichment",
  subtitle: null,
  stages: [
    { stage: "Market Intelligence", agents: [agent("marketTrends", "marketTrends", "Market Trends Agent")] },
    { stage: "Interview Readiness", agents: [agent("interviewPrep", "interviewPrep", "Interview Prep Agent")] },
  ],
};

const DATA: OrchestrationMapData = { maps: [PIPELINE, LEARNING, ENRICHMENT] };

/** Same agents, but story extraction moved ONTO the application pipeline. */
const SAME_MAP_DATA: OrchestrationMapData = {
  maps: [
    {
      ...PIPELINE,
      stages: [
        ...PIPELINE.stages,
        {
          stage: "Signal Capture",
          agents: [agent("storyExtraction", "storyExtractor", "Story Extraction Agent")],
        },
      ],
    },
  ],
};

const MODELS = DATA.maps.map((m) => buildMapModel(m, [], NOW));

// ---------------------------------------------------------------------------
// jsdom has no layout. The overlay measures real boxes, so the tests that care
// about DRAWN lines install a deterministic geometry: every node card gets its
// own 160×104 box on a 1600×1400 page, laid out in the order it was rendered.
// ---------------------------------------------------------------------------
function box(x: number, y: number, w = 160, h = 104): DOMRect {
  return {
    x,
    y,
    left: x,
    top: y,
    right: x + w,
    bottom: y + h,
    width: w,
    height: h,
    toJSON: () => ({}),
  } as DOMRect;
}

function installGeometry() {
  const seen = new Map<string, number>();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const nodeId = this.dataset.nodeId;
    if (nodeId) {
      if (!seen.has(nodeId)) seen.set(nodeId, seen.size);
      const i = seen.get(nodeId)!;
      return box(40 + (i % 4) * 200, 60 + Math.floor(i / 4) * 300);
    }
    const testid = this.dataset.testid ?? this.getAttribute("data-testid") ?? "";
    if (testid.startsWith("orchestration-graph-")) return box(0, 0, 1600, 260);
    return box(0, 0, 1600, 1400);
  });
}

function setUrl(search: string) {
  window.history.replaceState({}, "", `/dashboard/agents${search}`);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setUrl("");
});

beforeEach(() => setUrl(""));

// ---------------------------------------------------------------------------
// 1. The pure linkage layer — placement, ports, neighbourhood, geometry
// ---------------------------------------------------------------------------

describe("cross-map linkage model", () => {
  it("keeps only linkages whose two endpoints sit on DIFFERENT maps in this payload", () => {
    const links = crossMapLinks(MODELS);
    const ids = links.map((l) => l.link.id);
    expect(ids).toContain("storyExtraction->resumeTailoring");
    expect(ids).toContain("storyExtraction->coverLetter");
    expect(ids).toContain("resumeTailoring->storyExtraction");
    links.forEach((l) => expect(l.from.mapKey).not.toBe(l.to.mapKey));
  });

  it("drops a linkage whose endpoints share one map, rather than drawing a wire between neighbours", () => {
    const models = SAME_MAP_DATA.maps.map((m) => buildMapModel(m, [], NOW));
    const ids = crossMapLinks(models).map((l) => l.link.id);
    expect(ids).not.toContain("storyExtraction->resumeTailoring");
  });

  it("drops a linkage whose endpoint this payload does not contain at all", () => {
    const ids = crossMapLinks(MODELS).map((l) => l.link.id);
    // salaryIntelligence / companyResearch are absent from the fixture payload.
    expect(ids.some((id) => id.includes("salaryIntelligence"))).toBe(false);
    expect(ids.some((id) => id.includes("companyResearch"))).toBe(false);
  });

  it("words a port exactly as the mandate asked, in both directions", () => {
    const links = crossMapLinks(MODELS);
    const out = portsFor("storyExtraction", links).find(
      (p) => p.link.id === "storyExtraction->resumeTailoring",
    )!;
    expect(out.direction).toBe("out");
    expect(out.label).toBe("→ feeds Resume Tailoring Agent (Application Pipeline)");

    const back = portsFor("resumeTailoring", links).find(
      (p) => p.link.id === "storyExtraction->resumeTailoring",
    )!;
    expect(back.direction).toBe("in");
    expect(back.label).toBe("← from Story Extraction Agent (Learning Loop)");
    // The plain-language meaning travels with the port, not only the names.
    expect(back.description).toContain(back.link.meaning);
  });

  it("resolves a node's full in+out neighbourhood", () => {
    const links = crossMapLinks(MODELS);
    const hood = neighborhoodOf(["storyExtraction"], links);
    expect(hood.keys.has("resumeTailoring")).toBe(true); // out
    expect(hood.keys.has("coverLetter")).toBe(true); // out
    expect(hood.keys.has("interviewPrep")).toBe(true); // out
    expect(hood.keys.has("storyExtraction")).toBe(true); // the focus itself
    // resumeTailoring -> storyExtraction is an INBOUND edge and must be in it.
    expect(hood.linkIds.has("resumeTailoring->storyExtraction")).toBe(true);
    // Untouched agents stay outside the neighbourhood.
    expect(hood.keys.has("marketTrends")).toBe(false);
  });

  it("builds inert, labelled geometry — never motion, never coral", () => {
    const links = crossMapLinks(MODELS);
    const boxes: Record<string, Box> = {
      storyExtraction: { x: 100, y: 600, w: 160, h: 104 },
      resumeTailoring: { x: 400, y: 100, w: 160, h: 104 },
      coverLetter: { x: 700, y: 100, w: 160, h: 104 },
    };
    const lines = buildLinkageLines(links, boxes);
    expect(lines.length).toBeGreaterThan(0);
    lines.forEach((line) => {
      expect(line.motion).toBe("none");
      expect(line.structural).toBe(true);
      expect(line.path).toMatch(/^M /);
      expect(line.label.length).toBeGreaterThan(0);
      expect(JSON.stringify(line).toUpperCase()).not.toContain("FF6B35");
    });
    // A linkage with no measured box on one end is skipped, never guessed.
    expect(lines.every((l) => boxes[l.from] && boxes[l.to])).toBe(true);
  });

  it("keeps a label off the node cards it would otherwise print across", () => {
    const links = crossMapLinks(MODELS).filter(
      (l) => l.link.id === "storyExtraction->resumeTailoring",
    );
    const boxes: Record<string, Box> = {
      storyExtraction: { x: 100, y: 600, w: 160, h: 104 },
      resumeTailoring: { x: 100, y: 100, w: 160, h: 104 },
      // A card parked exactly where the wire's midpoint label would land.
      submission: { x: 40, y: 330, w: 280, h: 120 },
    };
    const [line] = buildLinkageLines(links, boxes);
    const label = { x: line.labelX - line.labelWidth / 2, y: line.labelY - 15, w: line.labelWidth, h: 14 };
    const blocker = boxes.submission;
    const hits =
      label.x < blocker.x + blocker.w &&
      label.x + label.w > blocker.x &&
      label.y < blocker.y + blocker.h &&
      label.y + label.h > blocker.y;
    expect(hits).toBe(false);
  });

  it("staggers labels so two wires leaving one node do not print on top of each other", () => {
    const links = crossMapLinks(MODELS).filter(
      (l) =>
        l.link.id === "storyExtraction->resumeTailoring" ||
        l.link.id === "storyExtraction->coverLetter",
    );
    expect(links).toHaveLength(2);
    const boxes: Record<string, Box> = {
      storyExtraction: { x: 100, y: 600, w: 160, h: 104 },
      resumeTailoring: { x: 400, y: 100, w: 160, h: 104 },
      coverLetter: { x: 420, y: 100, w: 160, h: 104 },
    };
    const [a, b] = buildLinkageLines(links, boxes);
    expect(Math.abs(a.labelY - b.labelY)).toBeGreaterThan(20);
  });
});

// ---------------------------------------------------------------------------
// 2. Ports on the node cards
// ---------------------------------------------------------------------------

describe("cross-map ports on the node", () => {
  it("names the counterpart and its map on the node that feeds it", () => {
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const port = screen.getByTestId("orchestration-port-out-storyExtraction->resumeTailoring");
    expect(port.getAttribute("aria-label")).toContain(
      "→ feeds Resume Tailoring Agent (Application Pipeline)",
    );
    expect(port.tagName).toBe("BUTTON");
  });

  it("names the source on the node that is fed", () => {
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const port = screen.getByTestId("orchestration-port-in-storyExtraction->coverLetter");
    expect(port.getAttribute("aria-label")).toContain(
      "← from Story Extraction Agent (Learning Loop)",
    );
  });

  it("renders no port when the two agents share a map", () => {
    render(<OrchestrationMap data={SAME_MAP_DATA} runs={[]} now={NOW} />);
    expect(
      screen.queryByTestId("orchestration-port-out-storyExtraction->resumeTailoring"),
    ).toBeNull();
  });

  it("moves focus to the counterpart node and flashes it, from the keyboard", () => {
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const port = screen.getByTestId("orchestration-port-out-storyExtraction->resumeTailoring");
    const target = screen.getByTestId("orchestration-agent-resumeTailoring");
    const scrollIntoView = vi.fn();
    target.scrollIntoView = scrollIntoView;

    port.focus();
    expect(document.activeElement).toBe(port);
    fireEvent.click(port); // Enter on a <button> dispatches click
    expect(document.activeElement).toBe(target);
    expect(target.getAttribute("data-flash")).toBe("true");
    expect(scrollIntoView).toHaveBeenCalled();
    // A flash is a wayfinding cue, never a claim that something is running.
    expect(target.getAttribute("data-motion")).toBe("none");
  });

  it("clears the flash again so it can never read as a state", () => {
    vi.useFakeTimers();
    try {
      render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
      const port = screen.getByTestId("orchestration-port-out-storyExtraction->resumeTailoring");
      const target = screen.getByTestId("orchestration-agent-resumeTailoring");
      target.scrollIntoView = vi.fn();
      fireEvent.click(port);
      expect(target.getAttribute("data-flash")).toBe("true");
      // The clear lands on a timer, i.e. outside React's event batching.
      act(() => {
        vi.advanceTimersByTime(3000);
      });
      expect(
        screen.getByTestId("orchestration-agent-resumeTailoring").getAttribute("data-flash"),
      ).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

// ---------------------------------------------------------------------------
// 3. The overlay toggle, its URL state and its legend
// ---------------------------------------------------------------------------

describe("Show connections — the linkage overlay", () => {
  it("is OFF by default and draws no overlay", () => {
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const toggle = screen.getByTestId("orchestration-links-toggle");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.textContent ?? "").toContain(LINKAGE_TOGGLE_LABEL);
    expect(screen.queryByTestId("orchestration-linkage-overlay")).toBeNull();
  });

  it("states both edge classes in plain language, with no promised date", () => {
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const legend = screen.getByTestId("orchestration-links-legend");
    expect(legend.textContent ?? "").toContain(LINKAGE_LEGEND);
    expect(LINKAGE_LEGEND).toContain("System wiring");
    expect(LINKAGE_LEGEND).toContain("real run records");
    expect(LINKAGE_LEGEND).not.toMatch(/\b20\d\d\b|\bQ[1-4]\b|next (week|month|release)/i);
  });

  it("comes up ON when the URL says ?links=1, so the view is shareable", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    expect(screen.getByTestId("orchestration-links-toggle").getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByTestId("orchestration-linkage-overlay")).toBeTruthy();
  });

  it("writes the toggle state back to the URL, both ways", () => {
    installGeometry();
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const toggle = screen.getByTestId("orchestration-links-toggle");
    fireEvent.click(toggle);
    expect(window.location.search).toContain("links=1");
    expect(screen.getByTestId("orchestration-linkage-overlay")).toBeTruthy();
    fireEvent.click(toggle);
    expect(window.location.search).not.toContain("links=1");
    expect(screen.queryByTestId("orchestration-linkage-overlay")).toBeNull();
  });

  it("draws the story-bank wiring as labelled, INERT lines", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const overlay = screen.getByTestId("orchestration-linkage-overlay");

    const tailoring = within(overlay).getByTestId(
      "orchestration-linkage-storyExtraction->resumeTailoring",
    );
    expect(tailoring.getAttribute("data-motion")).toBe("none");
    expect(tailoring.getAttribute("data-structural")).toBe("true");

    // NOTHING in the overlay may move: no SMIL, no coral, no dash animation.
    expect(overlay.querySelectorAll("animate, animateMotion, animateTransform")).toHaveLength(0);
    expect(overlay.querySelectorAll('[data-motion="pulse"]')).toHaveLength(0);
    expect(overlay.innerHTML.toUpperCase()).not.toContain("FF6B35");
  });

  it("leaves the stage-transition edge layer exactly as it was", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const edges = screen.getByTestId("orchestration-edges-application-pipeline");
    // No run is in flight in this fixture, so no stage edge may be active.
    expect(edges.querySelectorAll('[data-motion="pulse"]')).toHaveLength(0);
    expect(edges.querySelectorAll("g").length).toBeGreaterThan(0);
  });

  it("states the wiring in words for a screen reader, not only in curves", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    const text = screen.getByTestId("orchestration-linkage-text").textContent ?? "";
    expect(text).toContain("Story Extraction Agent");
    expect(text).toContain("Resume Tailoring Agent");
    expect(text).toContain("Application Pipeline");
  });
});

// ---------------------------------------------------------------------------
// 4. Neighbourhood highlight
// ---------------------------------------------------------------------------

describe("selected node — its linkage neighbourhood highlights, the rest dims", () => {
  it("highlights in+out counterparts across maps and dims everything else", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} onRunAgent={vi.fn()} />);

    fireEvent.click(screen.getByTestId("orchestration-agent-storyExtraction"));

    expect(screen.getByTestId("orchestration-agent-storyExtraction").getAttribute("data-linkage")).toBe(
      "focus",
    );
    expect(screen.getByTestId("orchestration-agent-resumeTailoring").getAttribute("data-linkage")).toBe(
      "neighbour",
    );
    expect(screen.getByTestId("orchestration-agent-coverLetter").getAttribute("data-linkage")).toBe(
      "neighbour",
    );
    expect(screen.getByTestId("orchestration-agent-interviewPrep").getAttribute("data-linkage")).toBe(
      "neighbour",
    );
    expect(screen.getByTestId("orchestration-agent-marketTrends").getAttribute("data-linkage")).toBe(
      "dimmed",
    );

    const overlay = screen.getByTestId("orchestration-linkage-overlay");
    expect(
      within(overlay)
        .getByTestId("orchestration-linkage-storyExtraction->resumeTailoring")
        .getAttribute("data-linkage"),
    ).toBe("focus");
    const unrelated = within(overlay).queryByTestId(
      "orchestration-linkage-jobDiscovery->marketTrends",
    );
    if (unrelated) expect(unrelated.getAttribute("data-linkage")).toBe("dimmed");
  });

  it("dims nothing at all when no node is selected", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} onRunAgent={vi.fn()} />);
    expect(document.querySelectorAll('[data-linkage="dimmed"]')).toHaveLength(0);
  });

  it("never highlights a linkage the table does not carry", () => {
    installGeometry();
    setUrl("?links=1");
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} onRunAgent={vi.fn()} />);
    fireEvent.click(screen.getByTestId("orchestration-agent-storyExtraction"));
    // submission is on no linkage with storyExtraction in the table.
    expect(WORKFLOW_LINKAGES.some((l) => l.id === "storyExtraction->submission")).toBe(false);
    expect(screen.getByTestId("orchestration-agent-submission").getAttribute("data-linkage")).toBe(
      "dimmed",
    );
  });
});
