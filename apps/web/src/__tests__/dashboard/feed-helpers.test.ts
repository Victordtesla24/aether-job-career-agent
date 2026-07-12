/**
 * AGT-DASH — unit coverage for the Agent Activity feed helpers (wireframe
 * agent-feed-s1t2u3): badge mapping, run descriptions enriched from output,
 * icon tiles and relative timestamps.
 */
import { describe, expect, it } from "vitest";

import {
  agentDisplayName,
  agentTile,
  describeRun,
  relTime,
  runBadge,
} from "../../components/dashboard/feed";
import type { AgentRun } from "../../lib/api/agents";

function run(overrides: Partial<AgentRun>): AgentRun {
  return {
    id: "r1",
    agentName: "scout",
    status: "completed",
    input: {},
    output: {},
    error: null,
    costUsd: null,
    startedAt: "2026-07-10T00:00:00Z",
    completedAt: "2026-07-10T00:01:00Z",
    createdAt: "2026-07-10T00:00:00Z",
    ...overrides,
  };
}

describe("runBadge", () => {
  it("maps wireframe badges per agent and status", () => {
    expect(runBadge(run({ agentName: "scout" })).label).toBe("Discovered");
    expect(runBadge(run({ agentName: "tailor" })).label).toBe("Tailored");
    expect(runBadge(run({ agentName: "submission" })).label).toBe("Submitted");
    expect(runBadge(run({ agentName: "coverLetter" })).label).toBe("Drafted");
    expect(runBadge(run({ agentName: "supervisor" })).label).toBe("Completed");
    expect(runBadge(run({ status: "running" })).label).toBe("Waiting");
    expect(runBadge(run({ status: "queued" })).label).toBe("Waiting");
    expect(runBadge(run({ status: "failed" })).label).toBe("Failed");
  });
});

describe("describeRun", () => {
  it("enriches matcher runs with job, company and fit score", () => {
    const d = describeRun(
      run({
        agentName: "matcher",
        output: { top_job_title: "Senior ML Engineer", top_company: "Canva", top_fit_score: 94.4 },
      }),
    );
    expect(d.highlight).toBe("Senior ML Engineer at Canva");
    expect(d.metric).toBe("match 94%");
  });

  it("reports scout discoveries and singular/plural correctly", () => {
    expect(describeRun(run({ agentName: "scout", output: { persisted: 6 } })).text).toContain(
      "6 new roles",
    );
    expect(describeRun(run({ agentName: "scout", output: { persisted: 1 } })).text).toContain(
      "1 new role",
    );
  });

  it("describes zero-insert scout runs as a check, not a discovery", () => {
    const d = describeRun(run({ agentName: "scout", output: { persisted: 0, updated: 5 } }));
    expect(d.text).toBe("checked job boards — no new roles");
    expect(d.metric).toBe("5 refreshed");
    const none = describeRun(run({ agentName: "scout", output: { persisted: 0, updated: 0 } }));
    expect(none.metric).toBeNull();
  });

  it("flags cover letters awaiting approval", () => {
    const d = describeRun(
      run({ agentName: "coverLetter", output: { approval_status: "pending" } }),
    );
    expect(d.text).toContain("awaiting your approval");
    expect(d.metric).toBe("needs approval");
  });

  it("handles failed and in-flight runs without fabricating detail", () => {
    expect(describeRun(run({ status: "failed", error: "boom" })).text).toBe("run failed");
    expect(describeRun(run({ status: "running" })).metric).toBe("in progress");
  });
});

describe("tiles and names", () => {
  it("gives every known agent a distinct tile and display name", () => {
    expect(agentDisplayName("scout")).toBe("Scout Agent");
    expect(agentDisplayName("coverLetter")).toBe("Cover Letter Agent");
    expect(agentTile("tailor").icon).toBe("fa-file-pen");
    expect(agentTile("unknown-agent").icon).toBe("fa-robot");
  });
});

describe("relTime", () => {
  const now = new Date("2026-07-10T12:00:00Z");
  it("formats minutes, hours, days and edge cases", () => {
    expect(relTime("2026-07-10T11:58:30Z", now)).toBe("1 min ago");
    expect(relTime("2026-07-10T11:59:40Z", now)).toBe("just now");
    expect(relTime("2026-07-10T09:00:00Z", now)).toBe("3 hr ago");
    expect(relTime("2026-07-08T09:00:00Z", now)).toBe("2 d ago");
    expect(relTime(null, now)).toBe("queued");
    expect(relTime("not-a-date", now)).toBe("queued");
  });
});
