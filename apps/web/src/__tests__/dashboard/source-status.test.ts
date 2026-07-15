/**
 * GAP-SRC-003 — unit coverage for the Jobs page per-source Sync Status
 * mapping (GET /agents/scout/sources -> view model): badge color/label per
 * status, honest error surfacing, and count/last-sync formatting.
 */
import { describe, expect, it } from "vitest";

import { sourceStatusView } from "../../components/dashboard/sourceStatus";
import type { ScoutSourceStatus } from "../../lib/api/jobs";

function row(overrides: Partial<ScoutSourceStatus>): ScoutSourceStatus {
  return {
    source: "greenhouse",
    lastSyncAt: "2026-07-15T12:00:00Z",
    lastFetched: 4,
    lastPersisted: 1,
    lastError: null,
    status: "ok",
    ...overrides,
  };
}

const NOW = new Date("2026-07-15T12:30:00Z");

describe("sourceStatusView", () => {
  it("maps status=ok to a green badge with the persisted count, never fabricating an error", () => {
    const [view] = sourceStatusView([row({ status: "ok", lastPersisted: 3 })], NOW);
    expect(view.badge).toBe("ok");
    expect(view.badgeLabel).toBe("ok, 3 new");
    expect(view.errorText).toBeNull();
  });

  it("shows 'ok, 0 new' for a source with zero new jobs but a real ok status", () => {
    const [view] = sourceStatusView([row({ status: "ok", lastPersisted: 0 })], NOW);
    expect(view.badge).toBe("ok");
    expect(view.count).toBe(0);
    expect(view.badgeLabel).toBe("ok, 0 new");
  });

  it("maps status=error to a red badge and surfaces the real backend error, never claiming ok", () => {
    const [view] = sourceStatusView(
      [
        row({
          source: "wellfound",
          status: "error",
          lastPersisted: 0,
          lastError: "AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden",
        }),
      ],
      NOW,
    );
    expect(view.badge).toBe("error");
    expect(view.badgeLabel).toBe("error");
    expect(view.errorText).toBe(
      "AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden",
    );
  });

  it("falls back to a generic error message when status=error but lastError is missing", () => {
    const [view] = sourceStatusView([row({ status: "error", lastError: null })], NOW);
    expect(view.badge).toBe("error");
    expect(view.errorText).toBe("Sync failed");
  });

  it("treats any non-ok/error status (e.g. skipped) as neutral, not ok", () => {
    const [view] = sourceStatusView([row({ status: "skipped" })], NOW);
    expect(view.badge).toBe("neutral");
    expect(view.badgeLabel).toBe("skipped");
    expect(view.errorText).toBeNull();
  });

  it("formats last-sync time relative to now, and 'never synced' when absent", () => {
    const [synced] = sourceStatusView([row({ lastSyncAt: "2026-07-15T12:00:00Z" })], NOW);
    expect(synced.lastSyncLabel).toBe("30 min ago");

    const [never] = sourceStatusView([row({ lastSyncAt: null })], NOW);
    expect(never.lastSyncLabel).toBe("never synced");
  });

  it("maps each row independently, preserving source order", () => {
    const views = sourceStatusView(
      [row({ source: "lever", status: "ok" }), row({ source: "indeed", status: "skipped" })],
      NOW,
    );
    expect(views.map((v) => v.source)).toEqual(["lever", "indeed"]);
  });
});
