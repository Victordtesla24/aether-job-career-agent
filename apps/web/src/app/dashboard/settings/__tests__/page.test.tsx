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

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
});

describe("SettingsPage — Privacy & Compliance tab", () => {
  it("does not claim a self-service export/delete-all-data feature that does not exist", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toMatch(/export or delete all data at any time/i);
  });

  it("describes the actual self-service (correction, Gmail disconnect) vs admin-mediated (full export/delete) split", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    render(<SettingsPage />);

    await waitFor(() => screen.getByTestId("settings-nav-privacy"));
    fireEvent.click(screen.getByTestId("settings-nav-privacy"));

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toMatch(/gmail/i);
    expect(bodyText).toMatch(/no self-service/i);
    expect(bodyText).toMatch(/contact/i);
  });
});
