// @vitest-environment jsdom
/**
 * B6 — REAL causal run edges (ORCH-B1-BLUEPRINT-2026-08-14.md §4.4).
 *
 * `workflow-cross-links.test.tsx`'s own header named this the deferred half
 * of "two classes of edge": STRUCTURAL (code wiring, checked in) is
 * buildable today; CAUSAL, run-level ("this run consumed stories X and Y at
 * 10:42") "needs a parent run id the API does not record yet ... NOT in this
 * slice, not faked here, and not pre-built as dead UI."
 *
 * The API now records it — `AgentRun.parentRunId`, stamped by
 * `_pipeline_core` on every step it dispatches (`apps/api/tests/
 * test_b6_parent_run_id.py`). This file pins the FE half: a causal edge is
 * drawn ONLY for a run pair BOTH present in the fetched `runs` window, with
 * BOTH backends resolving to a placed catalog agent — absent otherwise, the
 * same zero-fabrication discipline `crossMapLinks` already enforces for the
 * structural layer.
 *
 * Written following `workflow-cross-links.test.tsx`'s own fixture/render
 * patterns.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import OrchestrationMap from "../../components/agents/OrchestrationMap";
import type { AgentRun } from "../../lib/api/agents";
import type { OrchestrationMapAgent, OrchestrationMapEntry } from "../../lib/api/agentPolicy";
import { buildMapModel } from "../../components/agents/orchestration-map-model";
import { causalEdges, causalPortsFor } from "../../components/agents/workflow-linkage";

const NOW = Date.parse("2026-08-14T09:00:00Z");

function agent(agentKey: string, backend: string | null, name?: string): OrchestrationMapAgent {
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

const PIPELINE: OrchestrationMapEntry = {
  key: "application-pipeline",
  name: "Application Pipeline",
  subtitle: null,
  stages: [
    { stage: "Discovery", agents: [agent("jobDiscovery", "scout", "Job Discovery Agent")] },
    {
      stage: "Fit Scoring",
      agents: [agent("matchScoring", "fitScorer", "Fit Scoring Agent")],
    },
    { stage: "Tailoring", agents: [agent("resumeTailoring", "tailor", "Resume Tailoring Agent")] },
  ],
};

const LEARNING: OrchestrationMapEntry = {
  key: "learning-loop",
  name: "Learning Loop",
  subtitle: null,
  stages: [
    { stage: "Orchestration", agents: [agent("orchestration", "supervisor", "Orchestration Agent")] },
  ],
};

const DATA = { maps: [PIPELINE, LEARNING] };
const MODELS = DATA.maps.map((m) => buildMapModel(m, [], NOW));

/** Minimal, honest AgentRun fixture — mirrors `stale-run-honesty.test.tsx`'s
 *  own `run()` builder. */
function run(overrides: Partial<AgentRun> & { id: string; agentName: string }): AgentRun {
  const created = overrides.createdAt ?? new Date(NOW).toISOString();
  return {
    status: "completed",
    input: null,
    output: null,
    error: null,
    costUsd: null,
    startedAt: created,
    completedAt: created,
    parentRunId: null,
    ...overrides,
    createdAt: created,
  };
}

afterEach(cleanup);

describe("causalEdges (pure model)", () => {
  it("builds a real edge when a run's parentRunId names another run IN THE SAME fetched window", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: "sup-1" });
    const edges = causalEdges([sup, scout], MODELS);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      id: "sup-1->scout-1",
      parentRunId: "sup-1",
      childRunId: "scout-1",
    });
    expect(edges[0].from.name).toBe("Orchestration Agent");
    expect(edges[0].to.name).toBe("Job Discovery Agent");
  });

  it("drops the pair when the parent run is NOT present in the fetched window — never approximated", () => {
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: "sup-not-fetched" });
    expect(causalEdges([scout], MODELS)).toHaveLength(0);
  });

  it("drops nothing to invent when parentRunId is null — the honest default", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: null });
    expect(causalEdges([sup, scout], MODELS)).toHaveLength(0);
  });

  it("drops a pair whose backend is not placed on this payload, rather than guessing", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const unplaced = run({
      id: "salary-1", agentName: "salaryIntelligence", parentRunId: "sup-1",
    });
    expect(causalEdges([sup, unplaced], MODELS)).toHaveLength(0);
  });

  it("multiple children of the same parent are siblings, not chained to each other", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: "sup-1" });
    const fit = run({ id: "fit-1", agentName: "fitScorer", parentRunId: "sup-1" });
    const edges = causalEdges([sup, scout, fit], MODELS);
    expect(edges.map((e) => e.id).sort()).toEqual(["sup-1->fit-1", "sup-1->scout-1"]);
  });
});

describe("causalPortsFor (pure model)", () => {
  it("words the port distinctly from a structural one, in both directions", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: "sup-1" });
    const edges = causalEdges([sup, scout], MODELS);

    const out = causalPortsFor("supervisor", edges)[0];
    expect(out.direction).toBe("out");
    expect(out.label).toBe("⛓ caused Job Discovery Agent (Application Pipeline)");
    expect(out.description).toContain("not a stage-order inference");

    const back = causalPortsFor("scout", edges)[0];
    expect(back.direction).toBe("in");
    expect(back.label).toBe("⛓ caused by Orchestration Agent (Learning Loop)");
  });
});

describe("OrchestrationMap renders real causal ports, absent otherwise", () => {
  it("shows a causal port on the child node for a real recorded pair", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: "sup-1" });
    render(<OrchestrationMap data={DATA} runs={[sup, scout]} now={NOW} />);

    expect(
      screen.getByTestId("orchestration-causal-port-in-sup-1->scout-1"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("orchestration-causal-port-out-sup-1->scout-1"),
    ).toBeTruthy();
  });

  it("draws nothing when no run carries a parentRunId", () => {
    const sup = run({ id: "sup-1", agentName: "supervisor" });
    const scout = run({ id: "scout-1", agentName: "scout" }); // no parentRunId
    render(<OrchestrationMap data={DATA} runs={[sup, scout]} now={NOW} />);

    expect(screen.queryByTestId(/orchestration-causal-port-/)).toBeNull();
    expect(screen.queryByTestId("orchestration-causal-ports-jobDiscovery")).toBeNull();
  });

  it("draws nothing when the named parent fell outside the fetched window", () => {
    // scout claims a parent, but that run never made it into this response —
    // e.g. it aged out of GET /agents/runs' window. Must not be guessed.
    const scout = run({ id: "scout-1", agentName: "scout", parentRunId: "sup-gone" });
    render(<OrchestrationMap data={DATA} runs={[scout]} now={NOW} />);

    expect(screen.queryByTestId(/orchestration-causal-port-/)).toBeNull();
  });

  it("draws nothing for a run with no parent at all (a directly-triggered single run)", () => {
    const solo = run({ id: "solo-1", agentName: "matcher" });
    render(<OrchestrationMap data={DATA} runs={[solo]} now={NOW} />);
    expect(screen.queryByTestId(/orchestration-causal-port-/)).toBeNull();
  });
});
