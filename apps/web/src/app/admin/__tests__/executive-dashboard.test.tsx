// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-1 — /admin as the EXECUTIVE DASHBOARD.
 *
 * THE STANDARD THESE SPECS HOLD THE PAGE TO. The platform has roughly ten
 * accounts and no external paying subscribers today. An executive dashboard
 * that reacts to that by hiding tiles, printing zeroes, or animating a
 * confident-looking sparkline over three data points is worse than no
 * dashboard: it launders absence into evidence. Equally, hiding a real COUNT
 * because its block is flagged `insufficientData` hides the truth in the other
 * direction — BE-2's own docstring says that flag suppresses the RATE-shaped
 * reading, not the count. So the page must
 *
 *   · keep all five KPI slots on screen at every data volume,
 *   · show real counts at ten accounts, and gate only the rates,
 *   · never net A$ revenue against US$ LLM cost (the API refuses to, and says
 *     so in its own `note`),
 *   · poll every 30s and offer a manual refresh, without blanking figures
 *     already on screen while the next poll is in flight,
 *   · and surface a load failure as a failure, never as an empty dashboard.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminExecutiveDashboardPage from "../page";
import {
  AdminExecutiveMetricsSchema,
  type AdminExecutiveMetrics,
} from "../../../lib/api/adminMetrics";

// Vitest hoists every `vi.mock` below above the imports above, so the stubs are
// installed before `../page` is evaluated even though they are written after it.
// The `vi.fn()` handles they close over are read lazily, inside the arrows, so
// they are assigned long before the first call.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchAdminExecutiveMetricsMock = vi.fn();
vi.mock("../../../lib/api/adminMetrics", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/adminMetrics")>();
  return {
    ...actual,
    fetchAdminExecutiveMetrics: (...a: unknown[]) => fetchAdminExecutiveMetricsMock(...a),
  };
});

/**
 * The page reads three endpoints: the metrics payload, `/admin/users` (for the
 * latest-signups strip) and `/admin/audit-log`. `<HealthOverview>` reads
 * `/admin/health` too. All four are stubbed here.
 *
 * The stubs are RE-ARMED in `beforeEach` rather than configured once inside the
 * factory, because `afterEach`'s `vi.restoreAllMocks()` strips a `vi.fn()`'s
 * implementation — which previously left `fetchAdminHealth` returning
 * `undefined` and `HealthOverview` calling `.then` on it, crashing the whole
 * tree from the second test onward.
 */
const fetchAdminHealthMock = vi.fn();
const fetchAdminUsersMock = vi.fn();
const fetchAuditLogMock = vi.fn();
vi.mock("../../../lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/admin")>();
  return {
    ...actual,
    fetchAdminHealth: (...a: unknown[]) => fetchAdminHealthMock(...a),
    fetchAdminUsers: (...a: unknown[]) => fetchAdminUsersMock(...a),
    fetchAuditLog: (...a: unknown[]) => fetchAuditLogMock(...a),
  };
});

function stubMatchMedia(reduced: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? reduced : false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/** 30 zero-filled UTC days ending 2026-08-14, with `counts` applied to the tail. */
function days(counts: number[]): Array<{ date: string; count: number }> {
  const end = new Date("2026-08-14T00:00:00Z").getTime();
  const series: Array<{ date: string; count: number }> = [];
  for (let i = 29; i >= 0; i -= 1) {
    series.push({ date: new Date(end - i * 86_400_000).toISOString().slice(0, 10), count: 0 });
  }
  for (let i = 0; i < counts.length; i += 1) series[30 - counts.length + i].count = counts[i];
  return series;
}

/** Production's shape TODAY, parsed through the REAL client schema so this
 *  fixture cannot drift from what the page will actually receive. */
function todayMetrics(): AdminExecutiveMetrics {
  const signups = days([1, 0, 1, 0, 0, 2, 0, 1, 0, 0, 1, 0, 0, 0]);
  return AdminExecutiveMetricsSchema.parse({
    asOf: "2026-08-14T23:00:00Z",
    windowDays: 30,
    currencies: { revenue: "AUD", llmCost: "USD" },
    gstRegistered: false,
    insufficientDataThreshold: 20,
    revenue: {
      currency: "AUD",
      estimate: true,
      mrrAud: 0,
      arrAud: 0,
      paidSubscribers: 0,
      unbackedPaidRows: 1,
      excludedAdminRows: 1,
      excludedDeletedRows: 0,
      byPlan: [],
      sampleSize: 0,
      insufficientData: true,
    },
    signupsByDay: {
      series: signups,
      total: 6,
      windowDays: 30,
      excludes: "admin accounts and soft-deleted accounts",
      sampleSize: 6,
      insufficientData: true,
    },
    runsByDay: {
      series: signups.map((r) => ({ date: r.date, runs: r.count * 3, costUsd: r.count * 0.4 })),
      totalRuns: 18,
      totalCostUsd: 2.4,
      currency: "USD",
      windowDays: 30,
      includes: "all accounts (admin runs cost real money too)",
      sampleSize: 18,
      insufficientData: true,
    },
    funnel: {
      window: "all time",
      stages: [
        { key: "signup", label: "Signed up", count: 10, shareOfSignups: 1 },
        { key: "firstRun", label: "Ran an agent", count: 4, shareOfSignups: 0.4 },
        { key: "firstSubmission", label: "Submitted an application", count: 1, shareOfSignups: 0.1 },
        { key: "paid", label: "Paid", count: 0, shareOfSignups: 0 },
      ],
      definitions: {
        _shape: "Stages are INDEPENDENT milestone counts over the same signup population.",
      },
      sampleSize: 10,
      insufficientData: true,
    },
    costVsRevenue: {
      windowDays: 30,
      llmCostUsd: 12.6,
      grossRevenueAud: 0,
      refundsAud: 0,
      revenueAud: 0,
      paymentCount: 0,
      fxRateApplied: null,
      note: "LLM cost is USD and revenue is AUD. No exchange rate is applied and no combined margin is reported.",
      sampleSize: 0,
      insufficientData: true,
    },
    topReferrers: {
      agents: [],
      totalAgentsWithSignups: 0,
      totalAttributedSignups: 0,
      limit: 5,
      sampleSize: 0,
      insufficientData: true,
    },
    excluded: { adminAccounts: 1, deletedAccounts: 0 },
  });
}

const USERS = {
  users: [
    {
      id: "u-9",
      email: "newest@example.com",
      name: "Newest User",
      username: null,
      isAdmin: false,
      suspended: false,
      plan: "free",
      subStatus: null,
      signupAt: "2026-08-14T09:00:00Z",
      lastLoginAt: null,
      spendUsd: 0,
      runCount: 0,
      currency: "USD",
    },
    {
      id: "u-1",
      email: "older@example.com",
      name: "Older User",
      username: null,
      isAdmin: false,
      suspended: false,
      plan: "free",
      subStatus: null,
      signupAt: "2026-07-01T09:00:00Z",
      lastLoginAt: null,
      spendUsd: 0,
      runCount: 0,
      currency: "USD",
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
};

const AUDIT = {
  entries: [
    {
      id: "au-1",
      actorUserId: "owner-1",
      actorEmail: "owner@example.com",
      action: "admin.user.entitlement",
      targetType: "user",
      targetId: "u-9",
      detail: null,
      ip: null,
      createdAt: "2026-08-14T10:00:00Z",
    },
  ],
  total: 1,
  limit: 6,
  offset: 0,
};

beforeEach(() => {
  stubMatchMedia(true); // reduced motion: deterministic, no transitions to await
  fetchAdminExecutiveMetricsMock.mockReset();
  fetchAdminExecutiveMetricsMock.mockResolvedValue(todayMetrics());
  fetchAdminUsersMock.mockReset();
  fetchAdminUsersMock.mockResolvedValue(USERS);
  fetchAuditLogMock.mockReset();
  fetchAuditLogMock.mockResolvedValue(AUDIT);
  fetchAdminHealthMock.mockReset();
  fetchAdminHealthMock.mockResolvedValue({
    services: { api: "ok", database: "ok" },
    agents: { totalRuns: 0, succeeded: 0, failed: 0, running: 0, queued: 0, successRate: null },
    llm: { mode: "live" },
    cron: { status: "ok", detail: "" },
    providers: { configuredTiers: [], count: 0 },
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the KPI band", () => {
  it("keeps all five slots at ten users and nothing paid", async () => {
    render(<AdminExecutiveDashboardPage />);
    await waitFor(() => expect(screen.getByTestId("admin-kpi-mrr")).toBeTruthy());
    for (const id of ["mrr", "paid-subscribers", "signups-7d", "conversion", "cost-vs-revenue"]) {
      expect(screen.getByTestId(`admin-kpi-${id}`)).toBeTruthy();
    }
  });

  it("shows the real COUNTS at ten accounts rather than hiding them", async () => {
    render(<AdminExecutiveDashboardPage />);
    const mrr = await screen.findByTestId("admin-kpi-mrr");
    expect(mrr.getAttribute("data-measured")).toBe("true");
    expect(within(mrr).getByTestId("admin-kpi-mrr-value").textContent).toContain("A$0.00");
    expect(screen.getByTestId("admin-kpi-paid-subscribers-value").textContent).toContain("0");
    // Last 7 days of the fixture: 1+0+0+1+0+0+0 = 2.
    expect(screen.getByTestId("admin-kpi-signups-7d-value").textContent).toContain("2");
  });

  it("gates ONLY the rate-shaped tile, and names the API's threshold", async () => {
    render(<AdminExecutiveDashboardPage />);
    const tile = await screen.findByTestId("admin-kpi-conversion");
    expect(tile.getAttribute("data-measured")).toBe("false");
    expect(within(tile).getByTestId("admin-kpi-conversion-value").textContent).toContain("—");
    expect(tile.textContent).toContain("20");
    // The counts behind the refused rate are still on the tile.
    expect(tile.textContent).toContain("10");
  });

  it("never nets A$ revenue against US$ LLM cost, and quotes the API's refusal", async () => {
    render(<AdminExecutiveDashboardPage />);
    const tile = await screen.findByTestId("admin-kpi-cost-vs-revenue");
    expect(within(tile).getByTestId("admin-kpi-cost-vs-revenue-value").textContent).toContain(
      "US$12.60",
    );
    expect(tile.textContent).toContain("A$0.00");
    expect(tile.textContent).toMatch(/no exchange rate/i);
    // A margin would have to appear as a percentage; none may.
    expect(tile.textContent).not.toMatch(/\d+\.\d%/);
  });

  it("renders no fabricated delta where the API publishes no prior measurement", async () => {
    render(<AdminExecutiveDashboardPage />);
    const mrr = await screen.findByTestId("admin-kpi-mrr");
    expect(within(mrr).queryByTestId("admin-kpi-mrr-delta")).toBeNull();
    expect(mrr.textContent).toMatch(/no prior MRR measurement/i);
    // Signups DO have two real weeks to compare, so that tile gets a chip.
    expect(screen.getByTestId("admin-kpi-signups-7d-delta")).toBeTruthy();
  });
});

describe("the growth band", () => {
  it("draws the funnel's real counts and states they are independent milestones", async () => {
    render(<AdminExecutiveDashboardPage />);
    const funnel = await screen.findByTestId("admin-exec-funnel");
    expect(funnel.textContent).toContain("Signed up");
    expect(funnel.textContent).toContain("Ran an agent");
    expect(screen.getByTestId("admin-exec-funnel-shape-note").textContent).toMatch(/INDEPENDENT/);
  });

  it("suppresses the share percentages while the sample is below the threshold", async () => {
    render(<AdminExecutiveDashboardPage />);
    await screen.findByTestId("admin-exec-funnel");
    expect(screen.getByTestId("admin-exec-shares").getAttribute("data-trend-readable")).toBe(
      "false",
    );
    const row = screen.getByTestId("admin-exec-share-firstRun");
    expect(row.getAttribute("data-measured")).toBe("false");
    expect(row.textContent).toContain("—");
  });

  it("draws the signup series but says its shape is not yet a trend", async () => {
    render(<AdminExecutiveDashboardPage />);
    const panel = await screen.findByTestId("admin-exec-signup-trend");
    expect(panel.getAttribute("data-measured")).toBe("true");
    expect(within(panel).getByTestId("rate-not-readable").textContent).toMatch(
      /not enough data yet/i,
    );
  });

  it("says the plan mix is not measurable rather than drawing an empty ring", async () => {
    render(<AdminExecutiveDashboardPage />);
    const mix = await screen.findByTestId("admin-exec-plan-mix");
    expect(mix.getAttribute("data-measured")).toBe("false");
    expect(mix.textContent).toMatch(/not enough data yet/i);
  });
});

describe("the operational strip", () => {
  it("links the newest signup to its own user page, newest first", async () => {
    render(<AdminExecutiveDashboardPage />);
    const strip = await screen.findByTestId("admin-exec-latest-signups");
    const link = within(strip).getByRole("link", { name: /newest@example\.com|Newest User/ });
    expect(link.getAttribute("href")).toBe("/admin/users/u-9");
    // Sorted newest-first: the 2026-08-14 account precedes the 2026-07-01 one.
    const hrefs = within(strip)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"))
      .filter((h) => h?.startsWith("/admin/users/"));
    expect(hrefs[0]).toBe("/admin/users/u-9");
  });

  it("shows the honest empty state for sales-agent referrers", async () => {
    render(<AdminExecutiveDashboardPage />);
    const refs = await screen.findByTestId("admin-exec-referrers");
    expect(refs.getAttribute("data-measured")).toBe("false");
    expect(refs.textContent).toMatch(/no sales agent/i);
  });

  it("lists the most recent admin actions", async () => {
    render(<AdminExecutiveDashboardPage />);
    const audit = await screen.findByTestId("admin-exec-audit");
    expect(audit.textContent).toContain("admin.user.entitlement");
  });

  it("reports a failing side-read on its own panel, not as a blank board", async () => {
    fetchAuditLogMock.mockRejectedValue(new Error("audit unavailable"));
    render(<AdminExecutiveDashboardPage />);
    const audit = await screen.findByTestId("admin-exec-audit");
    await waitFor(() => expect(audit.textContent).toContain("audit unavailable"));
    // …and the metrics board is untouched by it.
    expect(screen.getByTestId("admin-kpi-mrr").getAttribute("data-measured")).toBe("true");
  });
});

describe("loading, polling and failure", () => {
  it("shows skeletons before the first payload, and no invented zeroes", async () => {
    let resolve: (v: AdminExecutiveMetrics) => void = () => {};
    fetchAdminExecutiveMetricsMock.mockImplementation(
      () =>
        new Promise<AdminExecutiveMetrics>((r) => {
          resolve = r;
        }),
    );
    render(<AdminExecutiveDashboardPage />);
    expect(screen.getAllByTestId("admin-exec-skeleton").length).toBeGreaterThan(0);
    expect(screen.queryByText("A$0.00")).toBeNull();
    await act(async () => {
      resolve(todayMetrics());
    });
    await waitFor(() => expect(screen.queryAllByTestId("admin-exec-skeleton")).toHaveLength(0));
  });

  it("polls every 30 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<AdminExecutiveDashboardPage />);
    await waitFor(() => expect(fetchAdminExecutiveMetricsMock).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fetchAdminExecutiveMetricsMock).toHaveBeenCalledTimes(2);
  });

  it("refreshes on demand", async () => {
    render(<AdminExecutiveDashboardPage />);
    await waitFor(() => expect(fetchAdminExecutiveMetricsMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(fetchAdminExecutiveMetricsMock).toHaveBeenCalledTimes(2));
  });

  it("keeps the last good figures on screen while a refresh is in flight", async () => {
    render(<AdminExecutiveDashboardPage />);
    await screen.findByTestId("admin-kpi-signups-7d");
    let resolve: (v: AdminExecutiveMetrics) => void = () => {};
    fetchAdminExecutiveMetricsMock.mockImplementation(
      () =>
        new Promise<AdminExecutiveMetrics>((r) => {
          resolve = r;
        }),
    );
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    // Still the previous payload's figure — a poll must not blank the board.
    expect(screen.getByTestId("admin-kpi-signups-7d-value").textContent).toContain("2");
    await act(async () => {
      resolve(todayMetrics());
    });
  });

  it("reports a load failure as a failure, never as an empty dashboard", async () => {
    fetchAdminExecutiveMetricsMock.mockRejectedValue(new Error("metrics endpoint unavailable"));
    render(<AdminExecutiveDashboardPage />);
    const banner = await screen.findByTestId("admin-exec-error");
    expect(banner.textContent).toContain("metrics endpoint unavailable");
    // And the tiles stay in place, each saying it could not be measured.
    expect(screen.getByTestId("admin-kpi-mrr").getAttribute("data-measured")).toBe("false");
  });
});
