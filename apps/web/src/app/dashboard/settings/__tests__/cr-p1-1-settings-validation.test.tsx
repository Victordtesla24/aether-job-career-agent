// @vitest-environment jsdom
/**
 * CR-P1-1 (commercial-readiness audit, RUN-20260818T0223Z) — a brand-new
 * subscriber's very first view of /dashboard/settings (Profile tab) showed
 * red "required" validation errors on Target role and Location before the
 * user had touched anything, because `targetRole`/`location` are empty at
 * registration (docs/delivery/evidence/RUN-20260818T0223Z/
 * COMMERCIAL-READINESS/profile-screening/audit.md, P1 finding).
 *
 * Root cause: the `validation` useMemo in settings-client.tsx computed
 * errors straight off `profile` state with no "touched"/"submitted" gating,
 * and `Input` rendered the red border + message unconditionally whenever
 * `error` was a non-empty string. This spec pins the fix: the red state
 * must render as an ordinary pristine input until the user has interacted
 * with that field (blur) or attempted to save the form — and must still
 * render honestly once either of those has happened. The underlying
 * validation logic (and the real save-blocking behaviour) is unchanged and
 * is deliberately re-asserted here too, so this fix cannot silently regress
 * into hiding a genuine failed-save error.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

// eslint-disable-next-line import/first
import SettingsPage from "../page";

// A brand-new subscriber: fullName/email came from signup, but targetRole
// and location are genuinely blank — exactly the state
// `03-settings-get.txt` in the audit evidence captured immediately after
// registration.
const FRESH_SUBSCRIBER_SETTINGS = {
  profile: {
    fullName: "New Subscriber",
    email: "new.subscriber@example.com",
    targetRole: "",
    location: "",
    hasAvatar: false,
    avatarRevision: null,
  },
  resume: { activeFile: null, uploadedAt: null, versions: 0 },
  portfolio: { url: null, cadence: null, lastSynced: null },
  agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
  integrations: [],
  connectedAccounts: [],
};
const CAREER_DATA = { sources: [], linkedinNote: "" };
const SUBSCRIPTION = {
  plan: { id: "free", name: "Free", modelTier: "light" },
  status: null,
  interval: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  quota: {
    runsUsed: 0,
    runsAllowed: 5,
    spendUsedUsd: 0,
    spendCapUsd: 1.0,
    periodEnd: "2026-09-01T00:00:00Z",
  },
};

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  saveSettingsMock.mockReset();
  fetchSubscriptionMock.mockReset();
});

describe("CR-P1-1: Settings Profile tab does not show validation errors before the user has done anything", () => {
  it("renders empty targetRole/location as ordinary pristine inputs on first load — no red border, no error text", async () => {
    fetchSettingsMock.mockResolvedValue(FRESH_SUBSCRIBER_SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);

    const targetRoleInput = await screen.findByTestId("settings-targetrole");
    const locationInput = await screen.findByTestId("settings-location");

    // No red border styling on either untouched, empty required field...
    expect(targetRoleInput.className).not.toMatch(/border-red-500/);
    expect(locationInput.className).not.toMatch(/border-red-500/);
    expect(targetRoleInput.getAttribute("aria-invalid")).toBe("false");
    expect(locationInput.getAttribute("aria-invalid")).toBe("false");

    // ...and no "required" error text printed underneath either field.
    const profileSection = screen.getByTestId("settings-profile");
    expect(profileSection.textContent ?? "").not.toMatch(/target role is required/i);
    expect(profileSection.textContent ?? "").not.toMatch(/location is required/i);
  });

  it("shows the real error once the user blurs an invalid field they touched", async () => {
    fetchSettingsMock.mockResolvedValue(FRESH_SUBSCRIBER_SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);

    const targetRoleInput = await screen.findByTestId("settings-targetrole");
    const locationInput = screen.getByTestId("settings-location");

    // The user clicks into Target role and leaves it blank again (blur).
    fireEvent.focus(targetRoleInput);
    fireEvent.blur(targetRoleInput);

    await waitFor(() => {
      expect(targetRoleInput.className).toMatch(/border-red-500/);
    });
    expect(targetRoleInput.getAttribute("aria-invalid")).toBe("true");
    const profileSection = screen.getByTestId("settings-profile");
    expect(profileSection.textContent ?? "").toMatch(/target role is required/i);

    // Location was never touched — it must still be pristine.
    expect(locationInput.className).not.toMatch(/border-red-500/);
    expect(locationInput.getAttribute("aria-invalid")).toBe("false");
    expect(profileSection.textContent ?? "").not.toMatch(/location is required/i);
  });

  it("clears the error the moment the touched field becomes valid", async () => {
    fetchSettingsMock.mockResolvedValue(FRESH_SUBSCRIBER_SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);

    const targetRoleInput = await screen.findByTestId("settings-targetrole");
    fireEvent.focus(targetRoleInput);
    fireEvent.blur(targetRoleInput);
    await waitFor(() => expect(targetRoleInput.className).toMatch(/border-red-500/));

    fireEvent.change(targetRoleInput, { target: { value: "Staff Engineer" } });

    await waitFor(() => {
      expect(targetRoleInput.className).not.toMatch(/border-red-500/);
    });
    expect(targetRoleInput.getAttribute("aria-invalid")).toBe("false");
  });

  it("shows every invalid field's error after a real failed save attempt, and still blocks the API call (validation logic unchanged)", async () => {
    fetchSettingsMock.mockResolvedValue(FRESH_SUBSCRIBER_SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    render(<SettingsPage />);

    const targetRoleInput = await screen.findByTestId("settings-targetrole");
    const locationInput = screen.getByTestId("settings-location");

    // Neither field has been touched — attempt to save immediately, exactly
    // like a user who opens the page and clicks Save without editing.
    fireEvent.click(screen.getByTestId("save-settings-btn"));

    await waitFor(() => {
      expect(targetRoleInput.className).toMatch(/border-red-500/);
    });
    expect(locationInput.className).toMatch(/border-red-500/);
    const profileSection = screen.getByTestId("settings-profile");
    expect(profileSection.textContent ?? "").toMatch(/target role is required/i);
    expect(profileSection.textContent ?? "").toMatch(/location is required/i);

    // The save must still be blocked client-side — no PUT ever fired while
    // required fields are invalid (the actual validation/blocking logic is
    // untouched by this fix; only the premature DISPLAY changed).
    expect(saveSettingsMock).not.toHaveBeenCalled();
    expect(screen.getByText(/fix the highlighted fields before saving/i)).toBeTruthy();
  });
});
