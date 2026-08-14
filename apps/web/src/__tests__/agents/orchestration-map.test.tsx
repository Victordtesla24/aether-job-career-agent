// @vitest-environment jsdom
/**
 * U-AX build spec item 5 — the Agent Orchestration section's workflow map(s).
 *
 * U-PLAN.md U-AX BUILD SPEC ADDITIONS item 5 (binding): "the Agents page's
 * orchestration section presents ALL 22 agents in one DEFINED end-to-end
 * workflow map ... each agent showing: its role/stage in the workflow, real
 * vs planned status (HONEST — planned agents render as labeled roadmap
 * stages, never fake execution) ..."
 *
 * ARCHITECTURAL FREEDOM: one or multiple maps allowed. This test supplies
 * TWO maps (mirroring the plan's own example decomposition — "a primary
 * application-pipeline map + a learning-loop map") to prove the component
 * handles the multi-map shape, and asserts the END RESULT (every agent
 * accounted for, honest status rendering) rather than a specific map count.
 *
 * Component does not exist on `main` yet —
 * `../../components/agents/OrchestrationMap` (test-author-chosen path,
 * DISTINCT from the existing `components/agents/Orchestration` task-queue
 * widget covered by `orchestration.test.tsx` — that widget is Pause
 * All/Manual Override/Task Queue/Performance, not a workflow graph).
 * Written BEFORE implementation.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import OrchestrationMap from "../../components/agents/OrchestrationMap";
import type { OrchestrationMapData } from "../../lib/api/agentPolicy";

afterEach(cleanup);

function realAgent(key: string) {
  return {
    agentKey: key,
    name: key,
    backend: key,
    status: "real" as const,
    metricsConsumed: ["conversionRate"],
    thresholds: ["conversion>=20%"],
    lastRunPolicyTier: null,
    trend: null,
  };
}

function plannedAgent(key: string) {
  return {
    agentKey: key,
    name: key,
    backend: null,
    status: "planned" as const,
    metricsConsumed: [],
    thresholds: [],
    lastRunPolicyTier: null,
    trend: null,
  };
}

const TWENTY_TWO_KEYS = Array.from({ length: 22 }, (_, i) => `agent${i + 1}`);

function buildData(): OrchestrationMapData {
  const [real, planned] = [
    TWENTY_TWO_KEYS.slice(0, 20),
    TWENTY_TWO_KEYS.slice(20),
  ];
  return {
    maps: [
      {
        key: "application-pipeline",
        name: "Application Pipeline",
        stages: [
          { stage: "discovery", agents: [realAgent(real[0])] },
          { stage: "fit-scoring", agents: [realAgent(real[1])] },
          { stage: "tailoring", agents: [realAgent(real[2])] },
          { stage: "cover-letter", agents: [realAgent(real[3])] },
          { stage: "quality-gates", agents: real.slice(4, 8).map((k) => realAgent(k)) },
          { stage: "submission", agents: real.slice(8, 12).map((k) => realAgent(k)) },
          { stage: "tracking", agents: real.slice(12, 16).map((k) => realAgent(k)) },
        ],
      },
      {
        key: "learning-loop",
        name: "Learning Loop",
        stages: [
          {
            stage: "learning-loop",
            agents: [
              ...real.slice(16, 20).map((k) => realAgent(k)),
              ...planned.map((k) => plannedAgent(k)),
            ],
          },
        ],
      },
    ],
  };
}

describe("OrchestrationMap — all agents, honest real/planned statuses", () => {
  it("renders every agent across every map", () => {
    render(<OrchestrationMap data={buildData()} />);
    for (const key of TWENTY_TWO_KEYS) {
      expect(screen.getByTestId(`orchestration-agent-${key}`)).toBeTruthy();
    }
  });

  it("never renders a 'planned' agent with a live/active/running indicator", () => {
    render(<OrchestrationMap data={buildData()} />);
    for (const key of TWENTY_TWO_KEYS.slice(20)) {
      const node = screen.getByTestId(`orchestration-agent-${key}`);
      expect(node.textContent).toMatch(/planned|roadmap/i);
      expect(node.textContent).not.toMatch(/\bactive\b|\brunning\b|\blive\b/i);
    }
  });

  it("labels real agents distinctly from planned ones", () => {
    render(<OrchestrationMap data={buildData()} />);
    const realNode = screen.getByTestId(`orchestration-agent-${TWENTY_TWO_KEYS[0]}`);
    expect(realNode.textContent).not.toMatch(/planned|roadmap/i);
  });

  it("groups agents under their assigned stage", () => {
    render(<OrchestrationMap data={buildData()} />);
    expect(screen.getByTestId("orchestration-stage-discovery")).toBeTruthy();
    expect(screen.getByTestId("orchestration-stage-tailoring")).toBeTruthy();
  });
});
