// @vitest-environment jsdom
/**
 * /dashboard/settings — Notifications (MV-settings-001, superseded by
 * GOLD-MASTER-V2 §4/G-B+G-O) and Job Board Integrations Sync (MV-settings-002).
 *
 * MV-settings-001 (original): the three Notifications toggles were rendered
 * with a fixed `value` and `onChange={() => undefined}` — they looked
 * interactive (a real switch with aria-checked) but were dead no-ops. That
 * fix made them honestly non-interactive (`disabled`) with a "Coming soon"
 * disclosure.
 *
 * GOLD-MASTER-V2 §4/G-B+G-O (this fix): even an honestly-disabled toggle
 * labelled "Coming soon" is still a shipped placeholder, which §4 classifies
 * as a BLOCKER ("No feature may remain in any partial state at exit") and
 * G-O forbids ("no routes render placeholders, 'Coming Soon', or planned
 * states"). Per-category notification PREFERENCES (approval-request pushes,
 * status-change pushes, a scheduled weekly send) have no backend at all —
 * building that now would be a new subsystem, out of scope this late in the
 * campaign. But a REAL, already-shipped delivery path does exist:
 * `NotificationAgent` (apps/api/app/agents/notification_agent.py), wired to
 * `POST /agents/run` and runnable today from the Agents screen
 * (`/dashboard/agents`) — it composes a real digest (status changes + new
 * scored matches) from the user's own data and queues an approval-gated send
 * to their connected Gmail. The three fake toggles are removed; the tab now
 * honestly says there are no preferences to save yet and links to the real
 * on-demand agent instead of promising unbuilt push/schedule behavior.
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
  profile: { fullName: "Jamie Rivera", email: "jamie@example.com", targetRole: "Staff Engineer", location: "Sydney, AU" , hasAvatar: false, avatarRevision: null },
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

describe("SettingsPage — Notifications tab has no stub toggles or 'Coming soon' copy (GOLD-MASTER-V2 G-B/G-O)", () => {
  it("renders none of the three former notification preference toggles", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnNotifications();

    expect(screen.queryByTestId("toggle-notif-approvals")).toBeNull();
    expect(screen.queryByTestId("toggle-notif-apps")).toBeNull();
    expect(screen.queryByTestId("toggle-notif-digest")).toBeNull();
  });

  it("contains no 'Coming soon' (or equivalent placeholder) text anywhere in the tab", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnNotifications();

    const section = screen.getByTestId("settings-notifications");
    const text = (section.textContent ?? "").toLowerCase();
    expect(text).not.toContain("coming soon");
    expect(text).not.toMatch(/in planning|planned\b/);
  });

  it("honestly points to the real on-demand Notification Agent instead of promising unbuilt push/schedule preferences", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    await renderOnNotifications();

    const notice = screen.getByTestId("notifications-info-notice");
    expect(notice.getAttribute("role")).toBe("status");
    const text = notice.textContent ?? "";
    expect(text).toMatch(/notification agent/i);
    expect(text).toMatch(/on-demand|any time|connected gmail/i);

    // Real link to the screen where the agent actually runs — not a dead end.
    const link = screen.getByRole("link", { name: /notification agent/i });
    expect(link.getAttribute("href")).toBe("/dashboard/agents");
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
