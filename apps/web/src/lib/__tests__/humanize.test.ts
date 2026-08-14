/**
 * I4-FE-04 — characterisation tests for `humanize.ts`'s
 * `humanizeActivityMessage`, pinning the honesty invariant I4-FE-02 /
 * I4-FE-02b / I4-FE-02c require: rewriting engineering jargon into calm copy
 * must never (a) turn a terminally-failed/abandoned run into copy that
 * reads as paused/retrying, and (b) reduce a non-empty error to the empty
 * string.
 *
 * Inputs below are verbatim strings this module is fed in production:
 *   - `ABANDONED_ERROR_MARKER` / `_honest_error()` output
 *     (apps/api/app/services/agent_run_watchdog.py:195, 208-223)
 *   - the feed's literal "run failed" text
 *     (apps/web/src/components/dashboard/feed.ts:119)
 * matching uat/reports/evidence/market-perf/i4/i4-fe-humanize-honesty-probe.txt.
 *
 * Before the I4-FE-02 fix, every case in this file failed:
 *   - "run abandoned — no worker heartbeat" → "run paused"
 *   - the two `_honest_error()` sentences had "abandoned" replaced by
 *     "paused" and "no worker heartbeat" stripped to "", leaving a sentence
 *     whose opening clause contradicted the rest of the message
 *   - "OpenRouter run failed: ..." → "...Agent run paused — retrying: ..."
 *   - "run failed" → "Agent run paused — retrying"
 *   - "no worker heartbeat" alone → "" (renders identically to "no error")
 */
import { describe, expect, it } from "vitest";

import { humanizeActivityMessage } from "../humanize";

const ABANDONED_ERROR_MARKER = "run abandoned — no worker heartbeat";

const HONEST_ERROR_HEARTBEAT_KNOWN =
  "Run abandoned — no worker heartbeat for 12.3 minutes on this tailor run " +
  "(it had been marked running for 192.6 hours). The process that owned it " +
  "died or was restarted; no result was produced and no work is in " +
  "progress. Start the agent again to retry.";

const HONEST_ERROR_NO_HEARTBEAT_EVER =
  "Run abandoned — no worker heartbeat was ever recorded for this tailor " +
  "run and it exceeded the 900s wall-clock ceiling (it had been marked " +
  "running for 192.6 hours). The process that owned it died or was " +
  "restarted; no result was produced and no work is in progress. Start " +
  "the agent again to retry.";

describe("humanizeActivityMessage — truth-value preservation (I4-FE-02)", () => {
  it("never rewrites the abandoned-run marker into paused/retrying copy", () => {
    const out = humanizeActivityMessage(ABANDONED_ERROR_MARKER);
    expect(out).not.toMatch(/paused/i);
    expect(out).not.toMatch(/retrying/i);
    expect(out).toBe(ABANDONED_ERROR_MARKER);
  });

  it("preserves the full honest-error sentence verbatim (heartbeat known)", () => {
    const out = humanizeActivityMessage(HONEST_ERROR_HEARTBEAT_KNOWN);
    expect(out).toBe(HONEST_ERROR_HEARTBEAT_KNOWN);
    expect(out).not.toMatch(/paused/i);
  });

  it("preserves the full honest-error sentence verbatim (no heartbeat ever)", () => {
    const out = humanizeActivityMessage(HONEST_ERROR_NO_HEARTBEAT_EVER);
    expect(out).toBe(HONEST_ERROR_NO_HEARTBEAT_EVER);
    expect(out).not.toMatch(/paused/i);
  });

  it("does not claim a retry is under way for a permanent billing failure", () => {
    const input = "OpenRouter run failed: 402 insufficient credit — add credit to continue";
    const out = humanizeActivityMessage(input);
    expect(out).not.toMatch(/retrying/i);
    expect(out).not.toMatch(/paused/i);
    expect(out).toBe(input);
  });

  it('leaves the bare feed string "run failed" untouched', () => {
    expect(humanizeActivityMessage("run failed")).toBe("run failed");
  });

  it("never returns the empty string for a non-empty input (I4-FE-02b)", () => {
    // Would previously render as the SAME em-dash the agents-page run-error
    // column uses for "no error at all" (apps/web/src/app/dashboard/agents/
    // page.tsx: `{humanizeActivityMessage(run.error) || "—"}`).
    expect(humanizeActivityMessage("no worker heartbeat")).not.toBe("");
    expect(humanizeActivityMessage("worker heartbeat missing")).not.toBe("");
  });

  it("is stateless across repeated calls with the same input", () => {
    // Guards against the `/g`-flag lastIndex-carryover class of bug: every
    // call must produce the identical result, not an alternating one.
    for (let i = 0; i < 4; i++) {
      expect(humanizeActivityMessage("run failed")).toBe("run failed");
    }
  });

  it("still humanises the one legitimate retryable case", () => {
    // Unaffected by I4-FE-02: cover-letter generation degrading is a real,
    // graceful-degradation retry path (not a terminal failure), so this
    // rewrite is truthful and stays.
    expect(humanizeActivityMessage("cover letter unavailable (generation degraded)")).toBe(
      "Could not generate — will retry automatically",
    );
  });

  it("passes through null/undefined/empty input unchanged", () => {
    expect(humanizeActivityMessage(null)).toBe("");
    expect(humanizeActivityMessage(undefined)).toBe("");
    expect(humanizeActivityMessage("")).toBe("");
  });
});
