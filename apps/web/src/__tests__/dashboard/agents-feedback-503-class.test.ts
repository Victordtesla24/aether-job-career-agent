/**
 * CRITICAL-3b — the 503 banner must tell the truth about WHY the run stopped.
 *
 * The API picks the 503 body by upstream failure CLASS
 * (`app/services/llm_client.py::llm_failure_user_message`):
 *
 *   402 out of credits -> "The AI provider rejected the request because the
 *                          account is out of credits ... retrying now will not
 *                          help."   (an OPERATOR problem, not the user's plan)
 *   401 bad key        -> "... rejected the configured credential ..."
 *   429/5xx/timeout    -> "The AI service is temporarily unavailable. Please
 *                          try again in a moment."
 *
 * `runErrorNotice` discarded all three and rendered one hardcoded line —
 * "the AI model is busy or its time budget was exceeded. Wait a minute and
 * press the button again" — so a user whose runs were dead because OUR
 * provider was out of credit was told to keep pressing the button, and an
 * operator failure read as routine flakiness on the Agents screen.
 */
import { describe, expect, it } from "vitest";

import { runErrorNotice } from "../../lib/agents-feedback";

/** An ApiError-shaped error exactly as `apiRequest` builds it. */
function apiError(status: number, detail: string) {
  return Object.assign(
    new Error(
      `POST /agents/tailor/run failed (${status}): ${JSON.stringify({ detail })}`,
    ),
    { status },
  );
}

const OUT_OF_CREDITS =
  "The AI provider rejected the request because the account is out of credits. " +
  "Automated runs are paused until the balance is topped up — retrying now will not help.";

const AUTH_FAILED =
  "The AI provider rejected the configured credential (authentication failed). " +
  "Automated runs are paused until the API key is corrected in Agent Settings — " +
  "retrying now will not help.";

const TRANSIENT = "The AI service is temporarily unavailable. Please try again in a moment.";

describe("runErrorNotice — 503 failure classes", () => {
  it("surfaces an upstream out-of-credit refusal instead of 'press the button again'", () => {
    const n = runErrorNotice(apiError(503, OUT_OF_CREDITS), "Tailor");
    expect(n.kind).toBe("error");
    expect(n.text).toContain("out of credits");
    expect(n.text).toContain("retrying now will not help");
    // The old copy invited exactly the retry the backend just said is futile.
    expect(n.text).not.toContain("press the button again");
    expect(n.text).not.toContain("time budget was exceeded");
    // An operator credit failure is not a plan problem — no upgrade CTA.
    expect(n.href).toBeUndefined();
  });

  it("surfaces a rejected API key as the credential problem it is", () => {
    const n = runErrorNotice(apiError(503, AUTH_FAILED), "Tailor");
    expect(n.text).toContain("authentication failed");
    expect(n.text).toContain("Agent Settings");
    expect(n.text).not.toContain("press the button again");
  });

  it("still tells the user to retry a genuinely transient failure", () => {
    const n = runErrorNotice(apiError(503, TRANSIENT), "Pipeline");
    expect(n.text).toContain("temporarily unavailable");
    expect(n.text).toContain("try again");
  });

  it("keeps the original guidance when the 503 carries no backend detail", () => {
    // Gateway/proxy 503s and client-synthesized errors have no JSON body —
    // the pre-existing copy must be preserved, not replaced by a guess.
    const n = runErrorNotice({ status: 503 }, "Pipeline");
    expect(n.text).toContain("time budget was exceeded");
    expect(n.text).toContain("press the button again");
  });
});
