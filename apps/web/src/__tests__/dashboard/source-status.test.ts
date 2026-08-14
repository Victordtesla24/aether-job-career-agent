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
    // QA H-08: the raw exception class / HTTP tail is humanized — the REAL
    // cause is preserved, never fabricated, but no "AdapterFetchError:" or
    // "HTTP Error 403: Forbidden" internals leak to the user.
    expect(view.errorText).toBe(
      "Wellfound public listings unavailable: the source returned HTTP 403 — Aether will retry on the next sync.",
    );
    expect(view.errorText).not.toContain("AdapterFetchError");
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

describe("sourceStatusView blocked sources (RT-008)", () => {
  it("renders status=blocked as a calm neutral 'unavailable' pill, never an error", () => {
    const [view] = sourceStatusView(
      [
        row({
          source: "wellfound",
          status: "blocked",
          lastError:
            "AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden",
        }),
      ],
      NOW,
    );
    expect(view.badge).toBe("neutral");
    expect(view.badgeLabel).toBe("unavailable (blocked by source)");
    expect(view.errorText).toBeNull();
  });
});

/**
 * S-FIX-A round 2 (finding S-FIX-A-R2-03) — a shared-key DAILY QUOTA pause is
 * temporary and self-healing, and the backend now says so in an honest
 * message. RT-008's blocked pill deliberately suppresses the row's error (a
 * permanent structural refusal is not user-actionable), which was swallowing
 * that message whole and telling a paying subscriber "unavailable (blocked by
 * source)" — i.e. "this board is blocking us" — when the truth is "the shared
 * daily API quota is used up and resets at midnight UTC".
 */
const QUOTA_ERROR =
  "SourceQuotaError: Adzuna daily API quota reached (225/225 calls on " +
  "2026-08-14); it resets at 00:00 UTC. No cached listings for this search yet.";

describe("sourceStatusView quota pauses (S-FIX-A/S-2)", () => {
  it("labels a quota pause as paused market data, not as a source block", () => {
    const [view] = sourceStatusView(
      [row({ source: "adzuna", status: "blocked", lastError: QUOTA_ERROR })],
      NOW,
    );
    expect(view.badge).toBe("neutral");
    expect(view.badgeLabel).toBe("market data paused (API quota)");
    expect(view.badgeLabel).not.toContain("blocked by source");
  });

  it("surfaces the backend's real quota copy instead of discarding it", () => {
    const [view] = sourceStatusView(
      [row({ source: "adzuna", status: "blocked", lastError: QUOTA_ERROR })],
      NOW,
    );
    expect(view.errorText).not.toBeNull();
    expect(view.errorText).toContain("Adzuna daily API quota reached");
    expect(view.errorText).toContain("00:00 UTC");
    // The exception class name is plumbing, never user copy.
    expect(view.errorText).not.toContain("SourceQuotaError");
  });

  it("keeps RT-008's structural block exactly as it was", () => {
    const [view] = sourceStatusView(
      [
        row({
          source: "wellfound",
          status: "blocked",
          lastError:
            "SourceBlockedError: Wellfound public listings unavailable: HTTP Error 403: Forbidden",
        }),
      ],
      NOW,
    );
    expect(view.badgeLabel).toBe("unavailable (blocked by source)");
    expect(view.errorText).toBeNull();
  });

  it("falls back to the humanized rendering if a quota row carries a raw dump", () => {
    const [view] = sourceStatusView(
      [
        row({
          source: "adzuna",
          status: "blocked",
          lastError:
            "SourceQuotaError: quota exhausted https://api.adzuna.com/v1/api/jobs/au/search/1?app_key=leak",
        }),
      ],
      NOW,
    );
    expect(view.errorText).not.toBeNull();
    expect(view.errorText).not.toContain("app_key");
  });
});
