// @vitest-environment jsdom
/**
 * GAP-P6-PAYWALL — dashboard subscription wall.
 *
 * Aether is a subscription-gated product (limited beta): an authenticated user
 * WITHOUT an active paid subscription must see a prominent "Subscribe to unlock
 * Aether" paywall on /dashboard instead of the actionable dashboard, with a
 * clear route to /pricing. A paid subscriber sees the real dashboard. When the
 * gate is disabled server-side (requiresSubscription=false), the dashboard
 * renders for everyone (freemium).
 *
 * The SubscriptionGate fetches entitlement from GET /billing/entitlement
 * (mocked here at the api-client boundary).
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Next's <Link> needs no router in a plain render — stub it to an anchor.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

// Mock the entitlement fetch at the module boundary.
const fetchEntitlementMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/api/billing", () => ({
  fetchEntitlement: fetchEntitlementMock,
}));

import { SubscriptionGate } from "../../components/subscription-gate";

afterEach(() => {
  cleanup();
  fetchEntitlementMock.mockReset();
});

const ACTIONABLE = "ACTIONABLE_DASHBOARD_CONTENT";

describe("SubscriptionGate", () => {
  it("shows the paywall for a non-subscriber (no active paid sub)", async () => {
    fetchEntitlementMock.mockResolvedValue({
      active_paid: false,
      plan: { id: "free", status: "active" },
      requiresSubscription: true,
    });

    render(
      <SubscriptionGate>
        <div>{ACTIONABLE}</div>
      </SubscriptionGate>,
    );

    await waitFor(() =>
      expect(screen.getByText(/Subscribe to unlock/i)).toBeTruthy(),
    );
    // The actionable dashboard is NOT rendered behind the wall.
    expect(screen.queryByText(ACTIONABLE)).toBeNull();
    // The CTA routes to /pricing.
    const cta = screen.getByRole("link", { name: /plan|subscribe/i });
    expect(cta.getAttribute("href")).toBe("/pricing");
  });

  it("renders the real dashboard for a paid subscriber", async () => {
    fetchEntitlementMock.mockResolvedValue({
      active_paid: true,
      plan: { id: "pro", status: "active" },
      requiresSubscription: true,
    });

    render(
      <SubscriptionGate>
        <div>{ACTIONABLE}</div>
      </SubscriptionGate>,
    );

    await waitFor(() => expect(screen.getByText(ACTIONABLE)).toBeTruthy());
    expect(screen.queryByText(/Subscribe to unlock/i)).toBeNull();
  });

  it("renders the dashboard for everyone when the gate is disabled", async () => {
    fetchEntitlementMock.mockResolvedValue({
      active_paid: false,
      plan: { id: "free", status: "active" },
      requiresSubscription: false,
    });

    render(
      <SubscriptionGate>
        <div>{ACTIONABLE}</div>
      </SubscriptionGate>,
    );

    await waitFor(() => expect(screen.getByText(ACTIONABLE)).toBeTruthy());
    expect(screen.queryByText(/Subscribe to unlock/i)).toBeNull();
  });
});
