// @vitest-environment jsdom
/**
 * Rail plan/quota indicator (MV-dashboard-006) + contact-support link
 * (O-1, S-FIX slice C).
 *
 * Ported from the deleted `components/__tests__/sidebar.test.tsx`
 * (SHELL-DEL remediation): that file was the ONLY test in the repo covering
 * these two behaviors, which are still live in `components/shell/Rail.tsx`
 * verbatim — same testids (`sidebar-plan-name`, `sidebar-plan-quota-runs`,
 * `sidebar-plan-quota`, `sidebar-plan-skeleton`), same anti-fabrication
 * guarantees, same `supportEmail` conditional. This ports the 5 cases to
 * import `Rail` directly (no `sidebar` alias) and follows the neighboring
 * shell tests' `fetchSubscription`/`fetchAgents` mocking idiom.
 *
 * MV-dashboard-006: the dashboard hub shows no plan-tier or quota/usage
 * indicator anywhere — not in the topbar chip, not in the rail — despite
 * a real, populated quota system existing server-side
 * (GET /billing/subscription -> quota.runsUsed/runsAllowed/spendUsedUsd/
 * spendCapUsd) that the wireframe expects to be visible ("Pro plan" under
 * the user's name) and that is already surfaced honestly elsewhere (Agent
 * Settings, admin). The rail's plan/quota readout is sourced from the same
 * real GET /billing/subscription the Settings page already uses
 * (settings-client.tsx `billing-quota-*`) — no fabricated numbers, no
 * Math.random().
 */
import type { ReactNode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SubscriptionState } from "../../../lib/api/billing";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));

const fetchSubscriptionMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/billing", () => ({ fetchSubscription: fetchSubscriptionMock }));

// eslint-disable-next-line import/first
import { Rail } from "../Rail";

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
    // ADMIN-FULL: GET /billing/subscription now carries the ONE server-side
    // entitlement verdict. This fixture is an ordinary paying user — not an
    // admin and under no override — so every assertion below is unchanged.
    entitlement: {
      unlimited: false,
      entitled: true,
      source: "plan",
      isAdmin: false,
      planId: "pro",
      activePaid: true,
      overrideActive: false,
      overrideKind: null,
      overridePlanId: null,
      overrideNote: null,
      overrideSetBy: null,
      overrideSetAt: null,
    },
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  fetchAgentsMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  fetchAgentsMock.mockReset();
  fetchSubscriptionMock.mockReset();
});

describe("Rail plan/quota indicator (MV-dashboard-006)", () => {
  it("shows the real plan name and real run-quota usage once loaded", async () => {
    fetchSubscriptionMock.mockResolvedValue(subscription());
    render(<Rail />);

    await waitFor(() => expect(screen.getByTestId("sidebar-plan-quota-runs")).toBeTruthy());
    expect(screen.getByTestId("sidebar-plan-name").textContent).toMatch(/pro/i);
    expect(screen.getByTestId("sidebar-plan-quota-runs").textContent).toMatch(/12\s*\/\s*50/);
  });

  it("never fabricates a number — an account with no quota on record shows honest fallback copy, not an invented figure", async () => {
    fetchSubscriptionMock.mockResolvedValue(subscription({ quota: null, plan: null }));
    render(<Rail />);

    await waitFor(() => expect(screen.getByTestId("sidebar-plan-name")).toBeTruthy());
    expect(screen.getByTestId("sidebar-plan-name").textContent).toMatch(/free/i);
    expect(screen.queryByTestId("sidebar-plan-quota-runs")).toBeNull();
    expect(screen.getByText(/no usage quota on record/i)).toBeTruthy();
  });

  it("fails closed honestly (no crash, no fabricated data) when the subscription fetch errors", async () => {
    fetchSubscriptionMock.mockRejectedValue(new Error("network error"));
    render(<Rail />);

    await waitFor(() => expect(screen.getByTestId("sidebar-plan-quota")).toBeTruthy());
    expect(screen.getByTestId("sidebar-plan-quota").textContent).toMatch(/plan unavailable/i);
  });
});

describe("Rail contact-support link (O-1, S-FIX slice C)", () => {
  beforeEach(() => {
    fetchSubscriptionMock.mockResolvedValue(null);
  });

  it("renders a real mailto 'Contact support' link next to Privacy Policy/Terms when a support email is supplied", () => {
    render(<Rail supportEmail="help@example-operator.com" />);

    const link = screen.getByRole("link", { name: /contact support/i });
    expect(link.getAttribute("href")).toBe("mailto:help@example-operator.com");
  });

  it("never fabricates a contact link — renders no 'Contact support' link when no support email is configured", () => {
    render(<Rail supportEmail={null} />);

    expect(screen.queryByRole("link", { name: /contact support/i })).toBeNull();
  });
});
