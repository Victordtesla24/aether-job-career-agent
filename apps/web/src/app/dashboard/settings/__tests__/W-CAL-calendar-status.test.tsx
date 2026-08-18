// @vitest-environment jsdom
/**
 * W-CAL (GOLD-MASTER V4 §10 / ADR-CALENDAR-V4) — the Connected Accounts panel
 * must render the REAL status the backend sent.
 *
 * Before this fix the badge was the literal string "Connected", hardcoded, for
 * every row regardless of `status`. That was harmless only while every row the
 * backend could emit really was connected. Google Calendar breaks that
 * assumption: it can honestly report `scope_missing` (the user consented to
 * Gmail and declined Calendar) or `needs_reauth` (the grant was revoked), and
 * a green "Connected" pill over either of those is exactly the fabricated
 * status GM2-EMAIL-001 was raised for.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchSettingsMock = vi.fn();
const fetchCareerDataMock = vi.fn();
const saveSettingsMock = vi.fn();
vi.mock("../../../../lib/api/workspaces", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/workspaces")>();
  return {
    ...actual,
    fetchSettings: (...args: unknown[]) => fetchSettingsMock(...args),
    fetchCareerData: (...args: unknown[]) => fetchCareerDataMock(...args),
    saveSettings: (...args: unknown[]) => saveSettingsMock(...args),
  };
});

const fetchSubscriptionMock = vi.fn();
vi.mock("../../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/billing")>();
  return { ...actual, fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args) };
});

import SettingsPage from "../page";

const BASE_SETTINGS = {
  profile: {
    fullName: "Jamie Rivera",
    email: "jamie@example.com",
    targetRole: "Staff Engineer",
    location: "Sydney, AU",
    hasAvatar: false,
    avatarRevision: null,
  },
  resume: { activeFile: "resume.pdf", uploadedAt: "2026-07-01", versions: 3 },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [],
  connectedAccounts: [],
};

const SUBSCRIPTION = {
  plan: { id: "pro", name: "Pro", modelTier: "advanced" },
  status: "active",
  interval: "month",
  currentPeriodEnd: "2026-08-01T00:00:00Z",
  cancelAtPeriodEnd: false,
  quota: {
    runsUsed: 15,
    runsAllowed: 100,
    spendUsedUsd: 0.07,
    spendCapUsd: 15.0,
    periodEnd: "2026-08-01T00:00:00Z",
  },
};

function renderWithAccounts(
  connectedAccounts: Array<{ name: string; status: string; detail: string }>,
) {
  fetchSettingsMock.mockResolvedValue({ ...BASE_SETTINGS, connectedAccounts });
  fetchCareerDataMock.mockResolvedValue({ sources: [], linkedinNote: "" });
  fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
  render(<SettingsPage />);
}

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  saveSettingsMock.mockReset();
  fetchSubscriptionMock.mockReset();
});

describe("W-CAL: Connected Accounts renders the real status, never a hardcoded 'Connected'", () => {
  it("shows an unconnected Google Calendar as NOT connected", async () => {
    renderWithAccounts([
      { name: "Google (Gmail)", status: "connected", detail: "Connected as me@gmail.com" },
      {
        name: "Google Calendar",
        status: "scope_missing",
        detail:
          "Google Calendar access was not granted for this account — Gmail still " +
          "works, but no calendar event was created. Reconnect your Google account " +
          "from Settings and tick the calendar permission to enable this.",
      },
    ]);

    const badge = await screen.findByTestId("account-status-scope_missing");
    expect(badge.textContent).toBe("Not connected");
    expect(badge.textContent).not.toContain("Connected as");
    // The Gmail row is genuinely connected and must still say so.
    expect(screen.getByTestId("account-status-connected").textContent).toBe("Connected");
  });

  it("shows a revoked Google Calendar grant as needing reconnection", async () => {
    renderWithAccounts([
      {
        name: "Google Calendar",
        status: "needs_reauth",
        detail: "Google Calendar authorization expired or was revoked.",
      },
    ]);

    const badge = await screen.findByTestId("account-status-needs_reauth");
    expect(badge.textContent).toBe("Reconnect needed");
    expect(screen.queryByTestId("account-status-connected")).toBeNull();
  });

  it("does not fall back to green for an unrecognised status", async () => {
    renderWithAccounts([
      { name: "Google Calendar", status: "unavailable", detail: "Could not be verified." },
    ]);

    const badge = await screen.findByTestId("account-status-unavailable");
    expect(badge.textContent).toBe("Unverified");
    expect(badge.className).not.toContain("aether-green");
  });
});
