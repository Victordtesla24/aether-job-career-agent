/**
 * P2/verification — dashboard stats must come from GET /analytics/funnel plus
 * live job fit scores, never hardcoded placeholders (the Phase 1 shell shipped
 * with STATS = 37/24/3/91). Card set per wireframe stats-row-p7q8r9: Active
 * Applications / Interview Rate / Offers / AI Confidence.
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

  it("builds the wireframe card set with every value derived from live data", () => {
    const cards = buildStatCards(FUNNEL_FIXTURE, { weeklyApplied: 8, avgFit: 91.2 });
    expect(cards.map((c) => c.label)).toEqual([
      "Active Applications",
      "Interview Rate",
      "Offers",
      "AI Confidence",
    ]);
    // applied=412; rate=round(19/412*100)=5; offers=4; avgFit→91
    expect(cards.map((c) => c.value)).toEqual(["412", "5", "4", "91"]);
    expect(cards[0]!.note).toBe("+8 this week");
    expect(cards[0]!.trendUp).toBe(true);
    expect(cards[1]!.unit).toBe("%");
    expect(cards[2]!.note).toContain("pending decision");
    expect(cards[3]!.unit).toBe("%");
  });

  it("degrades gracefully with zero/absent data instead of fabricating numbers", () => {
    const zero = buildStatCards(
      { ...FUNNEL_FIXTURE, applied: 0, interviewed: 0, offers: 0 },
      { weeklyApplied: 0, avgFit: null },
    );
    expect(zero[0]!.note).toBe("no new this week");
    expect(zero[1]!.value).toBe("0");
    expect(zero[1]!.note).toBe("no applications yet");
    expect(zero[2]!.note).toContain("none yet");
    expect(zero[3]!.value).toBe("—");
    expect(zero[3]!.unit).toBeUndefined();
  });

  it("dashboard page fetches live data and has no hardcoded funnel numbers", () => {
    const pageSource = readFileSync(join(__dirname, "../../app/dashboard/page.tsx"), "utf8");
    expect(pageSource).toContain("DashboardStats");
    expect(pageSource).toContain("fetchFunnel");
    expect(pageSource).toContain("fetchApprovals");
    // The Phase 1 placeholder values must be gone.
    expect(pageSource).not.toMatch(/value:\s*"(37|24|3|91)"/);
    expect(pageSource).not.toContain("const STATS");

    const statsSource = readFileSync(
      join(__dirname, "../../components/dashboard/DashboardStats.tsx"),
      "utf8",
    );
    expect(statsSource).toContain("buildStatCards");
    expect(statsSource).toContain('"use client"');
  });
});
