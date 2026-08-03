/**
 * CRITICAL-4 — the notification bell counted approvals the backend refuses.
 *
 * MEASURED IN PRODUCTION (schema `aether`, 2026-08-03):
 *
 *     ApprovalRequest | pending | 91 rows | oldest 2026-08-01 21:11:54
 *
 * and the autopilot keeps minting more (~45/day: one pending
 * `application_submit` per generated artifact).
 *
 * `ApprovalService.resolve` voids a pending approval after
 * `EXPIRY_HOURS = 48` and answers **409 "Approval expired (> 48h old);
 * re-run the agent"**. `GET /approvals?status=pending` does not filter those
 * out — correctly, because the Approvals page must still show them so they
 * can be cleared (it labels them "expired", disables Approve/Reject, and
 * offers "Clear expired").
 *
 * The topbar bell did none of that. It set the badge to the raw
 * `items.length` of that same unfiltered response and re-polled it every 60s,
 * so a queue made entirely of void requests still read "N pending approvals"
 * — the UI asserting actionable work that cannot be actioned. With ~45 new
 * approvals a day, every one of them becomes a permanent phantom in that
 * count 48h later.
 *
 * These tests pin the badge to what the API will actually let the user do.
 */
import { describe, expect, it } from "vitest";

import { actionableApprovalCount } from "../../components/topbar";
import type { Approval } from "../../lib/api/approvals";

const HOUR = 3600 * 1000;
const NOW = new Date("2026-08-03T06:00:00.000Z").getTime();

function approval(overrides: Partial<Approval> & { id: string }): Approval {
  return {
    type: "application_submit",
    status: "pending",
    createdAt: new Date(NOW - HOUR).toISOString(),
    payload: {},
    ...overrides,
  } as Approval;
}

describe("actionableApprovalCount", () => {
  it("counts a live pending approval", () => {
    const items = [approval({ id: "a1" })];
    expect(actionableApprovalCount(items, NOW)).toBe(1);
  });

  it("does NOT count an approval the API has already voided", () => {
    const items = [
      approval({ id: "live", createdAt: new Date(NOW - 47 * HOUR).toISOString() }),
      approval({ id: "void", createdAt: new Date(NOW - 49 * HOUR).toISOString() }),
    ];
    expect(actionableApprovalCount(items, NOW)).toBe(1);
  });

  it("is zero when every pending approval has expired", () => {
    const items = Array.from({ length: 91 }, (_, i) =>
      approval({ id: `a${i}`, createdAt: new Date(NOW - 72 * HOUR).toISOString() }),
    );
    expect(actionableApprovalCount(items, NOW)).toBe(0);
  });

  it("never counts a resolved approval, expired or not", () => {
    const items = [
      approval({ id: "ok", status: "approved" }),
      approval({ id: "no", status: "rejected" }),
    ];
    expect(actionableApprovalCount(items, NOW)).toBe(0);
  });

  it("uses the 48h boundary the backend uses, exactly", () => {
    // ApprovalService._is_expired is a strict `> 48h`, so 48h flat is STILL
    // actionable. Counting it as expired would hide a request the user can
    // still approve — the opposite dishonesty.
    const atBoundary = [
      approval({ id: "b", createdAt: new Date(NOW - 48 * HOUR).toISOString() }),
    ];
    expect(actionableApprovalCount(atBoundary, NOW)).toBe(1);
    const pastBoundary = [
      approval({
        id: "b",
        createdAt: new Date(NOW - 48 * HOUR - 1000).toISOString(),
      }),
    ];
    expect(actionableApprovalCount(pastBoundary, NOW)).toBe(0);
  });

  it("tolerates an unparseable createdAt by counting the row", () => {
    // Better to over-report one row the user can inspect than to silently
    // drop an approval that may well be actionable.
    const items = [approval({ id: "weird", createdAt: "not-a-date" })];
    expect(actionableApprovalCount(items, NOW)).toBe(1);
  });
});
