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
vi.mock("../../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/billing")>();
  return {
    ...actual,
    fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args),
    openBillingPortal: (...args: unknown[]) => openBillingPortalMock(...args),
  };
});

// eslint-disable-next-line import/first
import SettingsPage from "../page";

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

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  fetchSubscriptionMock.mockReset();
  openBillingPortalMock.mockReset();
});

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
});
