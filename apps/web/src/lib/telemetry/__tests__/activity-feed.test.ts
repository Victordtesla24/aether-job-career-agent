/**
 * S-UI-REBUILD §3.2 — THE MAPPING LAW, as a pure function.
 *
 * Law T-1: nothing in the telemetry layer may render a fact that is not in the
 * left column of §3.2's table. `/events/stream` carries NO record contents and
 * never names a business event (§3.1(a), and the server module docstring says
 * so citing ADR-GMV4-003) — so a row saying "Cover letter drafted for Nearmap"
 * would be a fabrication.
 *
 * These tests pin the mapping row by row, including the two places the wire is
 * easiest to over-read:
 *  - `watermark_advanced` proves a row MOVED, not that one was ADDED — so it
 *    may not carry a number of any kind;
 *  - `coverLetters` watches Application rows that HAVE a cover letter, so an
 *    unrelated stage move fires it (§3.1's "superset warning"). Its copy may
 *    never claim a cover letter was written.
 */
import { describe, expect, it } from "vitest";

import type { ResourceChange } from "../../realtime/transport-types";
import { describeResourceChange, resourceHref } from "../activity-feed";

function change(overrides: Partial<ResourceChange> = {}): ResourceChange {
  return {
    resource: "jobs",
    count: 12,
    watermark: "2026-08-14T03:44:12Z",
    previousCount: 0,
    previousWatermark: "2026-08-14T03:41:00Z",
    reason: "count_changed",
    ...overrides,
  };
}

describe("§3.2 row 1 — count_changed, count > previousCount", () => {
  it("states the EXACT delta, not the new total", () => {
    const row = describeResourceChange(change({ count: 8358, previousCount: 8346 }), 1000);
    expect(row.delta).toBe(12);
    expect(row.text).toBe("12 new jobs");
    expect(row.tone).toBe("increase");
    // The total is a fact the ticker has no business asserting as an event.
    expect(row.text).not.toMatch(/8358|8,358/);
  });

  it("singularises a delta of one", () => {
    expect(describeResourceChange(change({ count: 1, previousCount: 0 }), 1).text).toBe("1 new job");
  });
});

describe("§3.2 row 2 — count_changed, count < previousCount", () => {
  it("never calls a decrease 'new' and never shows a green up-delta", () => {
    const row = describeResourceChange(
      change({ resource: "applications", count: 284, previousCount: 287 }),
      1000,
    );
    expect(row.text).toBe("3 applications removed");
    expect(row.tone).toBe("decrease");
    expect(row.delta).toBe(-3);
    expect(row.text).not.toMatch(/new/i);
  });
});

describe("§3.2 row 3 — watermark_advanced (counts equal)", () => {
  it("carries NO number at all — the wire proves a move, not an addition", () => {
    const row = describeResourceChange(
      change({
        resource: "applications",
        reason: "watermark_advanced",
        count: 287,
        previousCount: 287,
      }),
      1000,
    );
    expect(row.text).toBe("Applications updated");
    expect(row.tone).toBe("neutral");
    expect(row.delta).toBeNull();
    expect(row.text).not.toMatch(/\d/);
  });

  it("stays numberless even when the server's counts happen to differ", () => {
    // `watermark_advanced` is the server saying "max(updated_at) moved". A
    // count difference alongside it was not the reported evidence, so the row
    // may not present one as the observed event.
    const row = describeResourceChange(
      change({ reason: "watermark_advanced", count: 40, previousCount: 12 }),
      1000,
    );
    expect(row.delta).toBeNull();
    expect(row.text).not.toMatch(/\d/);
  });
});

describe("§3.2 row 4 — reconnect_gap", () => {
  it("says it was reconnecting and never presents the change as observed live", () => {
    const row = describeResourceChange(
      change({ resource: "jobs", reason: "reconnect_gap", count: 40, previousCount: 12 }),
      1000,
    );
    expect(row.tone).toBe("gap");
    expect(row.text).toBe("While reconnecting: jobs changed");
    // Forbidden: a delta implying we watched those 28 rows arrive.
    expect(row.delta).toBeNull();
    expect(row.text).not.toMatch(/\bnew\b/i);
  });
});

describe("§3.1 superset warning — coverLetters", () => {
  it("never claims a cover letter was written, because the stream cannot know that", () => {
    const up = describeResourceChange(
      change({ resource: "coverLetters", count: 9, previousCount: 8 }),
      1000,
    );
    // `coverLetters` counts APPLICATION rows that have a cover letter, so an
    // unrelated stage move fires it. The copy states exactly that.
    expect(up.text).toBe("1 more application has a cover letter");
    expect(up.text).not.toMatch(/drafted|written|generated|wrote/i);

    const moved = describeResourceChange(
      change({ resource: "coverLetters", reason: "watermark_advanced", count: 9, previousCount: 9 }),
      1000,
    );
    expect(moved.text).toBe("Cover letters updated");
    expect(moved.text).not.toMatch(/drafted|written|generated/i);
  });

  it("phrases a decrease against the same superset noun", () => {
    const down = describeResourceChange(
      change({ resource: "coverLetters", count: 7, previousCount: 9 }),
      1000,
    );
    expect(down.text).toBe("2 fewer applications have a cover letter");
  });
});

describe("a delta that cannot be computed is never invented", () => {
  it("degrades to the numberless 'updated' copy when previousCount is null", () => {
    const row = describeResourceChange(
      change({ resource: "stories", count: 19, previousCount: null }),
      1000,
    );
    // There is no prior server observation to subtract from, so there is no
    // delta. Rendering "19 new stories" would claim 19 arrived just now.
    expect(row.delta).toBeNull();
    expect(row.text).toBe("Stories updated");
  });

  it("degrades when count_changed reports identical counts", () => {
    const row = describeResourceChange(change({ count: 5, previousCount: 5 }), 1000);
    expect(row.delta).toBeNull();
    expect(row.text).toBe("Jobs updated");
  });
});

describe("every resource maps to a screen that can show the truth", () => {
  it("routes each of the 12 keys to an owning screen", () => {
    const resources = [
      "jobs",
      "applications",
      "coverLetters",
      "resumes",
      "stories",
      "emails",
      "contacts",
      "outreach",
      "interviews",
      "offers",
      "approvals",
      "agentRuns",
    ] as const;
    for (const resource of resources) {
      expect(resourceHref(resource)).toMatch(/^\/dashboard/);
      // And every one of them produces a row with real words.
      const row = describeResourceChange(change({ resource, reason: "watermark_advanced" }), 1);
      expect(row.text.length).toBeGreaterThan(0);
      expect(row.text).not.toMatch(/undefined|null|NaN/);
    }
  });
});

describe("the row carries the observation instant it was given", () => {
  it("uses the caller's observedAt rather than reading the clock itself", () => {
    expect(describeResourceChange(change(), 1_723_600_000_000).observedAt).toBe(1_723_600_000_000);
  });
});
