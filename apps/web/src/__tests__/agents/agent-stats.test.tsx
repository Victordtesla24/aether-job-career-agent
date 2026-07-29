// @vitest-environment jsdom
/**
 * QA3-F-03 (MED, W-21) — the Agent Stats "Success Rate" card
 * (AgentStats.tsx, backed by GET /agents/stats) must disclose when its
 * success-rate figure has degraded (letterless) coverLetter runs excluded
 * from the numerator, mirroring the honest disclosure convention Orchestration's
 * Performance card already uses ("last N runs").
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import AgentStatsRow from "../../components/agents/AgentStats";
import type { AgentStats } from "../../components/agents/api";

afterEach(cleanup);

function stats(overrides: Partial<AgentStats> = {}): AgentStats {
  return {
    spendUsd: 1.23,
    avgCostPerRun: 0.01,
    providerCount: 7,
    tokensTotal: 1000,
    tokensIn: 400,
    tokensOut: 600,
    mostActiveAgent: { name: "Cover Letter", tasks: 4 },
    successRate: 75.0,
    taskCount: 4,
    ...overrides,
  };
}

describe("AgentStatsRow — QA3-F-03 degraded-run disclosure", () => {
  it("shows the degraded count next to the sample-window caption when present", () => {
    render(<AgentStatsRow stats={stats({ degradedCount: 1 })} loading={false} />);
    const card = screen.getByTestId("stat-success");
    expect(card.textContent).toMatch(/1 degraded/i);
  });

  it("does not mention 'degraded' when there are none", () => {
    render(<AgentStatsRow stats={stats({ degradedCount: 0 })} loading={false} />);
    const card = screen.getByTestId("stat-success");
    expect(card.textContent).not.toMatch(/degraded/i);
  });

  it("degrades gracefully (no crash, no 'degraded' text) when the field is absent (legacy response)", () => {
    const legacy = stats();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (legacy as any).degradedCount;
    render(<AgentStatsRow stats={legacy} loading={false} />);
    const card = screen.getByTestId("stat-success");
    expect(card.textContent).not.toMatch(/degraded/i);
  });
});
