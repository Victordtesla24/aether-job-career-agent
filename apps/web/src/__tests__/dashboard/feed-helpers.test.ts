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

/**
 * An in-flight run that is genuinely in flight.
 *
 * CRITICAL-2: "Waiting" / "in progress" are claims about the PRESENT, so the
 * feed helpers now only make them while a run could still plausibly be alive
 * (`lib/agent-run-health`). The fixed 2026-07-10 timestamps above describe a
 * run whose worker died long ago — correct for the terminal statuses they were
 * written for, but not for `running`/`queued`, which need a fresh anchor to
 * mean what these assertions intend. The stalled counterpart is asserted
 * explicitly below rather than left implicit in a stale fixture.
 */
function liveRun(overrides: Partial<AgentRun>): AgentRun {
  const now = new Date().toISOString();
  return run({ startedAt: now, createdAt: now, completedAt: null, ...overrides });
}

describe("runBadge", () => {
  it("maps wireframe badges per agent and status", () => {
    expect(runBadge(run({ agentName: "scout" })).label).toBe("Discovered");
    expect(runBadge(run({ agentName: "tailor" })).label).toBe("Tailored");
    expect(runBadge(run({ agentName: "submission" })).label).toBe("Submitted");
    expect(runBadge(run({ agentName: "coverLetter" })).label).toBe("Drafted");
    expect(runBadge(run({ agentName: "supervisor" })).label).toBe("Completed");
    expect(runBadge(liveRun({ status: "running" })).label).toBe("Waiting");
    expect(runBadge(liveRun({ status: "queued" })).label).toBe("Waiting");
    expect(runBadge(run({ status: "failed" })).label).toBe("Failed");
  });

  it("CRITICAL-2: an in-flight run whose worker is long gone is 'Stalled', never 'Waiting'", () => {
    // Nothing is waiting on a run that last moved eight days ago.
    const dead = new Date(Date.now() - 8 * 86_400_000).toISOString();
    expect(
      runBadge(run({ status: "running", startedAt: dead, createdAt: dead, completedAt: null }))
        .label,
    ).toBe("Stalled");
    expect(
      runBadge(run({ status: "queued", startedAt: null, createdAt: dead, completedAt: null }))
        .label,
    ).toBe("Stalled");
  });

  it("QA-RES-F: never shows the success 'Drafted' badge for a degraded coverLetter run", () => {
    const degraded = runBadge(
      run({
        agentName: "coverLetter",
        status: "completed",
        output: {
          coverLetterUnavailable: true,
          cover_letter_id: null,
          message: "The cover letter couldn't be generated because the writing model was temporarily unavailable.",
        },
      }),
    );
    expect(degraded.label).not.toBe("Drafted");
    expect(degraded.cls).not.toContain("aether-amber");
  });

  it("QA-RES-F: a genuinely drafted coverLetter run is unaffected", () => {
    const drafted = runBadge(
      run({
        agentName: "coverLetter",
        status: "completed",
        output: { cover_letter_id: "cl_123", approval_status: "approved" },
      }),
    );
    expect(drafted.label).toBe("Drafted");
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

  it("QA-RES-F: never claims a drafted cover letter for a completed-but-degraded run", () => {
    const d = describeRun(
      run({
        agentName: "coverLetter",
        status: "completed",
        output: {
          coverLetterUnavailable: true,
          cover_letter_id: null,
          tokensOut: 0,
          costUsd: 0,
          message: "The cover letter couldn't be generated because the writing model was temporarily unavailable.",
        },
      }),
    );
    expect(d.text).not.toContain("drafted a cover letter");
    expect(d.text).toBe("cover letter unavailable (generation degraded)");
  });

  it("QA-RES-F: a genuinely drafted cover letter is described unchanged", () => {
    const d = describeRun(
      run({
        agentName: "coverLetter",
        status: "completed",
        output: { cover_letter_id: "cl_123", approval_status: "approved" },
      }),
    );
    expect(d.text).toBe("drafted a cover letter");
  });

  it("handles failed and in-flight runs without fabricating detail", () => {
    expect(describeRun(run({ status: "failed", error: "boom" })).text).toBe("run failed");
    expect(describeRun(liveRun({ status: "running" })).metric).toBe("in progress");
  });

  it("CRITICAL-2: describes a long-dead in-flight run as stalled, never 'in progress'", () => {
    const dead = new Date(Date.now() - 8 * 86_400_000).toISOString();
    const d = describeRun(
      run({ status: "running", startedAt: dead, createdAt: dead, completedAt: null }),
    );
    expect(d.metric).toBe("stalled");
    expect(d.text).toMatch(/stalled — no progress for 8 days/);
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
