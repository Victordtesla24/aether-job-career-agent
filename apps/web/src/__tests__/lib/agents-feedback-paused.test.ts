/**
 * F5-010 (Fable 5 adversarial review): a 409 `agent_paused` refusal is the
 * user's OWN Stop-All / per-agent toggle at work — a deliberate,
 * pre-side-effect skip, not a failure. Before the fix, `runErrorNotice` had
 * no 409 branch, so the paused refusal fell through to the generic copy:
 *
 *   "sentimentAnalysis failed (POST /agents/sentimentAnalysis/run failed
 *    (409): {"detail":"agent_paused: sentimentAnalysis is stopped by the
 *    user's agent controls (Stop Al). Retry in a moment; ..."
 *
 * — three defects in one line: (1) a pause rendered as a FAILURE (kind
 * "error"), which also HALTED the OrchestrationMap batch runner ("Stopped at
 * Sentiment Analysis Agent — ..."); (2) "Retry in a moment" — advice that
 * cannot work until the user re-enables the agent; (3) the raw body
 * truncated mid-word at 140 chars ("(Stop Al"). These tests pin the fixed
 * behaviour for BOTH backend refusal shapes (see
 * apps/api/app/routers/agents.py): the plain-string detail from
 * `_dispatch`/`_enqueue_single_agent` and the coded dict from
 * `_execute_reserved_run`.
 */
import { describe, expect, it } from "vitest";

import { runErrorNotice } from "../../lib/agents-feedback";
import { ApiError } from "../../lib/api/client";

const STRING_SHAPE = new ApiError(
  'POST /agents/sentimentAnalysis/run failed (409): {"detail":"agent_paused: sentimentAnalysis is stopped by the user\'s agent controls (Stop All / per-agent toggle). Re-enable the agent on the Agents page to run it."}',
  409,
);

const DICT_SHAPE = new ApiError("POST /agents/tailor/run failed (409)", 409, undefined, {
  code: "agent_paused",
  message: "tailor is stopped by the user's agent controls.",
  agentKey: "tailor",
});

describe("F5-010: paused-agent 409 is an honest skip, never a failure", () => {
  it("renders the plain-string refusal shape as an info skip with re-enable guidance", () => {
    const notice = runErrorNotice(STRING_SHAPE, "sentimentAnalysis");

    // `info`, not `error` — the OrchestrationMap batch runner halts on
    // `outcome.kind === "error"`, and a user's own pause must not halt the
    // rest of the plan (board_sweep's honest-skip semantics).
    expect(notice.kind).toBe("info");
    expect(notice.text).toMatch(/skipped/i);
    expect(notice.text).toMatch(/stop all/i);
    expect(notice.text).toMatch(/re-enable/i);
    // The advice that was actively wrong must be gone.
    expect(notice.text).not.toMatch(/retry in a moment/i);
    expect(notice.text).not.toMatch(/RECENT RUNS/i);
    expect(notice.text).not.toMatch(/failed/i);
    // No truncated raw body leaking through.
    expect(notice.text).not.toContain('{"detail"');
  });

  it("renders the coded dict refusal shape the same way", () => {
    const notice = runErrorNotice(DICT_SHAPE, "tailor");

    expect(notice.kind).toBe("info");
    expect(notice.text).toMatch(/skipped/i);
    expect(notice.text).toMatch(/re-enable/i);
    expect(notice.text).not.toMatch(/retry in a moment/i);
  });

  it("surfaces a genuine non-paused 409 detail as a failure, without retry copy", () => {
    const notice = runErrorNotice(
      new ApiError(
        'POST /agents/scout/run failed (409): {"detail":"another run of scout is already in flight"}',
        409,
      ),
      "scout",
    );

    expect(notice.kind).toBe("error");
    expect(notice.text).toContain("another run of scout is already in flight");
    expect(notice.text).not.toMatch(/retry in a moment/i);
  });

  it("still degrades to the generic copy for a bare 409 with no backend detail", () => {
    const notice = runErrorNotice(new ApiError("POST /agents/scout/run failed (409)", 409), "scout");

    expect(notice.kind).toBe("error");
    expect(notice.text).toMatch(/retry in a moment/i);
  });
});
