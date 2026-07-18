// @vitest-environment jsdom
/**
 * Sidebar plan/quota indicator (MV-dashboard-006).
 *
 * MV-dashboard-006: the dashboard hub shows no plan-tier or quota/usage
 * indicator anywhere — not in the topbar chip, not in the sidebar — despite
 * a real, populated quota system existing server-side
 * (GET /billing/subscription -> quota.runsUsed/runsAllowed/spendUsedUsd/
 * spendCapUsd) that the wireframe expects to be visible ("Pro plan" under
 * the user's name) and that is already surfaced honestly elsewhere (Agent
 * Settings, admin). This adds a small, honest plan/quota readout to the
 * desktop sidebar, sourced from the same real GET /billing/subscription the
 * Settings page already uses (settings-client.tsx `billing-quota-*`) — no
 * fabricated numbers, no Math.random().
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SubscriptionState } from "../../lib/api/billing";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));

const fetchSubscriptionMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/billing", () => ({ fetchSubscription: fetchSubscriptionMock }));

// eslint-disable-next-line import/first
import { Sidebar } from "../sidebar";

function subscription(overrides: Partial<SubscriptionState> = {}): SubscriptionState {
  return {
    plan: { id: "pro", name: "Pro", modelTier: "premium" },
    status: "active",
    interval: "month",
    currentPeriodEnd: "2026-08-01T00:00:00Z",
    cancelAtPeriodEnd: false,
    quota: {
      runsUsed: 12,
      runsAllowed: 50,
      spendUsedUsd: 1.2,
      spendCapUsd: 10,
      periodEnd: "2026-08-01T00:00:00Z",
    },
    ...overrides,
  };
}

beforeEach(() => {
  fetchAgentsMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  fetchAgentsMock.mockReset();
  fetchSubscriptionMock.mockReset();
});

describe("Sidebar plan/quota indicator (MV-dashboard-006)", () => {
  it("shows the real plan name and real run-quota usage once loaded", async () => {
    fetchSubscriptionMock.mockResolvedValue(subscription());
    render(<Sidebar />);

    await waitFor(() => expect(screen.getByTestId("sidebar-plan-quota-runs")).toBeTruthy());
    expect(screen.getByTestId("sidebar-plan-name").textContent).toMatch(/pro/i);
    expect(screen.getByTestId("sidebar-plan-quota-runs").textContent).toMatch(/12\s*\/\s*50/);
  });

  it("never fabricates a number — an account with no quota on record shows honest fallback copy, not an invented figure", async () => {
    fetchSubscriptionMock.mockResolvedValue(subscription({ quota: null, plan: null }));
    render(<Sidebar />);

    await waitFor(() => expect(screen.getByTestId("sidebar-plan-name")).toBeTruthy());
    expect(screen.getByTestId("sidebar-plan-name").textContent).toMatch(/free/i);
    expect(screen.queryByTestId("sidebar-plan-quota-runs")).toBeNull();
    expect(screen.getByText(/no usage quota on record/i)).toBeTruthy();
  });

  it("fails closed honestly (no crash, no fabricated data) when the subscription fetch errors", async () => {
    fetchSubscriptionMock.mockRejectedValue(new Error("network error"));
    render(<Sidebar />);

    await waitFor(() => expect(screen.getByTestId("sidebar-plan-quota")).toBeTruthy());
    expect(screen.getByTestId("sidebar-plan-quota").textContent).toMatch(/plan unavailable/i);
  });
});
