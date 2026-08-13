// @vitest-environment jsdom
/**
 * U2a — Settings → Resume Management: honest baseline-document copy (R-F1/
 * R-F3/MON-012).
 *
 * Before this change the file picker only accepted `.pdf`/`.txt`/`.md`
 * (silently letting a `.docx` through the browser dialog's "All files"
 * escape hatch straight into the old undecodable-garbage path), the panel
 * said nothing about the uploaded file being an immutable baseline or about
 * pre-existing uploads having no stored original, and a rejected upload's
 * real reason was thrown away in favour of a truncated raw-JSON blob. These
 * tests pin the fixed contract: the file input accepts exactly the four
 * formats the backend genuinely reads, the helper text states the honest
 * baseline/format facts, the panel surfaces whether the active resume's
 * original bytes are stored, and a rejected upload shows the server's real
 * detail sentence verbatim.
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
const fetchPlansMock = vi.fn();
vi.mock("../../../../lib/api/billing", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/billing")>();
  return {
    ...actual,
    fetchSubscription: (...args: unknown[]) => fetchSubscriptionMock(...args),
    fetchPlans: (...args: unknown[]) => fetchPlansMock(...args),
  };
});

// eslint-disable-next-line import/first
import SettingsClient from "../settings-client";
// eslint-disable-next-line import/first
import type { SettingsPayload } from "../../../../lib/api/workspaces";

const CAREER_DATA = { sources: [], linkedinNote: "" };
const SUBSCRIPTION = {
  plan: { id: "free", name: "Free", modelTier: "basic" },
  status: null,
  interval: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  quota: { runsUsed: 0, runsAllowed: 5, spendUsedUsd: 0, spendCapUsd: 1.0, periodEnd: null },
};

// F-3 refix: annotated with the real `SettingsPayload` type (rather than
// left to structural inference from the literal below) so `activeFile`'s
// genuine `string | null` shape is checked here too — that's what let the
// no-resume test fall back to a suppressing `null as unknown as string`
// cast in the first place.
function settingsWith(originalStored: boolean): SettingsPayload {
  return {
    profile: { fullName: "Jamie Rivera", email: "jamie@example.com", targetRole: "Staff Engineer", location: "Sydney, AU" },
    resume: { activeFile: "resume.pdf", uploadedAt: "2026-08-01", versions: 2, originalStored },
    portfolio: { url: null, cadence: null, lastSynced: null },
    agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 80 },
    integrations: [],
    connectedAccounts: [],
  };
}

const originalFetch = global.fetch;

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  fetchSubscriptionMock.mockReset();
  fetchPlansMock.mockReset();
  global.fetch = originalFetch;
  window.localStorage.clear();
});

describe("U2a: file picker accepts every format the backend genuinely reads", () => {
  it("accept attribute is exactly .pdf,.docx,.txt,.md", async () => {
    fetchSettingsMock.mockResolvedValue(settingsWith(true));
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsClient supportEmail={null} supportPhone={null} />);

    const input = await waitFor(() => screen.getByTestId("resume-upload-input"));
    expect(input.getAttribute("accept")).toBe(".pdf,.docx,.txt,.md");
  });
});

describe("U2a: honest baseline helper text", () => {
  it("states supported formats, immutable-baseline behaviour, and the pre-existing-upload gap", async () => {
    fetchSettingsMock.mockResolvedValue(settingsWith(true));
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsClient supportEmail={null} supportPhone={null} />);

    const help = await waitFor(() => screen.getByTestId("resume-baseline-help-text"));
    const text = help.textContent ?? "";
    expect(text).toMatch(/PDF/);
    expect(text).toMatch(/Word|\.docx/);
    expect(text).toMatch(/plain text|\.txt/);
    expect(text).toMatch(/immutable baseline/i);
    expect(text).toMatch(/tailoring never alters it/i);
    expect(text).toMatch(/re-upload/i);
    // F-1 refix: no engine preserves format on download today — the copy
    // must not claim re-uploading "enables" that as an already-live
    // behaviour, only that it stores bytes for a future engine.
    expect(text).not.toMatch(/enable format preservation/i);
    expect(text).toMatch(/still renders in the aether template/i);
  });
});

describe("U2a: original-stored badge derived from the real API field", () => {
  it("shows the positive badge when the active resume's original bytes are stored", async () => {
    fetchSettingsMock.mockResolvedValue(settingsWith(true));
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsClient supportEmail={null} supportPhone={null} />);

    const badge = await waitFor(() => screen.getByTestId("resume-original-stored-badge"));
    expect(badge.textContent).toMatch(/Original stored/);
  });

  it("shows the honest re-upload prompt when no original bytes are stored (pre-U2a upload)", async () => {
    fetchSettingsMock.mockResolvedValue(settingsWith(false));
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsClient supportEmail={null} supportPhone={null} />);

    const badge = await waitFor(() => screen.getByTestId("resume-original-stored-badge"));
    expect(badge.textContent).toMatch(/original not stored/i);
    expect(badge.textContent).toMatch(/re-upload/i);
    // F-1 refix: must NOT claim re-uploading "enables format preservation" —
    // downloads still render in the Aether template regardless of upload age.
    expect(badge.textContent).not.toMatch(/enable format preservation/i);
  });

  it("renders no badge at all when there is no active resume yet", async () => {
    const settings = settingsWith(false);
    settings.resume.activeFile = null;
    fetchSettingsMock.mockResolvedValue(settings);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    render(<SettingsClient supportEmail={null} supportPhone={null} />);

    await waitFor(() => screen.getByTestId("resume-upload-input"));
    expect(screen.queryByTestId("resume-original-stored-badge")).toBeNull();
  });
});

describe("U2a: upload rejection surfaces the server's real detail verbatim", () => {
  it("shows the exact 422 detail sentence, not a truncated raw-JSON blob", async () => {
    fetchSettingsMock.mockResolvedValue(settingsWith(true));
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);
    window.localStorage.setItem("aether_token", "test-token");

    const detail =
      "Unsupported file format. Aether reads PDF (.pdf), Word (.docx) and " +
      "plain-text (.txt/.md) résumés; this file is not a readable document " +
      "in any of those formats.";
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/resumes/upload")) {
        return new Response(JSON.stringify({ detail }), { status: 422 });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    render(<SettingsClient supportEmail={null} supportPhone={null} />);
    const input = await waitFor(() => screen.getByTestId("resume-upload-input"));

    const file = new File(["not really a docx"], "resume.docx", {
      type: "application/octet-stream",
    });
    fireEvent.change(input, { target: { files: [file] } });

    const notice = await waitFor(() => screen.getByTestId("resume-upload-notice"));
    expect(notice.textContent).toBe(detail);
    expect(notice.textContent).not.toMatch(/^Upload failed \(422\):/);
  });
});
