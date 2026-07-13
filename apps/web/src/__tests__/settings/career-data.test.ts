/**
 * GAP-P4-047 — Settings → Career Data wiring.
 *
 * The reviewer rejected the prior fix because the Settings screen never called
 * `POST /workspaces/career-data/refresh` (the "Sync now" button was a fake
 * setTimeout spinner) and had no inputs for GitHub / portfolio / LinkedIn.
 * These tests pin the now-real client + payload logic that the page uses:
 *   - `fetchCareerData` / `refreshCareerData` hit the correct endpoints, and
 *   - `buildRefreshPayload` / `deriveInputs` map the form ↔ server contract.
 *
 * RED before the fix: `fetchCareerData`, `refreshCareerData` and the
 * `components/settings/career-data` helpers did not exist.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildRefreshPayload,
  careerStatusLabel,
  careerStatusStyle,
  deriveInputs,
  parseGithubUsername,
  bySource,
} from "../../components/settings/career-data";
import {
  fetchCareerData,
  refreshCareerData,
  type CareerData,
} from "../../lib/api/workspaces";

const CAREER_FIXTURE: CareerData = {
  sources: [
    {
      source: "github",
      status: "ok",
      url: "https://github.com/Victordtesla24",
      summary: "GitHub profile: Victor — 12 public repos.",
      error: null,
      lastSynced: "2026-07-13T10:00:00",
    },
    {
      source: "portfolio",
      status: "error",
      url: "https://forgotten-mistory.web.app/",
      summary: null,
      error: "Could not reach the portfolio site.",
      lastSynced: "2026-07-13T10:00:00",
    },
    {
      source: "linkedin",
      status: "empty",
      url: null,
      summary: null,
      error: "LinkedIn has no public profile API available to this app (ADR D-0031).",
      lastSynced: null,
    },
  ],
  linkedinNote: "Paste your LinkedIn summary below.",
};

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.fn().mockResolvedValue(response);
}

describe("career-data API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchCareerData GETs /workspaces/career-data with the bearer token", async () => {
    const fetchMock = mockFetchOnce(CAREER_FIXTURE);
    vi.stubGlobal("fetch", fetchMock);

    const data = await fetchCareerData({ token: "tok-abc" });

    expect(data.sources).toHaveLength(3);
    expect(bySource(data, "github")?.url).toBe("https://github.com/Victordtesla24");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/workspaces/career-data");
    expect((init as RequestInit).method ?? "GET").toBe("GET");
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer tok-abc" });
  });

  it("refreshCareerData POSTs the inputs to /workspaces/career-data/refresh", async () => {
    const fetchMock = mockFetchOnce(CAREER_FIXTURE);
    vi.stubGlobal("fetch", fetchMock);

    await refreshCareerData(
      { githubUsername: "octocat", portfolioUrl: "https://x.dev", linkedinSummary: "hi" },
      { token: "t" },
    );

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/workspaces/career-data/refresh");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      githubUsername: "octocat",
      portfolioUrl: "https://x.dev",
      linkedinSummary: "hi",
    });
  });
});

describe("buildRefreshPayload", () => {
  const base = { githubUsername: "  octocat  ", portfolioUrl: "  https://x.dev ", linkedinSummary: "pasted text" };

  it("always sends trimmed github username and portfolio url once loaded", () => {
    const payload = buildRefreshPayload(base, false);
    expect(payload.githubUsername).toBe("octocat");
    expect(payload.portfolioUrl).toBe("https://x.dev");
  });

  it("omits linkedinSummary when the textarea was not edited (reuse stored value)", () => {
    const payload = buildRefreshPayload(base, false);
    expect(payload).not.toHaveProperty("linkedinSummary");
  });

  it("includes linkedinSummary when the textarea was edited — even when cleared", () => {
    expect(buildRefreshPayload(base, true).linkedinSummary).toBe("pasted text");
    expect(buildRefreshPayload({ ...base, linkedinSummary: "" }, true).linkedinSummary).toBe("");
  });

  // GAP-P4-047 Wave-1 reviewer regression: the Settings page fetches career
  // data asynchronously on mount, so there is a window where `career` is
  // still null and `careerInputs` is still the component's un-populated
  // default (empty strings) — even though the server already has
  // githubUsername/portfolioUrl configured. Pressing "Sync now" in that
  // window must never submit those defaults as an implicit clear.
  describe("omits githubUsername/portfolioUrl when career data has not loaded yet (career === null)", () => {
    const unloadedInputs = { githubUsername: "", portfolioUrl: "", linkedinSummary: "" };

    it("sends nothing for github/portfolio while `loaded` is false, even with server-configured values present", () => {
      // `loaded` mirrors the page's `career !== null` check — false here
      // reproduces clicking "Sync now" before the initial GET resolves.
      const payload = buildRefreshPayload(unloadedInputs, false, false);
      expect(payload).not.toHaveProperty("githubUsername");
      expect(payload).not.toHaveProperty("portfolioUrl");
      expect(payload).toEqual({});
    });

    it("never sends empty-string github/portfolio as an implicit clear before load", () => {
      const payload = buildRefreshPayload(unloadedInputs, false, false);
      expect(payload.githubUsername).not.toBe("");
      expect(payload.portfolioUrl).not.toBe("");
    });

    it("resumes sending trimmed github/portfolio once `loaded` is true (default) — unchanged post-load behaviour", () => {
      const payload = buildRefreshPayload(base, false);
      expect(payload.githubUsername).toBe("octocat");
      expect(payload.portfolioUrl).toBe("https://x.dev");
    });
  });
});

describe("parseGithubUsername / deriveInputs", () => {
  it("extracts the username from a github profile url", () => {
    expect(parseGithubUsername("https://github.com/Victordtesla24")).toBe("Victordtesla24");
    expect(parseGithubUsername("https://github.com/octocat?tab=repos")).toBe("octocat");
    expect(parseGithubUsername(null)).toBe("");
    expect(parseGithubUsername("not-a-url")).toBe("");
  });

  it("derives editable inputs from server state (linkedin stays blank)", () => {
    const inputs = deriveInputs(CAREER_FIXTURE);
    expect(inputs.githubUsername).toBe("Victordtesla24");
    expect(inputs.portfolioUrl).toBe("https://forgotten-mistory.web.app/");
    expect(inputs.linkedinSummary).toBe("");
  });

  it("derives empty inputs from a null payload", () => {
    expect(deriveInputs(null)).toEqual({ githubUsername: "", portfolioUrl: "", linkedinSummary: "" });
  });
});

describe("careerStatusLabel / careerStatusStyle", () => {
  it("maps every known status to a human label", () => {
    expect(careerStatusLabel("ok")).toBe("Synced");
    expect(careerStatusLabel("error")).toBe("Error");
    expect(careerStatusLabel("empty")).toBe("Not provided");
    expect(careerStatusLabel("not_configured")).toBe("Not configured");
    expect(careerStatusLabel("weird")).toBe("weird");
  });

  it("returns a style string for known and unknown statuses", () => {
    expect(careerStatusStyle("ok")).toContain("aether-green");
    expect(careerStatusStyle("error")).toContain("red");
    expect(careerStatusStyle("nope")).toBe(careerStatusStyle("not_configured"));
  });
});
