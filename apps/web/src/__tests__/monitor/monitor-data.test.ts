/**
 * Unit tests for the Agent Monitor data-mapping layer (AGT-MONITOR).
 * Guarantees every panel value derives from real run/agent data, not fixtures.
 */
import { describe, expect, it } from "vitest";

import type { AgentRun, AgentSummary } from "../../lib/api/agents";
import {
  WORKFLOW_NODES,
  anyRunning,
  deriveErrorLog,
  deriveHeaderStats,
  derivePerformance,
  deriveTaskQueue,
  mapAgentsToNodes,
} from "../../components/monitor/data";

function agent(name: string, status: string): AgentSummary {
  return { name, status, last_run: null, approval_gated: false };
}

function run(partial: Partial<AgentRun> & Pick<AgentRun, "id" | "agentName" | "status">): AgentRun {
  return { createdAt: "2026-07-10T10:00:00Z", ...partial };
}

describe("mapAgentsToNodes", () => {
  it("maps a running backing agent to an active/coral pulsing node", () => {
    const nodes = mapAgentsToNodes([agent("scout", "running")]);
    const discovery = nodes.find((n) => n.id === "discovery")!;
    expect(discovery.status).toBe("active");
    expect(discovery.tone).toBe("coral");
    expect(discovery.pulse).toBe(true);
  });

  it("labels a completed memory (supervisor) node as synced", () => {
    const nodes = mapAgentsToNodes([agent("supervisor", "completed")]);
    expect(nodes.find((n) => n.id === "memory")!.status).toBe("synced");
  });

  it("defaults unknown/absent agents to idle", () => {
    const nodes = mapAgentsToNodes([]);
    expect(nodes).toHaveLength(WORKFLOW_NODES.length);
    expect(nodes.every((n) => n.status === "idle" && n.tone === "dim")).toBe(true);
  });

  it("picks the dominant (most active) status among multi-agent nodes", () => {
    const nodes = mapAgentsToNodes([agent("fitScorer", "completed"), agent("matcher", "running")]);
    expect(nodes.find((n) => n.id === "evaluator")!.tone).toBe("coral");
  });
});

describe("deriveHeaderStats", () => {
  it("counts in-flight runs and reports real success rate", () => {
    const agents = [agent("scout", "running"), agent("tailor", "idle")];
    const runs = [
      run({ id: "1", agentName: "scout", status: "running" }),
      run({ id: "2", agentName: "tailor", status: "completed" }),
      run({ id: "3", agentName: "coverLetter", status: "failed" }),
    ];
    const stats = deriveHeaderStats(agents, runs);
    expect(stats.agentsOnline).toBe(2);
    expect(stats.tasksInQueue).toBe(1);
    expect(stats.successRate).toBe("50%");
  });
});

describe("deriveTaskQueue", () => {
  it("returns only running/queued runs, newest first", () => {
    const runs = [
      run({ id: "old", agentName: "scout", status: "running", createdAt: "2026-07-10T09:00:00Z" }),
      run({ id: "new", agentName: "tailor", status: "queued", createdAt: "2026-07-10T11:00:00Z" }),
      run({ id: "done", agentName: "matcher", status: "completed" }),
    ];
    const queue = deriveTaskQueue(runs);
    expect(queue.map((q) => q.id)).toEqual(["new", "old"]);
    expect(queue[0].label).toBe("Tailor");
  });
});

describe("derivePerformance", () => {
  it("computes tasks done, avg time from duration_ms, and success rate", () => {
    const runs = [
      run({ id: "1", agentName: "scout", status: "completed", output: { duration_ms: 2000 } }),
      run({ id: "2", agentName: "tailor", status: "completed", output: { duration_ms: 4000 } }),
      run({ id: "3", agentName: "coverLetter", status: "failed" }),
    ];
    const perf = derivePerformance(runs);
    expect(perf.tasksDone).toBe(2);
    expect(perf.avgTime).toBe("3.0s");
    expect(perf.successRate).toBe("66.7%");
  });

  it("falls back to startedAt/completedAt and shows ms under a second", () => {
    const perf = derivePerformance([
      run({
        id: "1",
        agentName: "scout",
        status: "completed",
        startedAt: "2026-07-10T10:00:00.000Z",
        completedAt: "2026-07-10T10:00:00.500Z",
      }),
    ]);
    expect(perf.avgTime).toBe("500ms");
  });

  it("reports em dash when there is no terminal data", () => {
    const perf = derivePerformance([run({ id: "1", agentName: "scout", status: "running" })]);
    expect(perf.successRate).toBe("—");
    expect(perf.avgTime).toBe("—");
  });
});

describe("deriveErrorLog", () => {
  it("classifies failed→ERR and completed→OK (incl. gated), newest first, ignoring in-flight runs", () => {
    const runs = [
      run({ id: "1", agentName: "scout", status: "completed", createdAt: "2026-07-10T08:00:00Z" }),
      run({ id: "2", agentName: "coverLetter", status: "failed", error: "boom", createdAt: "2026-07-10T10:00:00Z" }),
      run({
        id: "3",
        agentName: "tailor",
        status: "completed",
        output: { approvalRequired: true },
        createdAt: "2026-07-10T09:00:00Z",
      }),
      run({ id: "4", agentName: "matcher", status: "running", createdAt: "2026-07-10T11:00:00Z" }),
    ];
    const log = deriveErrorLog(runs);
    expect(log.map((e) => e.id)).toEqual(["2", "3", "1"]);
    expect(log.map((e) => e.level)).toEqual(["ERR", "OK", "OK"]);
    expect(log[0].message).toContain("boom");
  });

  it("respects the limit", () => {
    const runs = Array.from({ length: 20 }, (_, i) =>
      run({ id: String(i), agentName: "scout", status: "completed" }),
    );
    expect(deriveErrorLog(runs, 5)).toHaveLength(5);
  });
});

describe("anyRunning", () => {
  it("is true when a run is running or queued", () => {
    expect(anyRunning([run({ id: "1", agentName: "scout", status: "queued" })])).toBe(true);
    expect(anyRunning([run({ id: "1", agentName: "scout", status: "completed" })])).toBe(false);
  });
});
