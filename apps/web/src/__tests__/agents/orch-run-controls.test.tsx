// @vitest-environment jsdom
/**
 * ORCH-RUN — "run individual, multiple agents or the whole workflow from the
 * Agent Orchestration — Workflow UI" (user mandate, 2026-08-14).
 *
 * The three affordances under test are UI ORCHESTRATION over machinery that
 * already exists — the console's `trigger(agent.backend)` path, the one run
 * store the map already reads, and the truthful `agents-feedback` notices. No
 * endpoint is added, and nothing here may invent a run state.
 *
 * WHAT THESE TESTS PIN (each one a way the feature could lie):
 *   1. a per-node run dispatches THAT node's backend, once, through the passed
 *      trigger — not the agent key, not a neighbouring node's backend;
 *   2. a roadmap node can never be run and says why in the user's words;
 *   3. a REAL agent the server marks `runnable: false` (e.g. `orchestration` →
 *      backend `supervisor`, absent from `_RUNNABLE_BACKENDS`) is refused with
 *      its own honest reason rather than offered a button that can only 404;
 *   4. a multi-selection dispatches in the MAP'S STAGE ORDER, whatever order
 *      the nodes were clicked in;
 *   5. "Run workflow" is Run pipeline scoped to THAT map — never another map's
 *      agents, never a planned node;
 *   6. three nodes sharing one backend (`matchScoring` / `atsOptimization` /
 *      `skillGap` all resolve to `fitScorer`) produce ONE dispatch, exactly as
 *      Run pipeline does — a per-node dispatch would bill three metered runs;
 *   7. an agent whose run is genuinely in flight (per the run store) offers no
 *      second run, and says which state it is in;
 *   8. an API refusal (quota / spend cap) surfaces the API's OWN words at the
 *      node, and halts the rest of the batch the way `_pipeline_core` halts.
 *
 * Written BEFORE the implementation.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OrchestrationMap from "../../components/agents/OrchestrationMap";
import { buildMapModel } from "../../components/agents/orchestration-map-model";
import {
  NOT_DISPATCHABLE_REASON,
  PLANNED_RUN_REASON,
  runAvailability,
  runTargets,
  stageNarration,
} from "../../components/agents/orchestration-run-plan";
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapData, OrchestrationMapEntry } from "../../lib/api/agentPolicy";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const NOW = Date.parse("2026-08-14T09:00:00Z");

function agent(
  agentKey: string,
  backend: string | null,
  extra: Partial<{ runnable: boolean; name: string }> = {},
) {
  return {
    agentKey,
    name: extra.name ?? agentKey,
    backend,
    status: (backend ? "real" : "planned") as "real" | "planned",
    runnable: extra.runnable ?? (backend ? true : false),
    metricsConsumed: [],
    thresholds: [],
    lastRunPolicyTier: null,
    lastRunAt: null,
    lastRunStatus: null,
    trend: null,
  };
}

/** Mirrors the production payload's shape, including its shared-backend nodes. */
const PIPELINE: OrchestrationMapEntry = {
  key: "application-pipeline",
  name: "Application Pipeline",
  subtitle: "The path one job posting travels from discovery to a tracked application.",
  stages: [
    { stage: "Discovery", agents: [agent("jobDiscovery", "scout")] },
    {
      stage: "Fit Scoring",
      agents: [
        agent("matchScoring", "fitScorer"),
        agent("atsOptimization", "fitScorer"),
        agent("skillGap", "fitScorer"),
        agent("jobMatching", "matcher"),
      ],
    },
    { stage: "Tailoring", agents: [agent("resumeTailoring", "tailor")] },
    // REAL but not independently dispatchable (backend `supervisor`).
    { stage: "Orchestration", agents: [agent("orchestration", "supervisor", { runnable: false })] },
    { stage: "Roadmap", agents: [agent("futureAudit", null)] },
  ],
};

const LEARNING: OrchestrationMapEntry = {
  key: "learning-loop",
  name: "Learning Loop",
  subtitle: null,
  stages: [{ stage: "Signal Capture", agents: [agent("storyExtraction", "storyExtractor")] }],
};

const DATA: OrchestrationMapData = { maps: [PIPELINE, LEARNING] };

function liveRun(agentName: string): AgentRun {
  return {
    id: `run-${agentName}`,
    agentName,
    status: "running",
    createdAt: new Date(NOW - 30_000).toISOString(),
    startedAt: new Date(NOW - 30_000).toISOString(),
    completedAt: null,
    error: null,
    output: null,
  } as AgentRun;
}

/** A trigger stub that records dispatch order and resolves truthful notices. */
function triggerStub(
  outcomes: Record<string, { kind: "success" | "error"; text: string }> = {},
) {
  const calls: string[] = [];
  const fn = vi.fn(async (backend: string) => {
    calls.push(backend);
    return outcomes[backend] ?? { kind: "success" as const, text: `${backend} finished.` };
  });
  return { fn, calls };
}

function renderMap(props: Partial<ComponentProps<typeof OrchestrationMap>> = {}) {
  return render(
    <OrchestrationMap data={DATA} runs={[]} now={NOW} onRunAgent={vi.fn()} {...props} />,
  );
}

// ---------------------------------------------------------------------------
// 1. The plan module — order, dedup and refusal reasons, with no renderer
// ---------------------------------------------------------------------------

describe("ORCH-RUN plan — stage order, one-run-per-backend, honest refusals", () => {
  const model = buildMapModel(PIPELINE, [], NOW);

  it("orders a whole-map plan by stage, left to right", () => {
    expect(runTargets(model).map((t) => t.backend)).toEqual([
      "scout",
      "fitScorer",
      "matcher",
      "tailor",
    ]);
  });

  it("dispatches one run per BACKEND, naming the nodes that share it", () => {
    const fit = runTargets(model).find((t) => t.backend === "fitScorer");
    expect(fit?.agentKey).toBe("matchScoring");
    expect(fit?.alsoCovers).toEqual(["atsOptimization", "skillGap"]);
  });

  it("excludes roadmap nodes and server-marked non-dispatchable agents", () => {
    const backends = runTargets(model).map((t) => t.backend);
    expect(backends).not.toContain("supervisor");
    expect(runTargets(model).map((t) => t.agentKey)).not.toContain("futureAudit");
  });

  it("keeps a selection in stage order regardless of pick order", () => {
    const picked = new Set(["resumeTailoring", "jobDiscovery"]);
    expect(runTargets(model, picked).map((t) => t.backend)).toEqual(["scout", "tailor"]);
  });

  it("never runs a node outside the selection, even one sharing a backend", () => {
    const picked = new Set(["atsOptimization"]);
    const plan = runTargets(model, picked);
    expect(plan).toHaveLength(1);
    expect(plan[0].agentKey).toBe("atsOptimization");
    expect(plan[0].alsoCovers).toEqual([]);
  });

  it("states, in words, why each un-runnable node cannot run", () => {
    const nodeOf = (key: string) =>
      model.stages.flatMap((s) => s.nodes).find((n) => n.agent.agentKey === key)!;
    expect(runAvailability(nodeOf("futureAudit")).reason).toBe(PLANNED_RUN_REASON);
    expect(runAvailability(nodeOf("orchestration")).reason).toBe(NOT_DISPATCHABLE_REASON);
    expect(runAvailability(nodeOf("jobDiscovery")).runnable).toBe(true);
    expect(
      runAvailability(nodeOf("jobDiscovery"), { busyBackend: "pipeline" }).reason,
      // P1-B rename (ADR-AGI-3 Decision 2): the header control is "Run
      // pipeline (5 steps)" now, and this message names the same control.
    ).toMatch(/Run pipeline is in progress/i);
  });

  it("refuses a second run of an agent the run store reports as live", () => {
    const live = buildMapModel(PIPELINE, [liveRun("tailor")], NOW);
    const node = live.stages
      .flatMap((s) => s.nodes)
      .find((n) => n.agent.agentKey === "resumeTailoring")!;
    expect(node.state).toBe("live");
    expect(runAvailability(node)).toEqual({
      runnable: false,
      reason: "Already running — wait for this run to finish",
    });
  });

  it("narrates a stage from counts only, and stays silent about zero failures", () => {
    expect(stageNarration("Fit Scoring", { running: 2, done: 1, failed: 0 })).toBe(
      "Fit Scoring — 2 running / 1 done",
    );
    expect(stageNarration("Tailoring", { running: 0, done: 1, failed: 1 })).toBe(
      "Tailoring — 0 running / 1 done / 1 failed",
    );
  });
});

// ---------------------------------------------------------------------------
// 2. Per-node run
// ---------------------------------------------------------------------------

describe("ORCH-RUN — every real node can be run on its own", () => {
  it("dispatches THAT node's backend, once, through the console's trigger path", async () => {
    const { fn, calls } = triggerStub();
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-resumeTailoring"));

    await waitFor(() => expect(calls).toEqual(["tailor"]));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("gives a roadmap node no run path at all, and says why", () => {
    const { fn } = triggerStub();
    renderMap({ onRunAgent: fn });

    const control = screen.getByTestId("orchestration-run-futureAudit") as HTMLButtonElement;
    expect(control.disabled).toBe(true);
    expect(control.getAttribute("title")).toBe(PLANNED_RUN_REASON);

    fireEvent.click(control);
    expect(fn).not.toHaveBeenCalled();
  });

  it("refuses a real agent the server marks non-dispatchable, in its own words", () => {
    const { fn } = triggerStub();
    renderMap({ onRunAgent: fn });

    const control = screen.getByTestId("orchestration-run-orchestration") as HTMLButtonElement;
    expect(control.disabled).toBe(true);
    expect(control.getAttribute("title")).toBe(NOT_DISPATCHABLE_REASON);
    fireEvent.click(control);
    expect(fn).not.toHaveBeenCalled();
  });

  it("offers no second run while the run store says that agent is live", () => {
    const { fn } = triggerStub();
    renderMap({ onRunAgent: fn, runs: [liveRun("tailor")] });

    const control = screen.getByTestId("orchestration-run-resumeTailoring") as HTMLButtonElement;
    expect(control.disabled).toBe(true);
    expect(control.getAttribute("title")).toMatch(/already running/i);
    fireEvent.click(control);
    expect(fn).not.toHaveBeenCalled();
  });

  it("stands down entirely while the console is running something else", () => {
    const { fn } = triggerStub();
    renderMap({ onRunAgent: fn, busyBackend: "pipeline" });

    const control = screen.getByTestId("orchestration-run-jobDiscovery") as HTMLButtonElement;
    expect(control.disabled).toBe(true);
    expect(control.getAttribute("title")).toMatch(/run pipeline is in progress/i);
  });

  it("renders no run affordance at all when the console passes no trigger", () => {
    render(<OrchestrationMap data={DATA} runs={[]} now={NOW} />);
    expect(screen.queryByTestId("orchestration-run-jobDiscovery")).toBeNull();
    expect(screen.queryByTestId("orchestration-run-workflow-application-pipeline")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. Multi-select
// ---------------------------------------------------------------------------

describe("ORCH-RUN — a selection runs in the map's stage order", () => {
  it("counts the selection and dispatches it left-to-right, whatever the click order", async () => {
    const { fn, calls } = triggerStub();
    renderMap({ onRunAgent: fn });

    // Picked out of order on purpose: Tailoring first, Discovery second.
    fireEvent.click(screen.getByTestId("orchestration-agent-resumeTailoring"));
    fireEvent.click(screen.getByTestId("orchestration-agent-jobDiscovery"));

    const bar = screen.getByTestId("orchestration-run-bar");
    expect(bar.textContent ?? "").toMatch(/2 selected/i);

    fireEvent.click(screen.getByTestId("orchestration-run-selected"));
    await waitFor(() => expect(calls).toEqual(["scout", "tailor"]));
  });

  it("collapses nodes that share one backend into the single run Run pipeline would make", async () => {
    const { fn, calls } = triggerStub();
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-agent-matchScoring"));
    fireEvent.click(screen.getByTestId("orchestration-agent-atsOptimization"));
    fireEvent.click(screen.getByTestId("orchestration-agent-skillGap"));

    fireEvent.click(screen.getByTestId("orchestration-run-selected"));
    await waitFor(() => expect(calls).toEqual(["fitScorer"]));
  });

  it("never lets a roadmap node into a selection", () => {
    renderMap();
    fireEvent.click(screen.getByTestId("orchestration-agent-futureAudit"));
    expect(screen.queryByTestId("orchestration-run-bar")).toBeNull();
    expect(
      screen.getByTestId("orchestration-agent-futureAudit").getAttribute("data-selected"),
    ).not.toBe("true");
  });

  it("shows the selection on the node itself and clears the whole thing on Escape", () => {
    renderMap();
    const node = screen.getByTestId("orchestration-agent-jobDiscovery");
    fireEvent.click(node);
    expect(node.getAttribute("data-selected")).toBe("true");
    expect(screen.getByTestId("orchestration-run-bar")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("orchestration-run-bar")).toBeNull();
    expect(
      screen.getByTestId("orchestration-agent-jobDiscovery").getAttribute("data-selected"),
    ).not.toBe("true");
  });
});

// ---------------------------------------------------------------------------
// 4. Run workflow — Run pipeline scoped to one map
// ---------------------------------------------------------------------------

describe("ORCH-RUN — 'Run workflow' is Run pipeline scoped to that map", () => {
  it("runs every runnable agent of THAT map, in stage order, and nothing else", async () => {
    const { fn, calls } = triggerStub();
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => expect(calls).toEqual(["scout", "fitScorer", "matcher", "tailor"]));
    expect(calls).not.toContain("storyExtractor");
    expect(calls).not.toContain("supervisor");
  });

  it("keeps a second map's workflow to its own agents", async () => {
    const { fn, calls } = triggerStub();
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-learning-loop"));

    await waitFor(() => expect(calls).toEqual(["storyExtractor"]));
  });

  it("narrates progress stage by stage from real state, never a fabricated one", async () => {
    // The FIRST dispatch is held open, so the narration can be read while it is
    // genuinely mid-flight — and the run store genuinely reports scout in
    // flight, which is where "1 running" comes from. "0 done" while the run is
    // open is the point: nothing may be counted finished before it reports.
    let release: (n: { kind: "success"; text: string }) => void = () => {};
    const gate = new Promise<{ kind: "success"; text: string }>((resolve) => {
      release = resolve;
    });
    const fn = vi.fn(async (backend: string) =>
      backend === "scout" ? gate : { kind: "success" as const, text: `${backend} finished.` },
    );
    renderMap({ onRunAgent: fn, runs: [liveRun("scout")] });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => {
      expect(
        screen.getByTestId("orchestration-run-progress-application-pipeline").textContent ?? "",
      ).toMatch(/Discovery — 1 running \/ 0 done/);
    });

    release({ kind: "success", text: "Scout finished — 3 new jobs discovered." });

    await waitFor(() => {
      expect(
        screen.getByTestId("orchestration-run-progress-application-pipeline").textContent ?? "",
      ).toMatch(/Discovery — 1 running \/ 1 done/);
    });
  });
});

// ---------------------------------------------------------------------------
// 5. Refusals surface the API's own words, and halt the batch
// ---------------------------------------------------------------------------

describe("ORCH-RUN — an API refusal is quoted, not paraphrased", () => {
  const QUOTA =
    "Tailor is blocked — you've reached your plan's run quota for this period. Runs resume on Sep 1 at 9:00 am.";

  it("shows the API's own reason on the node that was refused", async () => {
    const { fn } = triggerStub({ tailor: { kind: "error", text: QUOTA } });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-resumeTailoring"));

    await waitFor(() => {
      expect(
        screen.getByTestId("orchestration-run-outcome-resumeTailoring").textContent ?? "",
      ).toContain(QUOTA);
    });
  });

  it("halts the rest of the batch on a refusal, exactly as the pipeline does", async () => {
    const { fn, calls } = triggerStub({ fitScorer: { kind: "error", text: QUOTA } });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => expect(calls).toEqual(["scout", "fitScorer"]));
    // matcher/tailor were never dispatched — the refusal ended the run.
    expect(calls).not.toContain("matcher");
    expect(calls).not.toContain("tailor");
    await waitFor(() => {
      expect(
        screen.getByTestId("orchestration-run-progress-application-pipeline").textContent ?? "",
      ).toMatch(/stopped/i);
    });
  });

  it("LOOP-429: waits a short rate-limit Retry-After and retries that step once before continuing", async () => {
    const RATE =
      "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.";
    const calls: string[] = [];
    let tailorAttempts = 0;
    const fn = vi.fn(async (backend: string) => {
      calls.push(backend);
      if (backend === "tailor") {
        tailorAttempts += 1;
        if (tailorAttempts === 1) {
          return { kind: "error" as const, text: RATE, retryAfterSeconds: 0 };
        }
      }
      return { kind: "success" as const, text: `${backend} finished.` };
    });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => expect(calls).toEqual(["scout", "fitScorer", "matcher", "tailor", "tailor"]));
    expect(tailorAttempts).toBe(2);
  });

  it("LOOP-429: a long cooldown does not auto-retry; Resume continues from the halted agent", async () => {
    const RATE =
      "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.";
    const calls: string[] = [];
    const fn = vi.fn(async (backend: string) => {
      calls.push(backend);
      if (backend === "fitScorer" && calls.filter((c) => c === "fitScorer").length === 1) {
        return { kind: "error" as const, text: RATE, retryAfterSeconds: 812 };
      }
      return { kind: "success" as const, text: `${backend} finished.` };
    });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => expect(calls).toEqual(["scout", "fitScorer"]));
    expect(calls).not.toContain("matcher");
    await waitFor(() => {
      expect(screen.getByTestId("orchestration-run-resume-application-pipeline")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("orchestration-run-resume-application-pipeline"));

    await waitFor(() =>
      expect(calls).toEqual(["scout", "fitScorer", "fitScorer", "matcher", "tailor"]),
    );
  });

  it("LOOP-429: a rate-limit without Retry-After does not auto-retry (production async drop)", async () => {
    const RATE =
      "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.";
    const calls: string[] = [];
    const fn = vi.fn(async (backend: string) => {
      calls.push(backend);
      if (backend === "tailor") {
        return { kind: "error" as const, text: RATE };
      }
      return { kind: "success" as const, text: `${backend} finished.` };
    });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => expect(calls).toEqual(["scout", "fitScorer", "matcher", "tailor"]));
    expect(calls.filter((c) => c === "tailor")).toHaveLength(1);
    await waitFor(() => {
      expect(screen.getByTestId("orchestration-run-resume-application-pipeline")).toBeTruthy();
    });
  });

  it("LOOP-429: unmounting during a Retry-After wait does not fire a second dispatch", async () => {
    vi.useFakeTimers();
    try {
      const RATE =
        "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.";
      const calls: string[] = [];
      const fn = vi.fn(async (backend: string) => {
        calls.push(backend);
        if (backend === "tailor") {
          return { kind: "error" as const, text: RATE, retryAfterSeconds: 60 };
        }
        return { kind: "success" as const, text: `${backend} finished.` };
      });
      const { unmount } = renderMap({ onRunAgent: fn });
      fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));
      await vi.advanceTimersByTimeAsync(20);
      expect(calls.filter((c) => c === "tailor")).toHaveLength(1);
      unmount();
      await vi.advanceTimersByTimeAsync(70_000);
      expect(calls.filter((c) => c === "tailor")).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("LOOP-429: a quota halt does not offer Resume (waiting cannot lift a quota wall)", async () => {
    const { fn, calls } = triggerStub({ fitScorer: { kind: "error", text: QUOTA } });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    await waitFor(() => expect(calls).toEqual(["scout", "fitScorer"]));
    await waitFor(() => {
      expect(
        screen.getByTestId("orchestration-run-progress-application-pipeline").textContent ?? "",
      ).toMatch(/stopped/i);
    });
    expect(screen.queryByTestId("orchestration-run-resume-application-pipeline")).toBeNull();
  });

  it("keeps a single node's result to the node the user actually ran", async () => {
    const { fn } = triggerStub({ fitScorer: { kind: "error", text: QUOTA } });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-matchScoring"));

    await waitFor(() => {
      expect(
        screen.getByTestId("orchestration-run-outcome-matchScoring").textContent ?? "",
      ).toContain(QUOTA);
    });
    // The user ran ONE node. Its two backend-siblings were not asked for and
    // are not annotated as though they had been.
    expect(screen.queryByTestId("orchestration-run-outcome-atsOptimization")).toBeNull();
    expect(screen.queryByTestId("orchestration-run-outcome-skillGap")).toBeNull();
  });

  it("reports a whole-map dispatch on every node that one run genuinely covered", async () => {
    const { fn } = triggerStub({ fitScorer: { kind: "error", text: QUOTA } });
    renderMap({ onRunAgent: fn });

    fireEvent.click(screen.getByTestId("orchestration-run-workflow-application-pipeline"));

    // One fitScorer run stands for all three nodes that share it, so all three
    // carry its refusal — hiding it on two of them would imply they were fine.
    for (const key of ["matchScoring", "atsOptimization", "skillGap"]) {
      await waitFor(() => {
        expect(screen.getByTestId(`orchestration-run-outcome-${key}`).textContent ?? "").toContain(
          QUOTA,
        );
      });
    }
  });
});
