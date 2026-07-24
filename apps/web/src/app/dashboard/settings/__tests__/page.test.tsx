// @vitest-environment jsdom
/**
 * /dashboard/settings page — Privacy & Compliance tab (GAP-P6-DOCS-002).
 *
 * The privacy tab copy claimed "You can export or delete all data at any
 * time" — no self-service export/delete endpoint exists in the codebase
 * (only Gmail disconnect via DELETE /api/emails/accounts/{id} and in-app
 * profile correction are real, self-service features; full data export or
 * account deletion is admin-mediated only). This mirrors the same fix
 * already applied to the public /privacy-policy page.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";

const fetchSettingsMock = vi.fn();
const fetchCareerDataMock = vi.fn();
vi.mock("../../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchSettings: (...args: unknown[]) => fetchSettingsMock(...args),
    fetchCareerData: (...args: unknown[]) => fetchCareerDataMock(...args),
  };
});

const fetchSubscriptionMock = vi.fn();
const openBillingPortalMock = vi.fn();
const fetchEntitlementMock = vi.fn();
const fetchPlansMock = vi.fn();
vi.mock("../../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/billing")>();
  return {
    ...actual,
    fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args),
    openBillingPortal: (...args: unknown[]) => openBillingPortalMock(...args),
    fetchEntitlement: (...args: unknown[]) => fetchEntitlementMock(...args),
    fetchPlans: (...args: unknown[]) => fetchPlansMock(...args),
  };
});

const PLANS_RESPONSE = {
  currency: "AUD",
  gstIncluded: true,
  plans: [
    {
      id: "free", name: "Free", modelTier: "light", runsPerMonth: 5,
      monthly: { total: 0, gst: 0, net: 0 }, annual: null,
      features: [], purchasable: false,
    },
    {
      id: "pro", name: "Pro", modelTier: "advanced", runsPerMonth: 100,
      monthly: { total: 39, gst: 3.55, net: 35.45 },
      annual: { total: 359, gst: 32.64, net: 326.36 },
      features: [], purchasable: true,
    },
  ],
};

// The SubscriptionGate reads the live pathname to allowlist /dashboard/settings.
const usePathnameMock = vi.fn(() => "/dashboard/settings" as string | null);
vi.mock("next/navigation", () => ({
  usePathname: () => usePathnameMock(),
}));

// eslint-disable-next-line import/first
import SettingsPage from "../page";
// eslint-disable-next-line import/first
import { SubscriptionGate } from "../../../../components/subscription-gate";

const SETTINGS = {
  profile: { fullName: "Jamie Rivera", email: "jamie@example.com", targetRole: "Staff Engineer", location: "Sydney, AU" },
  resume: { activeFile: "resume.pdf", uploadedAt: "2026-07-01", versions: 3 },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [],
  connectedAccounts: [],
};

const CAREER_DATA = { sources: [], linkedinNote: "" };

const SUBSCRIPTION = {
  plan: { id: "pro", name: "Pro", modelTier: "advanced" },
  status: "active",
  interval: "month",
  currentPeriodEnd: "2026-08-01T00:00:00Z",
  cancelAtPeriodEnd: false,
  quota: {
    runsUsed: 15,
    runsAllowed: 100,
    spendUsedUsd: 0.074688,
    spendCapUsd: 15.0,
    periodEnd: "2026-08-01T00:00:00Z",
  },
};

// Some tests below replace `window.location` with a plain href-capturing stub
// (to observe a redirect to the billing portal) via Object.defineProperty —
// jsdom's `window` persists across `it()`s within this file, so without
// restoring the real descriptor afterward, every later test would inherit a
// `window.location` with no working `search` (breaking the
// ?checkout=success tests below, which read the real URL).
const originalLocationDescriptor = Object.getOwnPropertyDescriptor(window, "location");

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  fetchSubscriptionMock.mockReset();
  openBillingPortalMock.mockReset();
  fetchEntitlementMock.mockReset();
  fetchPlansMock.mockReset();
  usePathnameMock.mockReturnValue("/dashboard/settings");
  vi.unstubAllEnvs();
  if (originalLocationDescriptor) {
    Object.defineProperty(window, "location", originalLocationDescriptor);
  }
  window.history.replaceState(null, "", "/dashboard/settings");
});

const FREE_SUBSCRIPTION = {
  plan: { id: "free", name: "Free", modelTier: "basic" },
  status: null,
  interval: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  quota: {
    runsUsed: 3,
    runsAllowed: 5,
    spendUsedUsd: 0.42,
    spendCapUsd: 1.0,
    periodEnd: "2026-08-01T00:00:00Z",
  },
};

describe("SettingsPage — Privacy & Compliance tab", () => {
  it("does not claim a self-service export/delete-all-data feature that does not exist", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/export or delete all data at any time/i);
  });

  it("describes the actual self-service (correction, Gmail disconnect) vs admin-mediated (full export/delete) split", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/gmail/i);
    expect(bodyText).toMatch(/no self-service/i);
    expect(bodyText).toMatch(/contact/i);
  });
});

describe("SettingsPage — Billing & Subscription (MV-settings-003, MV-pricing-003)", () => {
  it("renders the real plan, status and run/spend quota from GET /billing/subscription", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    render(<SettingsPage />);

    await waitFor(() => {
      expect(fetchSubscriptionMock).toHaveBeenCalled();
    });
    await waitFor(() => screen.getByTestId("billing-plan-name"));

    expect(screen.getByTestId("billing-plan-name").textContent).toContain("Pro");
    expect(screen.getByTestId("billing-plan-status").textContent).toContain("active");
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("15");
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("100");
  });

  it("PAY-R3-06: renders the plan's price and the real next-billing (Stripe renewal) date, not just the usage-quota reset date", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("billing-plan-price"));
    expect(screen.getByTestId("billing-plan-price").textContent).toMatch(/\$39.*\/\s*month/i);

    await waitFor(() => screen.getByTestId("billing-next-date"));
    // SUBSCRIPTION.currentPeriodEnd = "2026-08-01T00:00:00Z" — rendered
    // day-first in en-AU (W-E quality sweep), never the runtime default.
    expect(screen.getByTestId("billing-next-date").textContent).toMatch(
      new Date("2026-08-01T00:00:00Z").toLocaleDateString("en-AU"),
    );

    // Distinct from the usage-quota reset date — both are shown, not conflated.
    const section = screen.getByTestId("settings-billing");
    expect(section.textContent ?? "").toMatch(/usage quota resets/i);
  });

  it("PAY-R3-06: falls back to an honest 'Price unavailable' / 'No upcoming charge' — never a fabricated $0 or placeholder — when data is missing", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(FREE_SUBSCRIPTION);
    fetchPlansMock.mockRejectedValue(new Error("plans catalog unavailable"));
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("billing-plan-price"));
    expect(screen.getByTestId("billing-plan-price").textContent).toContain("Price unavailable");
    expect(screen.getByTestId("billing-next-date").textContent).toContain("No upcoming charge");
  });

  it("wires 'Manage subscription' to the real POST /billing/portal endpoint and follows the returned URL", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockResolvedValue({ portalUrl: "https://billing.stripe.com/session/abc" });
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { set href(v: string) { hrefSetter(v); }, get href() { return ""; } },
    });

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => {
      expect(openBillingPortalMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(hrefSetter).toHaveBeenCalledWith("https://billing.stripe.com/session/abc");
    });
  });

  it("shows an honest contact-fallback message (no fake success) when the account has no Stripe billing profile (409)", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockRejectedValue(
      new ApiError("POST /billing/portal failed (409): No billing account yet", 409),
    );

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => screen.getByTestId("manage-subscription-message"));
    const msg = screen.getByTestId("manage-subscription-message").textContent ?? "";
    expect(msg).not.toMatch(/success/i);
    expect(msg.toLowerCase()).toMatch(/billing profile|contact|support/);
  });

  it("includes the support phone in the contact-fallback message when AETHER_SUPPORT_PHONE is configured (409)", async () => {
    vi.stubEnv("AETHER_SUPPORT_PHONE", "+61 433 224 556");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockRejectedValue(
      new ApiError("POST /billing/portal failed (409): No billing account yet", 409),
    );

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => screen.getByTestId("manage-subscription-message"));
    const msg = screen.getByTestId("manage-subscription-message").textContent ?? "";
    expect(msg).toContain("+61 433 224 556");
  });

  it("does not mention a phone number in the contact-fallback message when AETHER_SUPPORT_PHONE is unset (409)", async () => {
    vi.stubEnv("AETHER_SUPPORT_PHONE", "");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    openBillingPortalMock.mockRejectedValue(
      new ApiError("POST /billing/portal failed (409): No billing account yet", 409),
    );

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("manage-subscription-btn"));
    fireEvent.click(screen.getByTestId("manage-subscription-btn"));

    await waitFor(() => screen.getByTestId("manage-subscription-message"));
    const msg = screen.getByTestId("manage-subscription-message").textContent ?? "";
    expect(msg).not.toMatch(/\+61 433 224 556/);
    expect(msg).not.toMatch(/or call/i);
  });
});

describe("Settings billing reachable through the SubscriptionGate for a FREE account (MV-pricing-003, MV-settings-003, MV-mobile-dashboard-002)", () => {
  it("a gated free user on /dashboard/settings sees their plan + Manage subscription, NOT the full-page paywall", async () => {
    // A free/unsubscribed account: the gate would normally paywall the whole
    // dashboard, but account management (view plan/quota + cancel) must stay
    // reachable. Rendered exactly as production wraps it: <SubscriptionGate>.
    fetchEntitlementMock.mockResolvedValue({
      active_paid: false,
      plan: { id: "free", status: "active" },
      requiresSubscription: true,
    });
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(FREE_SUBSCRIPTION);
    usePathnameMock.mockReturnValue("/dashboard/settings");

    render(
      <SubscriptionGate>
        <SettingsPage />
      </SubscriptionGate>,
    );

    // Billing section renders the real free plan + a working Manage button…
    await waitFor(() => screen.getByTestId("billing-plan-name"));
    expect(screen.getByTestId("billing-plan-name").textContent).toContain("Free");
    expect(screen.getByTestId("manage-subscription-btn")).toBeTruthy();
    expect(screen.getByTestId("billing-quota-runs").textContent).toContain("5");
    // …and the paywall never replaces it.
    expect(screen.queryByTestId("subscription-paywall")).toBeNull();
    expect(screen.queryByText(/Subscribe to unlock/i)).toBeNull();
  });
});

describe("SettingsPage — post-checkout success banner (PAY-R3-05)", () => {
  it("shows an 'activating' banner (never a fabricated success) when the subscription hasn't confirmed the upgrade yet, then flips to a real success message once it does", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?checkout=success");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    // First resolve still shows the OLD (free) plan — webhook hasn't landed —
    // then a manual "Refresh now" click confirms the real upgrade.
    fetchSubscriptionMock
      .mockResolvedValueOnce(FREE_SUBSCRIPTION)
      .mockResolvedValueOnce(SUBSCRIPTION);

    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("checkout-success-banner"));
    expect(screen.getByTestId("checkout-success-banner").textContent ?? "").toMatch(
      /being activated/i,
    );
    // The URL is stripped so a refresh doesn't re-show the banner.
    expect(window.location.search).toBe("");

    fireEvent.click(screen.getByTestId("checkout-banner-refresh"));

    await waitFor(() => {
      const banner = screen.getByTestId("checkout-success-banner");
      expect(banner.textContent ?? "").toMatch(/subscription active/i);
    });
    expect(screen.getByTestId("checkout-success-banner").textContent ?? "").toContain("Pro");
  });

  it("shows the success banner immediately (no 'activating' delay) when the subscription already confirms an active paid plan on first load", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?checkout=success");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("checkout-success-banner").textContent ?? "").toMatch(
        /subscription active.*welcome to pro/i,
      );
    });
  });

  it("shows no banner at all on a plain visit with no ?checkout param", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("billing-plan-name"));
    expect(screen.queryByTestId("checkout-success-banner")).toBeNull();
  });

  it("is dismissible", async () => {
    window.history.replaceState(null, "", "/dashboard/settings?checkout=success");
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchPlansMock.mockResolvedValue(PLANS_RESPONSE);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);
    await waitFor(() => screen.getByTestId("checkout-success-banner"));
    fireEvent.click(screen.getByTestId("checkout-banner-dismiss"));
    expect(screen.queryByTestId("checkout-success-banner")).toBeNull();
  });
});
