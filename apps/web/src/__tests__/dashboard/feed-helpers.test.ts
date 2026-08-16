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
    // CLI-D3 refix (audit wf_9a87f76f-eaa, adversarial attack-1): "Submitted"
    // now requires output PROVING a transmission (submissionState =
    // "transmitted", the one state backed by Application."transmittedAt" —
    // apps/api/app/agents/submission_agent.py). A bare completed submission
    // run no longer earns it; the state-specific pins live in the
    // "submission-run honesty" block below. This is a legitimate contract
    // update, not a weakening: the old pin asserted a green "Submitted" chip
    // for runs the agent's own catalog says transmit nothing.
    expect(
      runBadge(run({ agentName: "submission", output: { submissionState: "transmitted", transmitted: true } }))
        .label,
    ).toBe("Submitted");
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

/**
 * CLI-D3 refix (audit wf_9a87f76f-eaa, adversarial attack-1 — MUST-FIX 1).
 *
 * The Submission Agent "transmits NOTHING itself: a run ends as a pending
 * card in Approvals" (apps/api/app/routers/agents.py) — its run output
 * carries the honest terminal state (apps/api/app/agents/submission_agent.py:
 * submissionState = transmitted | awaiting_approval | manual_step_required |
 * recorded_not_transmitted | no_change | none). Before this fix the feed
 * stamped a green "Submitted" chip and said "submitted an application" for
 * EVERY completed submission run. These pins make the badge and sentence a
 * function of the run's own evidence: only output proving a transmission may
 * render "Submitted".
 */
describe("submission-run honesty (CLI-D3 refix, wf_9a87f76f-eaa attack-1)", () => {
  const sub = (output: Record<string, unknown>) =>
    run({ agentName: "submission", status: "completed", output });

  it("an awaiting_approval submission run NEVER renders 'Submitted' — it reads as queued for approval, nothing sent", () => {
    const r = sub({
      submissionState: "awaiting_approval",
      transmitted: false,
      approvalId: "ap_1",
      message: "Recorded in your tracker and queued for sending — NOT transmitted yet.",
    });
    const badge = runBadge(r);
    expect(badge.label).not.toBe("Submitted");
    expect(badge.label).toBe("Needs approval");
    // Not the success green either — a queued card is not a sent application.
    expect(badge.cls).not.toContain("aether-green");
    const d = describeRun(r);
    expect(d.text).not.toContain("submitted an application");
    expect(d.text).toMatch(/approval/i);
    expect(d.text).toMatch(/nothing sent|not (yet )?sent|nothing has been sent/i);
  });

  it("only transmission-proving output renders 'Submitted' / 'submitted an application'", () => {
    const r = sub({
      submissionState: "transmitted",
      transmitted: true,
      transmissionRef: "msg-abc",
    });
    expect(runBadge(r).label).toBe("Submitted");
    expect(describeRun(r).text).toBe("submitted an application");
  });

  it("manual_step_required reads as its honest state, never 'Submitted'", () => {
    const r = sub({
      submissionState: "manual_step_required",
      transmitted: false,
      message: "Seek requires you to apply on their site.",
    });
    const badge = runBadge(r);
    expect(badge.label).not.toBe("Submitted");
    expect(badge.label).toBe("Manual step");
    const d = describeRun(r);
    expect(d.text).not.toContain("submitted an application");
    expect(d.text).toMatch(/step|needs you/i);
  });

  it("no_change / none read as no-op checks, never 'Submitted'", () => {
    for (const state of ["no_change", "none"]) {
      const r = sub({ submissionState: state, transmitted: false });
      expect(runBadge(r).label).not.toBe("Submitted");
      expect(runBadge(r).label).toBe("No change");
      expect(describeRun(r).text).not.toContain("submitted an application");
    }
  });

  it("recorded_not_transmitted says recorded-not-sent, never 'Submitted'", () => {
    const r = sub({ submissionState: "recorded_not_transmitted", transmitted: false });
    expect(runBadge(r).label).not.toBe("Submitted");
    const d = describeRun(r);
    expect(d.text).not.toContain("submitted an application");
    expect(d.text).toMatch(/not sent/i);
  });

  it("a completed submission run with NO state evidence (legacy/empty output) never claims a submission", () => {
    for (const output of [{}, { submitted: true }]) {
      const r = sub(output);
      const badge = runBadge(r);
      expect(badge.label).not.toBe("Submitted");
      expect(badge.cls).not.toContain("aether-green");
      expect(describeRun(r).text).not.toContain("submitted an application");
    }
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
