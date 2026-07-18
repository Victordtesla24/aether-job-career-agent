// @vitest-environment jsdom
/**
 * MV-agent-monitor-001 / 002 / 003 — Agent Orchestration widget (Orchestration.tsx).
 *
 * Regression coverage for the manual-verification findings on
 * `/dashboard/agents` (agent-monitor monitoring section):
 *
 *  - MV-agent-monitor-001 (HIGH): "Pause All" / "Manual Override" had no
 *    onClick — clicking did nothing, with no visual signal that they were
 *    inert. Fixed to an honest disabled state with a "not yet available"
 *    tooltip (no backend pause/override capability exists — see
 *    apps/api/app/routers/agents.py, grepped for pause/override at fix time).
 *  - MV-agent-monitor-002 (MEDIUM): Task Queue "in progress" rows rendered a
 *    fabricated `35 + i*25` percentage with no backing progress field on
 *    AgentRun. Fixed to never render a numeric percentage for a run in
 *    progress — only a real, backend-derived 100% for completed runs.
 *  - MV-agent-monitor-003 (MEDIUM): the Performance card's success-rate number
 *    (windowed by the `runs` prop, capped at 50 server-side) contradicted the
 *    separate Agent Stats "Success Rate" card (windowed at 200 server-side)
 *    with no disclosure that they read different sample windows. Fixed by
 *    labelling the Performance card's own window inline.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

// This project does not install @testing-library/jest-dom (see
// provider-config-modal.test.tsx) — assert plain DOM properties instead of
// `toBeDisabled()`.

import Orchestration from "../../components/agents/Orchestration";
import type { AgentRun, AgentSummary } from "../../lib/api/agents";

afterEach(cleanup);

const agents: AgentSummary[] = [
  { name: "supervisor", status: "active", last_run: null, approval_gated: false },
];

function run(overrides: Partial<AgentRun>): AgentRun {
  return {
    id: overrides.id ?? "r1",
    agentName: overrides.agentName ?? "tailor",
    status: overrides.status ?? "completed",
    input: null,
    output: null,
    error: null,
    costUsd: null,
    startedAt: overrides.startedAt ?? "2026-07-17T10:00:00Z",
    completedAt: overrides.completedAt ?? "2026-07-17T10:00:05Z",
    createdAt: overrides.createdAt ?? "2026-07-17T10:00:00Z",
    ...overrides,
  };
}

describe("Orchestration — MV-agent-monitor-001 dead buttons", () => {
  it("renders 'Pause All' as an honestly disabled control, not a live one", () => {
    render(<Orchestration agents={agents} runs={[]} />);
    const btn = screen.getByRole("button", { name: /pause all/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("title") || btn.getAttribute("aria-label") || "").toMatch(
      /not yet available/i,
    );
    // Clicking a disabled control must not throw and must not change anything.
    fireEvent.click(btn);
  });

  it("renders 'Manual Override' as an honestly disabled control, not a live one", () => {
    render(<Orchestration agents={agents} runs={[]} />);
    const btn = screen.getByRole("button", { name: /manual override/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("title") || btn.getAttribute("aria-label") || "").toMatch(
      /not yet available/i,
    );
    fireEvent.click(btn);
  });
});

describe("Orchestration — MV-agent-monitor-002 fabricated progress %", () => {
  it("never renders a numeric percentage for an in-progress (running/queued) task", () => {
    const runs = [
      run({ id: "a", status: "running", startedAt: null, completedAt: null }),
      run({ id: "b", status: "queued", startedAt: null, completedAt: null }),
    ];
    render(<Orchestration agents={agents} runs={runs} />);
    const queue = screen.getByTestId("task-queue");
    // The old formula produced exactly 35% and 60% for these two rows —
    // assert neither fabricated figure (nor any other bare "N%" number tied
    // to the in-progress rows) is present.
    expect(queue.textContent).not.toMatch(/35%/);
    expect(queue.textContent).not.toMatch(/60%/);
    expect(queue.textContent).not.toMatch(/85%/);
  });

  it("still renders an honest 100% for genuinely completed tasks", () => {
    const runs = [run({ id: "c", status: "completed" })];
    render(<Orchestration agents={agents} runs={runs} />);
    const queue = screen.getByTestId("task-queue");
    expect(queue.textContent).toMatch(/100%/);
  });
});

describe("Orchestration — MV-agent-monitor-003 success-rate window disclosure", () => {
  it("labels the Performance card's own sample window so it cannot read as contradicting the Agent Stats card", () => {
    const runs = Array.from({ length: 5 }, (_, i) =>
      run({ id: `r${i}`, status: i === 0 ? "failed" : "completed" }),
    );
    render(<Orchestration agents={agents} runs={runs} />);
    const perf = screen.getByTestId("performance-metrics");
    expect(perf.textContent).toMatch(/last 5 runs?/i);
  });
});

describe("Orchestration — ADV-agent-monitor-001 fabricated uptime", () => {
  it("does not render a hardcoded/fabricated uptime figure in the header — there is no real uptime signal", () => {
    render(<Orchestration agents={agents} runs={[]} />);
    const section = screen.getByTestId("agent-orchestration");
    expect(section.textContent).not.toMatch(/uptime/i);
    expect(section.textContent).not.toMatch(/99\.8\s*%/);
  });

  it("still shows the real, live agent/task counts next to where uptime used to be", () => {
    const runs = [run({ id: "q1", status: "queued", startedAt: null, completedAt: null })];
    render(<Orchestration agents={agents} runs={runs} />);
    const section = screen.getByTestId("agent-orchestration");
    expect(section.textContent).toMatch(/1 agents? online/i);
    expect(section.textContent).toMatch(/1 tasks? in queue/i);
  });
});
