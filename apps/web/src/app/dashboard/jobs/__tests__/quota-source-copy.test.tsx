// @vitest-environment jsdom
/**
 * S-FIX-A round 2 (finding S-FIX-A-R2-03) — when the shared Adzuna key's daily
 * quota is exhausted the backend raises a typed `SourceQuotaError` carrying an
 * honest, temporary, self-healing message ("… resets at 00:00 UTC"). Until this
 * test existed, that message was written to the source row and then thrown away
 * by the UI: RT-008's `blocked` pill renders a hardcoded "unavailable (blocked
 * by source)" and suppresses the row's error by design, so a paying subscriber
 * read a permanent-sounding board refusal for a pause that clears at midnight.
 *
 * This asserts the copy at the ONLY place the user can see it — the Jobs page's
 * per-source Sync Status panel — not just in the mapper's unit test.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const fetchScoutSources = vi.fn();
const fetchSourceAvailability = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
  ApiError: class ApiError extends Error {},
  describeApiError: (e: unknown, fallback: string) =>
    e instanceof Error ? e.message : fallback,
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
  fetchSourceAvailability: (...args: unknown[]) => fetchSourceAvailability(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

/** Exactly what app.agents.scout_agent writes on a quota pause. */
const QUOTA_ROW = {
  source: "adzuna",
  lastSyncAt: "2026-08-14T01:00:00Z",
  lastFetched: 0,
  lastPersisted: 0,
  lastError:
    "SourceQuotaError: Adzuna daily API quota reached (225/225 calls on " +
    "2026-08-14); it resets at 00:00 UTC. No cached listings for this search yet.",
  status: "blocked",
};

/** RT-008's permanent structural refusal — must keep its existing copy. */
const WELLFOUND_BLOCKED = {
  source: "wellfound",
  lastSyncAt: "2026-08-14T01:00:00Z",
  lastFetched: 0,
  lastPersisted: 0,
  lastError:
    "SourceBlockedError: Wellfound public listings unavailable: HTTP Error 403: Forbidden",
  status: "blocked",
};

getToken.mockResolvedValue("test-token");
apiBaseUrl.mockReturnValue("http://test.local");
fetchSourceAvailability.mockResolvedValue([
  { source: "adzuna", available: true, reason: null },
  { source: "wellfound", available: true, reason: null },
]);

function mockApi() {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/jobs?include_stale=true") return [];
    if (path.startsWith("/jobs?")) return [];
    if (path === "/agents") return [{ name: "scout", last_run: "2026-08-14T01:00:00Z" }];
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  fetchScoutSources.mockReset();
});

describe("Jobs page — quota pause copy is visible to the user", () => {
  it("shows the honest quota message on the Adzuna source chip", async () => {
    mockApi();
    fetchScoutSources.mockResolvedValue([QUOTA_ROW]);
    render(<JobsPage />);

    const chip = await waitFor(() => screen.getByTestId("source-status-chip"));
    expect(chip.textContent).toContain("market data paused (API quota)");
    expect(chip.textContent).toContain("Adzuna daily API quota reached");
    expect(chip.textContent).toContain("00:00 UTC");
    // The pause is temporary — it must not read as the board refusing us.
    expect(chip.textContent).not.toContain("blocked by source");
    expect(chip.textContent).not.toContain("SourceQuotaError");
  });

  it("still renders RT-008's structural block with its suppressed reason", async () => {
    mockApi();
    fetchScoutSources.mockResolvedValue([WELLFOUND_BLOCKED]);
    render(<JobsPage />);

    const chip = await waitFor(() => screen.getByTestId("source-status-chip"));
    expect(chip.textContent).toContain("unavailable (blocked by source)");
    expect(chip.textContent).not.toContain("HTTP Error 403");
  });
});
