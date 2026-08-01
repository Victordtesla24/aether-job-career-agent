/**
 * DROP-001 — the plan-quota 429 must prompt an upgrade or a wait, not tell the
 * user to retry.
 *
 * `routers/agents.py` raises a 429 whose detail documents itself as carrying
 * "an upgrade CTA (/pricing) and the period reset time so the UI can prompt an
 * upgrade or a wait". Two client-side layers dropped it:
 *
 *   1. ApiError flattened the response body into a message string, so the
 *      structured detail was unreachable;
 *   2. runErrorNotice had no 429 branch, so a quota wall fell through to the
 *      generic "Retry in a moment … check the RECENT RUNS table" copy — advice
 *      that is actively wrong for a quota (retrying cannot succeed).
 *
 * These tests are RED against that behaviour.
 */
import { describe, expect, it } from "vitest";

import { runErrorNotice } from "../../lib/agents-feedback";
import { ApiError, parseApiErrorDetail } from "../../lib/api/client";

function quotaError(detail: Record<string, unknown>): ApiError {
  return new ApiError("POST /agents/run failed (429)", 429, undefined, detail);
}

describe("DROP-001: the quota wall must be actionable", () => {
  it("surfaces the server's own message, reset time and upgrade CTA", () => {
    const notice = runErrorNotice(
      quotaError({
        code: "run_quota_exceeded",
        message: "You've used all 5 agent runs this period.",
        runsUsed: 5,
        runsAllowed: 5,
        quotaReset: "2026-09-01T00:00:00+00:00",
        upgradeUrl: "/pricing",
      }),
      "Pipeline",
    );

    expect(notice.kind).toBe("error");
    expect(notice.text).toContain("You've used all 5 agent runs this period.");
    // Must state WHEN runs resume — the whole point of quotaReset.
    expect(notice.text).toMatch(/runs resume/i);
    // Must offer the upgrade route the server pointed at.
    expect(notice.href).toBe("/pricing");
    expect(notice.hrefLabel).toMatch(/upgrade/i);
    // Must NOT give the generic retry advice — retrying cannot clear a quota.
    expect(notice.text).not.toMatch(/retry in a moment/i);
    expect(notice.text).not.toMatch(/RECENT RUNS/i);
  });

  it("labels a spend-cap block as a plan review, not an upgrade", () => {
    const notice = runErrorNotice(
      quotaError({
        code: "spend_cap_exceeded",
        message: "Your monthly spend cap has been reached.",
        quotaReset: "2026-09-01T00:00:00+00:00",
        upgradeUrl: "/pricing",
      }),
      "Pipeline",
    );

    expect(notice.text).toContain("Your monthly spend cap has been reached.");
    expect(notice.hrefLabel).toMatch(/review/i);
  });

  it("never invents a reset time the server did not send", () => {
    const notice = runErrorNotice(
      quotaError({
        code: "run_quota_exceeded",
        message: "You've reached your plan's run quota this period.",
        quotaReset: null,
        upgradeUrl: "/pricing",
      }),
      "Pipeline",
    );

    expect(notice.text).toContain("You've reached your plan's run quota this period.");
    // No reset instant was sent, so none may be asserted.
    expect(notice.text).not.toMatch(/runs resume/i);
    expect(notice.href).toBe("/pricing");
  });

  it("ignores an unparseable reset instant rather than rendering Invalid Date", () => {
    const notice = runErrorNotice(
      quotaError({ message: "Quota reached.", quotaReset: "not-a-date", upgradeUrl: "/pricing" }),
      "Pipeline",
    );

    expect(notice.text).not.toMatch(/invalid date/i);
    expect(notice.text).not.toMatch(/runs resume/i);
  });

  it("still degrades honestly when the server sends no structured detail", () => {
    const notice = runErrorNotice(new ApiError("POST /agents/run failed (429)", 429), "Pipeline");

    expect(notice.kind).toBe("error");
    // No fabricated reset time and no fabricated CTA.
    expect(notice.text).not.toMatch(/runs resume/i);
    expect(notice.href).toBeUndefined();
  });
});

describe("parseApiErrorDetail lifts only what the server actually sent", () => {
  it("extracts an object detail", () => {
    expect(parseApiErrorDetail('{"detail": {"code": "run_quota_exceeded"}}')).toEqual({
      code: "run_quota_exceeded",
    });
  });

  it("returns undefined for a plain-string detail", () => {
    expect(parseApiErrorDetail('{"detail": "Not authenticated"}')).toBeUndefined();
  });

  it("returns undefined for a non-JSON body", () => {
    expect(parseApiErrorDetail("<html>502 Bad Gateway</html>")).toBeUndefined();
    expect(parseApiErrorDetail("")).toBeUndefined();
  });
});
