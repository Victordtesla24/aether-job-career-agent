/**
 * D11 — application tracker submit flow: the client can mark a draft
 * application as submitted with the real apply URL, and Application detail
 * exposes `applyUrl` (the job's real posting URL) for the "Apply on company
 * site" link.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApplicationSchema,
  fetchApplication,
  submitApplication,
} from "../../lib/api/applications";

const APP_FIXTURE = {
  id: "capp1234567890123456789012",
  jobId: "cjob1234567890123456789012",
  resumeId: "cres1234567890123456789012",
  status: "draft",
  coverLetter: "Dear Hiring Manager,",
  jobTitle: "Senior Technical Delivery Lead",
  company: "Culture Amp",
  applyUrl: "https://job-boards.greenhouse.io/cultureamp/jobs/123",
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-10T00:00:00Z",
};

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.fn().mockResolvedValue(response);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("application applyUrl + submit", () => {
  it("Application schema accepts the real applyUrl field", () => {
    const parsed = ApplicationSchema.parse(APP_FIXTURE);
    expect(parsed.applyUrl).toBe(APP_FIXTURE.applyUrl);
  });

  it("Application schema tolerates a missing applyUrl (older rows)", () => {
    const withoutUrl: Record<string, unknown> = { ...APP_FIXTURE };
    delete withoutUrl.applyUrl;
    const parsed = ApplicationSchema.parse(withoutUrl);
    expect(parsed.applyUrl ?? null).toBeNull();
  });

  it("fetchApplication surfaces applyUrl for the detail panel", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(APP_FIXTURE));
    const detail = await fetchApplication(APP_FIXTURE.id, { token: "tok" });
    expect(detail.applyUrl).toContain("greenhouse.io");
  });

  it("submitApplication POSTs the applied URL and returns the updated app", async () => {
    const fetchMock = mockFetchOnce({ ...APP_FIXTURE, status: "submitted" });
    vi.stubGlobal("fetch", fetchMock);
    const updated = await submitApplication(
      APP_FIXTURE.id,
      APP_FIXTURE.applyUrl,
      { token: "tok" },
    );
    expect(updated.status).toBe("submitted");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain(`/applications/${APP_FIXTURE.id}/submit`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      applied_url: APP_FIXTURE.applyUrl,
    });
  });
});
