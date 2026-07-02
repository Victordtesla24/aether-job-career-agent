/**
 * P2 — dashboard stats must come from GET /analytics/funnel, not hardcoded
 * placeholder values (the Phase 1 shell shipped with STATS = 37/24/3/91).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchFunnel } from "../../lib/api/analytics";
import { buildStatCards } from "../../components/dashboard/DashboardStats";

const FUNNEL_FIXTURE = {
  period: "all",
  jobs_found: 847,
  applied: 412,
  screened: 133,
  interviewed: 19,
  offers: 4,
};

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.fn().mockResolvedValue(response);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dashboard live stats", () => {
  it("fetchFunnel calls GET /analytics/funnel and validates the payload", async () => {
    const fetchMock = mockFetchOnce(FUNNEL_FIXTURE);
    vi.stubGlobal("fetch", fetchMock);

    const funnel = await fetchFunnel("all", { token: "test-token" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/analytics/funnel?period=all");
    expect(funnel.jobs_found).toBe(847);
    expect(funnel.offers).toBe(4);
  });

  it("buildStatCards derives every card value from live funnel data", () => {
    const cards = buildStatCards(FUNNEL_FIXTURE);
    expect(cards).toHaveLength(4);
    expect(cards.map((c) => c.value)).toEqual(["847", "412", "19", "4"]);

    const zero = buildStatCards({ ...FUNNEL_FIXTURE, applied: 0, interviewed: 0 });
    expect(zero[2]!.note).toContain("0%");
  });

  it("dashboard page renders DashboardStats and has no hardcoded funnel numbers", () => {
    const pageSource = readFileSync(
      join(__dirname, "../../app/dashboard/page.tsx"),
      "utf8",
    );
    expect(pageSource).toContain("DashboardStats");
    // The Phase 1 placeholder values must be gone.
    expect(pageSource).not.toMatch(/value:\s*"(37|24|3|91)"/);
    expect(pageSource).not.toContain("const STATS");

    const statsSource = readFileSync(
      join(__dirname, "../../components/dashboard/DashboardStats.tsx"),
      "utf8",
    );
    expect(statsSource).toContain("fetchFunnel");
    expect(statsSource).toContain('"use client"');
  });
});
