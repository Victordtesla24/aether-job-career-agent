// @vitest-environment jsdom
/**
 * /dashboard/settings — Notifications (MV-settings-001) and Job Board
 * Integrations Sync (MV-settings-002).
 *
 * MV-settings-001: the three Notifications toggles are rendered with a fixed
 * `value` and `onChange={() => undefined}` — they look interactive (a real
 * switch with aria-checked) but are dead no-ops; no backend field for
 * notification preferences exists anywhere in apps/api. The approved fix
 * makes them honestly non-interactive (disabled) with a visible disclosure,
 * instead of a fake-looking interactive control.
 *
 * MV-settings-002: "Sync All" and the 5 per-row "Sync" buttons under Job
 * Board Integrations only flip local `syncing` state via `setTimeout` — zero
 * network calls (confirmed by production evidence: zero requests fired).
 * Per-source sync is not something the real backend (ScoutAgent.run(), which
 * always fans out over every registered adapter) can honestly perform, so
 * the approved fix removes the per-row buttons and wires "Sync All" to the
 * real POST /agents/scout/run endpoint via runScoutAgent(query, location).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

const runScoutAgentMock = vi.fn();
vi.mock("../../../../lib/api/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/jobs")>();
  return {
    ...actual,
    runScoutAgent: (...args: unknown[]) => runScoutAgentMock(...args),
  };
});

// The SubscriptionGate (not used directly here, but settings-client pulls in
// billing which some helpers reference) reads the live pathname.
const usePathnameMock = vi.fn(() => "/dashboard/settings" as string | null);
vi.mock("next/navigation", () => ({
  usePathname: () => usePathnameMock(),
}));

// eslint-disable-next-line import/first
import SettingsPage from "../page";

const SETTINGS = {
  profile: { fullName: "Jamie Rivera", email: "jamie@example.com", targetRole: "Staff Engineer", location: "Sydney, AU" },
  resume: { activeFile: "resume.pdf", uploadedAt: "2026-07-01", versions: 3 },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [
    { name: "Greenhouse", status: "connected", detail: "12 jobs discovered · last sync 2026-07-17T10:00 UTC" },
    { name: "Ashby", status: "connected", detail: "8 jobs discovered · last sync 2026-07-16T09:00 UTC" },
  ],
  connectedAccounts: [],
};

const SETTINGS_MISSING_PROFILE = {
  ...SETTINGS,
  profile: { ...SETTINGS.profile, targetRole: "", location: "   " },
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
  fetchEntitlementMock.mockReset();
  fetchPlansMock.mockReset();
  runScoutAgentMock.mockReset();
  usePathnameMock.mockReturnValue("/dashboard/settings");
  window.localStorage.clear();
});

// syncAllJobBoards() resolves a real bearer token via lib/api/client's
// getToken() before calling the (mocked) runScoutAgent — an authenticated
// session must exist in jsdom's localStorage for that resolution to succeed
// at all (mirrors the same "aether_token" stubbing convention used by
// src/components/__tests__/user-menu.test.tsx).
function stubAuthenticatedSession() {
  window.localStorage.setItem("aether_token", "jwt-123");
}

async function renderOnNotifications() {
  render(<SettingsPage />);
  await waitFor(() => screen.getByTestId("settings-nav-notifications"));
  fireEvent.click(screen.getByTestId("settings-nav-notifications"));
  await waitFor(() => screen.getByTestId("settings-notifications"));
}

async function renderOnIntegrations() {
  render(<SettingsPage />);
  await waitFor(() => screen.getByTestId("settings-nav-integrations"));
  fireEvent.click(screen.getByTestId("settings-nav-integrations"));
  await waitFor(() => screen.getByTestId("settings-integrations"));
}

describe("SettingsPage — Notifications toggles are honestly inert (MV-settings-001)", () => {
  it("renders all three notification toggle buttons as disabled with aria-disabled", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnNotifications();

    for (const testId of ["toggle-notif-approvals", "toggle-notif-apps", "toggle-notif-digest"]) {
      const btn = screen.getByTestId(testId) as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      expect(btn.getAttribute("aria-disabled")).toBe("true");
    }
  });

  it("is genuinely inert via a disabled control (not merely a no-op click handler on an enabled-looking switch)", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnNotifications();

    const approvals = screen.getByTestId("toggle-notif-approvals") as HTMLButtonElement;
    const apps = screen.getByTestId("toggle-notif-apps") as HTMLButtonElement;
    const digest = screen.getByTestId("toggle-notif-digest") as HTMLButtonElement;

    // The contract requires the *mechanism* of inertness to be a real
    // `disabled` HTML attribute on the control — not just an onChange that
    // happens to be a no-op while the button still presents as an active,
    // clickable switch (which is exactly today's dishonest defect: it LOOKS
    // interactive with no visible cue that nothing happens).
    expect(approvals.disabled).toBe(true);
    expect(apps.disabled).toBe(true);
    expect(digest.disabled).toBe(true);

    expect(approvals.getAttribute("aria-checked")).toBe("true");
    expect(apps.getAttribute("aria-checked")).toBe("true");
    expect(digest.getAttribute("aria-checked")).toBe("false");

    fireEvent.click(approvals);
    fireEvent.click(apps);
    fireEvent.click(digest);

    // Still exactly the fixed inert display values — clicking a disabled
    // control must never flip it.
    expect(approvals.getAttribute("aria-checked")).toBe("true");
    expect(apps.getAttribute("aria-checked")).toBe("true");
    expect(digest.getAttribute("aria-checked")).toBe("false");
  });

  it("discloses honestly that notification preferences are not yet functional/saved", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnNotifications();

    const notice = screen.getByTestId("notifications-unavailable-notice");
    expect(notice.getAttribute("role")).toBe("status");
    expect(notice.textContent ?? "").toMatch(/not (yet )?available|isn't (built|saved|functional)|coming soon/i);
  });
});

describe("SettingsPage — Job Board Sync is real, not a fake setTimeout (MV-settings-002)", () => {
  it("removes the per-row individual Sync buttons entirely", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnIntegrations();

    expect(screen.queryByTestId("sync-greenhouse")).toBeNull();
    expect(screen.queryByTestId("sync-ashby")).toBeNull();
    expect(screen.getByTestId("sync-all-btn")).toBeTruthy();
  });

  it("wires Sync All to the real runScoutAgent(query, location) endpoint and re-fetches settings on success", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    runScoutAgentMock.mockResolvedValue(undefined);
    stubAuthenticatedSession();

    await renderOnIntegrations();

    // fetchSettings already resolved once at mount.
    await waitFor(() => expect(fetchSettingsMock).toHaveBeenCalledTimes(1));

    const syncAllBtn = screen.getByTestId("sync-all-btn") as HTMLButtonElement;
    expect(syncAllBtn.disabled).toBe(false);
    fireEvent.click(syncAllBtn);

    await waitFor(() => expect(runScoutAgentMock).toHaveBeenCalledTimes(1));
    const call = runScoutAgentMock.mock.calls[0];
    expect(call[0]).toBe(SETTINGS.profile.targetRole);
    expect(call[1]).toBe(SETTINGS.profile.location);

    // A real refetch, proving this isn't a fake local state flip.
    await waitFor(() => expect(fetchSettingsMock.mock.calls.length).toBeGreaterThan(1));

    await waitFor(() => screen.getByTestId("jobboard-sync-notice"));
    const notice = screen.getByTestId("jobboard-sync-notice");
    expect(notice.getAttribute("role")).toBe("status");
    expect(notice.textContent ?? "").toMatch(/sync/i);
    expect(notice.textContent ?? "").not.toMatch(/error|fail/i);
  });

  it("shows an honest error (not a fake success) when runScoutAgent rejects, and does not get stuck in a Syncing state", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    runScoutAgentMock.mockRejectedValue(new Error("scout run failed"));
    stubAuthenticatedSession();

    await renderOnIntegrations();

    const syncAllBtn = screen.getByTestId("sync-all-btn") as HTMLButtonElement;
    fireEvent.click(syncAllBtn);

    await waitFor(() => expect(runScoutAgentMock).toHaveBeenCalledTimes(1));
    await waitFor(() => screen.getByTestId("jobboard-sync-error"));

    const errEl = screen.getByTestId("jobboard-sync-error");
    expect(errEl.getAttribute("role")).toBe("alert");
    expect(errEl.textContent ?? "").not.toMatch(/synced ✓/i);

    // Not stuck showing a stale "Syncing…" anywhere in the section.
    const section = screen.getByTestId("settings-integrations");
    expect(section.textContent ?? "").not.toMatch(/syncing…/i);
  });

  it("disables Sync All when the profile has no target role or location to search with", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS_MISSING_PROFILE);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnIntegrations();

    const syncAllBtn = screen.getByTestId("sync-all-btn") as HTMLButtonElement;
    expect(syncAllBtn.disabled).toBe(true);

    fireEvent.click(syncAllBtn);
    expect(runScoutAgentMock).not.toHaveBeenCalled();
  });
});
