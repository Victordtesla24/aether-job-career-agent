/**
 * AUD-COV-2 — the autopilot's low-fit skip is honest wherever the UI reads it.
 *
 * The board-sweep autopilot refuses to auto-generate a "direct match" cover
 * letter for a job below the user's own `agentConfig.matchThreshold` (or an
 * unscored one) and records that refusal as a zero-cost `boardSweep` AgentRun
 * with `output.skipped = true`, status `completed` — nothing failed, so a red
 * row would be dishonest.
 *
 * `completed` is exactly why these helpers must exist: without them the skip
 * counts as work produced (`runProducedOutput`) and paints a green "completed"
 * in the runs table, which is indistinguishable from a sweep that really
 * generated something. Same shape of fix, and same reasoning, as the
 * pre-existing `coverLetterDegraded` treatment.
 */
import { describe, expect, it } from "vitest";

import {
  autopilotSkipMessage,
  autopilotSkipped,
  coverLetterDegraded,
  runProducedOutput,
} from "../../lib/agent-run-health";
import type { AgentRun } from "../../lib/api/agents";

const SKIP_MESSAGE =
  "No cover letter was auto-generated for this role: it scored 12 against your " +
  "profile, below your match threshold of 50. Adjust your match threshold, or " +
  "generate one yourself from the Cover Letter studio.";

function run(overrides: Partial<AgentRun>): AgentRun {
  return {
    id: "r1",
    agentName: "boardSweep",
    status: "completed",
    input: {},
    output: {},
    error: null,
    costUsd: 0,
    startedAt: "2026-08-17T00:00:00Z",
    completedAt: "2026-08-17T00:00:00Z",
    createdAt: "2026-08-17T00:00:00Z",
    ...overrides,
  };
}

const skipRun = run({
  output: {
    skipped: true,
    reason: "below_match_threshold",
    fitScore: 12,
    matchThreshold: 50,
    message: SKIP_MESSAGE,
  },
});

describe("autopilotSkipped", () => {
  it("recognizes the recorded low-fit skip", () => {
    expect(autopilotSkipped(skipRun)).toBe(true);
  });

  it("is scoped to boardSweep runs", () => {
    expect(
      autopilotSkipped(run({ agentName: "coverLetter", output: { skipped: true } })),
    ).toBe(false);
  });

  it("requires an explicit boolean true, never a truthy value", () => {
    expect(autopilotSkipped(run({ output: { skipped: "yes" } }))).toBe(false);
    expect(autopilotSkipped(run({ output: {} }))).toBe(false);
  });

  it("does not misread a genuine sweep stop as a skip", () => {
    // The spend-cap stop records `stopped`, not `skipped`.
    expect(
      autopilotSkipped(
        run({ status: "failed", output: { stopped: true, reason: "spend_cap_exceeded" } }),
      ),
    ).toBe(false);
  });
});

describe("autopilotSkipMessage", () => {
  it("quotes the backend's own sentence verbatim", () => {
    expect(autopilotSkipMessage(skipRun)).toBe(SKIP_MESSAGE);
  });

  it("is empty for a non-skip run, and for a skip with no message", () => {
    expect(autopilotSkipMessage(run({ agentName: "scout" }))).toBe("");
    expect(autopilotSkipMessage(run({ output: { skipped: true } }))).toBe("");
  });
});

describe("runProducedOutput", () => {
  it("does not count a low-fit skip as work produced", () => {
    expect(runProducedOutput(skipRun)).toBe(false);
  });

  it("still counts a real completed run, and still excludes the cover degrade", () => {
    const real = run({ agentName: "tailor", output: { changes: 4 } });
    const degraded = run({
      agentName: "coverLetter",
      output: { coverLetterUnavailable: true, cover_letter_id: null },
    });
    expect(runProducedOutput(real)).toBe(true);
    expect(coverLetterDegraded(degraded)).toBe(true);
    expect(runProducedOutput(degraded)).toBe(false);
  });
});
