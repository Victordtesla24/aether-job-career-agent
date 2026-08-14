// @vitest-environment jsdom
/**
 * ADMIN-FULL — OWNER EXPERIENCE.
 *
 * USER MANDATE (2026-08-14): "admins/owners have NO subscriptions or plans
 * themselves". So an admin must never be shown a plan surface, a quota counter
 * or an upsell — the server enforces none of those against them, and rendering
 * "Pro 98/100" for an account nothing meters is a fabricated number.
 *
 * The exemption is SERVER-SIDE: `entitlement.unlimited` on GET
 * /billing/subscription and GET /billing/entitlement is the ONE resolver's
 * verdict (app/services/entitlements.py). These specs pin that the UI mirrors
 * that verdict and NOTHING more — a non-admin's behaviour at each surface is
 * asserted unchanged in the same file.
 */
import type { ReactNode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const fetchEntitlementMock = vi.hoisted(() => vi.fn());
const fetchSubscriptionMock = vi.hoisted(() => vi.fn());
const fetchAgentsMock = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api/billing", () => ({
  fetchEntitlement: fetchEntitlementMock,
  fetchSubscription: fetchSubscriptionMock,
}));
vi.mock("../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));

import { SubscriptionGate } from "../../components/subscription-gate";
import { Rail } from "../../components/shell/Rail";
import { MobileNavSheet } from "../../components/shell/MobileNavSheet";
import { ShellSubscriptionContext } from "../../components/shell/shell-context";

const ACTIONABLE = "ACTIONABLE_DASHBOARD_CONTENT";

const PAID_QUOTA = {
  runsUsed: 98,
  runsAllowed: 100,
  spendUsedUsd: 4.2,
  spendCapUsd: 15,
  periodEnd: "2026-09-01T00:00:00Z",
};

beforeEach(() => {
  window.localStorage.clear();
  fetchAgentsMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SubscriptionGate — no paywall ever renders for an unlimited account", () => {
  it("renders the dashboard for an admin with no paid subscription", async () => {
    fetchEntitlementMock.mockResolvedValue({
      active_paid: false,
      plan: { id: "free", status: "active" },
      requiresSubscription: true,
      unlimited: true,
      entitled: true,
      source: "admin",
      isAdmin: true,
    });

    render(
      <SubscriptionGate>
        <div>{ACTIONABLE}</div>
      </SubscriptionGate>,
    );

    await waitFor(() => expect(screen.getByText(ACTIONABLE)).toBeTruthy());
    expect(screen.queryByTestId("subscription-paywall")).toBeNull();
  });

  it("still paywalls a NON-admin without a paid subscription (unchanged)", async () => {
    fetchEntitlementMock.mockResolvedValue({
      active_paid: false,
      plan: { id: "free", status: "active" },
      requiresSubscription: true,
      unlimited: false,
      entitled: false,
      source: "plan",
      isAdmin: false,
    });

    render(
      <SubscriptionGate>
        <div>{ACTIONABLE}</div>
      </SubscriptionGate>,
    );

    await waitFor(() => expect(screen.getByTestId("subscription-paywall")).toBeTruthy());
    expect(screen.queryByText(ACTIONABLE)).toBeNull();
  });
});

describe("Rail plan card — 'Owner — unlimited' instead of a quota nothing enforces", () => {
  it("shows the owner state and NO run counter for an unlimited account", async () => {
    fetchSubscriptionMock.mockResolvedValue({
      plan: { id: "pro", name: "Pro", modelTier: "advanced" },
      status: "active",
      interval: "month",
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      quota: PAID_QUOTA,
      entitlement: { unlimited: true, source: "admin", isAdmin: true },
    });

    render(<Rail />);

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-plan-name").textContent).toContain("Owner"),
    );
    expect(screen.getByTestId("sidebar-plan-unlimited").textContent).toContain(
      "No plan, quota or spend cap",
    );
    expect(screen.queryByTestId("sidebar-plan-quota-runs")).toBeNull();
    // The card must not offer an upgrade path anywhere.
    expect(screen.getByTestId("sidebar-plan-quota").textContent).not.toMatch(/upgrade/i);
  });

  it("still shows the real plan + run counter for a NON-admin (unchanged)", async () => {
    fetchSubscriptionMock.mockResolvedValue({
      plan: { id: "pro", name: "Pro", modelTier: "advanced" },
      status: "active",
      interval: "month",
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      quota: PAID_QUOTA,
      entitlement: { unlimited: false, source: "plan", isAdmin: false },
    });

    render(<Rail />);

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-plan-name").textContent).toContain("Pro"),
    );
    expect(screen.getByTestId("sidebar-plan-quota-runs").textContent).toContain("98/100");
    expect(screen.queryByTestId("sidebar-plan-unlimited")).toBeNull();
  });

  it("keeps the plan counter when the API omits entitlement entirely (older build)", async () => {
    fetchSubscriptionMock.mockResolvedValue({
      plan: { id: "free", name: "Free", modelTier: "light" },
      status: "active",
      interval: null,
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      quota: { ...PAID_QUOTA, runsUsed: 1, runsAllowed: 5 },
    });

    render(<Rail />);

    await waitFor(() =>
      expect(screen.getByTestId("sidebar-plan-quota-runs").textContent).toContain("1/5"),
    );
  });
});

describe("MobileNavSheet plan card — the same owner state on the phone surface", () => {
  // The mobile sheet reads the ONE shared GET /billing/subscription through
  // ShellSubscriptionContext (see shell-context.tsx), so it is driven by the
  // very same server verdict as the rail. Pinning it here stops the owner
  // experience from being desktop-only.
  const sheet = (value: unknown) => (
    <ShellSubscriptionContext.Provider value={{ value } as never}>
      <MobileNavSheet open onClose={() => {}} currentHref="/dashboard" />
    </ShellSubscriptionContext.Provider>
  );

  it("shows 'Owner — unlimited' and no run counter for an unlimited account", async () => {
    render(
      sheet({
        plan: { id: "pro", name: "Pro", modelTier: "advanced" },
        status: "active",
        interval: "month",
        currentPeriodEnd: null,
        cancelAtPeriodEnd: false,
        quota: PAID_QUOTA,
        entitlement: { unlimited: true, source: "admin", isAdmin: true },
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("mobile-nav-plan-name").textContent).toContain("Owner"),
    );
    expect(screen.getByTestId("mobile-nav-plan-unlimited").textContent).toContain(
      "No plan, quota or spend cap",
    );
    expect(screen.getByTestId("mobile-nav-plan-quota").textContent).not.toMatch(/98/);
    expect(screen.getByTestId("mobile-nav-plan-quota").textContent).not.toMatch(/upgrade/i);
  });

  it("still shows the real plan + run counter for a NON-admin (unchanged)", async () => {
    render(
      sheet({
        plan: { id: "pro", name: "Pro", modelTier: "advanced" },
        status: "active",
        interval: "month",
        currentPeriodEnd: null,
        cancelAtPeriodEnd: false,
        quota: PAID_QUOTA,
        entitlement: { unlimited: false, source: "plan", isAdmin: false },
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("mobile-nav-plan-quota").textContent).toContain("98/100"),
    );
    expect(screen.queryByTestId("mobile-nav-plan-unlimited")).toBeNull();
  });
});
