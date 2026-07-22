// @vitest-environment jsdom
/**
 * ML-settings-001 (MEDIUM) — an oversized field validation error renders the
 * raw, unwrapped Pydantic error payload instead of a bounded, human-readable
 * message (uat/reports/evidence/models-live/screens/misc-dashboard/
 * TESTING-OUTCOME-REPORT.md).
 *
 * `SettingsProfile.fullName` is server-validated to `max_length=120`
 * (apps/api/app/routers/workspaces.py) and correctly 422s for a longer
 * value. But `apps/web/src/lib/api/client.ts`'s `apiRequest()` builds
 * `ApiError.message` as `` `${method} ${path} failed (${status}): ${detail}` ``
 * where `detail` is the RAW response body text — for a FastAPI/Pydantic 422
 * that body is a structured JSON array that echoes the FULL invalid input
 * back verbatim, e.g.
 *   {"detail":[{"type":"string_too_long", …, "input":"XXXX…(5000 chars)…",
 *              "ctx":{"max_length":120}}]}
 * `settings-client.tsx`'s `save()` catch block (`setError(e.message)`)
 * renders that raw string directly in an unwrapped
 * `<p className="… text-sm text-red-300">` banner — no truncation, no
 * bounding — which is the same raw text that balloons
 * `document.documentElement.scrollWidth` to ~50,600px on the live page (the
 * OVERFLOW half of this finding is a live Playwright repro,
 * e2e/ml-fe-polish.spec.ts, since jsdom performs no real CSS layout). This
 * spec pins the OTHER half, independent of any CSS fix: the error MESSAGE
 * ITSELF must be a bounded, human-readable string — never the raw
 * echoed-input Pydantic payload.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";

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

const SETTINGS = {
  profile: {
    fullName: "Jamie Rivera",
    email: "jamie@example.com",
    targetRole: "Staff Engineer",
    location: "Sydney, AU",
  },
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
    spendUsedUsd: 0.07,
    spendCapUsd: 15.0,
    periodEnd: "2026-08-01T00:00:00Z",
  },
};

afterEach(() => {
  cleanup();
  fetchSettingsMock.mockReset();
  fetchCareerDataMock.mockReset();
  saveSettingsMock.mockReset();
  fetchSubscriptionMock.mockReset();
});

describe("ML-settings-001: oversized-field 422 must render a bounded, human-readable error", () => {
  it("does not echo the raw oversized input back into the error banner, and keeps the message bounded", async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS);
    fetchCareerDataMock.mockResolvedValue(CAREER_DATA);
    fetchSubscriptionMock.mockResolvedValue(SUBSCRIPTION);

    const hugeValue = "X".repeat(5000);
    const rawPydanticBody = JSON.stringify({
      detail: [
        {
          type: "string_too_long",
          loc: ["body", "profile", "fullName"],
          msg: "String should have at most 120 characters",
          input: hugeValue,
          ctx: { max_length: 120 },
        },
      ],
    });
    // Exactly the shape apps/web/src/lib/api/client.ts's apiRequest() builds
    // from a real 422 response (method + path + raw response body text).
    saveSettingsMock.mockRejectedValue(
      new ApiError(`PUT /workspaces/settings failed (422): ${rawPydanticBody}`, 422),
    );

    render(<SettingsPage />);

    const fullNameInput = await screen.findByTestId("settings-fullname");
    fireEvent.change(fullNameInput, { target: { value: hugeValue } });
    fireEvent.click(screen.getByTestId("save-settings-btn"));

    await waitFor(() => expect(saveSettingsMock).toHaveBeenCalled());

    const errorEl = await waitFor(() => {
      const el = document.querySelector("p.text-sm.text-red-300");
      if (!el) throw new Error("error banner not rendered yet");
      return el;
    });

    const text = errorEl.textContent ?? "";
    expect(
      text.includes(hugeValue.slice(0, 200)),
      `error banner echoes the raw ${hugeValue.length}-char invalid input back to the user — ` +
        `rendered text is ${text.length} chars, starting: ${JSON.stringify(text.slice(0, 80))}`,
    ).toBe(false);
    expect(
      text.length,
      `error banner text is ${text.length} chars — expected a bounded, human-readable ` +
        "message (<=300 chars), not the raw Pydantic validation payload",
    ).toBeLessThanOrEqual(300);
    // Not just bounded — also honestly informative (mentions the actual
    // field), not just an opaque truncated fragment of the raw JSON.
    expect(text.toLowerCase()).toMatch(/full name|120|too long|shorter/);
  });
});
