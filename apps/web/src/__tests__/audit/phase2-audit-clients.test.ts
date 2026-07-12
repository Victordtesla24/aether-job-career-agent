/**
 * Phase-2 audit — typed API client coverage for defects D4–D9.
 *
 * Covers the client functions added while fixing the wireframe↔backend
 * wiring audit defects:
 *  - D5: downloadResume (POST /resumes/{id}/download, 501 until Phase 3)
 *  - D6: createStory / updateStory (POST/PUT /stories)
 *  - D7: fetchApplication (GET /applications/{id})
 *  - D9: fetchConversion (GET /analytics/conversion)
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversionSchema, fetchConversion } from "../../lib/api/analytics";
import { fetchApplication } from "../../lib/api/applications";
import { ApiError } from "../../lib/api/client";
import { downloadResume } from "../../lib/api/resumes";
import { createStory, updateStory } from "../../lib/api/stories";

const STORY_FIXTURE = {
  id: "cstory12345678901234567890",
  title: "Cut deploy time by 80%",
  situation: "Slow release cycle",
  task: "Speed up CI/CD",
  action: "Introduced parallel pipelines",
  result: "Deploys dropped from 40m to 8m",
  metrics: { minutesSaved: 32 },
  tags: ["devops", "ci"],
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-01T00:00:00Z",
};

const APPLICATION_FIXTURE = {
  id: "capp123456789012345678901",
  jobId: "cjob123456789012345678901",
  resumeId: "cres123456789012345678901",
  status: "submitted",
  coverLetter: "Dear hiring team...",
  jobTitle: "DevOps Engineer",
  company: "Atlassian",
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-02T00:00:00Z",
};

const CONVERSION_FIXTURE = {
  period: "all",
  found_to_applied: 18.4,
  applied_to_screened: 25.0,
  screened_to_interview: 14.7,
  interview_to_offer: 12.5,
};

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("D6 — story bank create/edit clients", () => {
  it("createStory POSTs the payload and returns a validated story", async () => {
    const fetchMock = mockFetchOnce(STORY_FIXTURE, 200);
    const story = await createStory(
      {
        title: STORY_FIXTURE.title,
        situation: STORY_FIXTURE.situation,
        task: STORY_FIXTURE.task,
        action: STORY_FIXTURE.action,
        result: STORY_FIXTURE.result,
        tags: STORY_FIXTURE.tags,
      },
      { token: "tok" },
    );
    expect(story.id).toBe(STORY_FIXTURE.id);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/stories");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((init as RequestInit).body))).toMatchObject({
      title: STORY_FIXTURE.title,
      tags: ["devops", "ci"],
    });
  });

  it("updateStory PUTs a partial payload to /stories/{id}", async () => {
    const fetchMock = mockFetchOnce({ ...STORY_FIXTURE, title: "Updated" }, 200);
    const story = await updateStory(STORY_FIXTURE.id, { title: "Updated" }, { token: "tok" });
    expect(story.title).toBe("Updated");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain(`/stories/${STORY_FIXTURE.id}`);
    expect((init as RequestInit).method).toBe("PUT");
  });

  it("createStory rejects when the response fails validation", async () => {
    mockFetchOnce({ nonsense: true }, 200);
    await expect(
      createStory(
        { title: "x", situation: "s", task: "t", action: "a", result: "r" },
        { token: "tok" },
      ),
    ).rejects.toThrow();
  });
});

describe("D5 — resume download client", () => {
  it("downloadResume surfaces the backend 501 as ApiError with status", async () => {
    mockFetchOnce({ detail: "PDF export ships in Phase 3", resume_id: "r1" }, 501);
    try {
      await downloadResume("r1", { token: "tok" });
      expect.unreachable("expected downloadResume to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(501);
    }
  });

  it("downloadResume calls GET /resumes/{id}/download", async () => {
    const pdfBlob = new Blob(["%PDF-fake"], { type: "application/pdf" });
    const fetchMock = mockFetchOnce(pdfBlob, 200);
    await downloadResume("r1", { token: "tok" });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/resumes/r1/download");
    // GET request — no explicit method set
  });
});

describe("D7 — application detail client", () => {
  it("fetchApplication returns a validated application", async () => {
    const fetchMock = mockFetchOnce(APPLICATION_FIXTURE, 200);
    const app = await fetchApplication(APPLICATION_FIXTURE.id, { token: "tok" });
    expect(app.status).toBe("submitted");
    expect(app.coverLetter).toContain("Dear hiring team");
    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain(`/applications/${APPLICATION_FIXTURE.id}`);
  });

  it("fetchApplication rejects on an invalid status enum", async () => {
    mockFetchOnce({ ...APPLICATION_FIXTURE, status: "bogus" }, 200);
    await expect(fetchApplication(APPLICATION_FIXTURE.id, { token: "tok" })).rejects.toThrow();
  });
});

describe("D9 — conversion analytics client", () => {
  it("fetchConversion validates and returns the four stage rates", async () => {
    const fetchMock = mockFetchOnce(CONVERSION_FIXTURE, 200);
    const conv = await fetchConversion("30d", { token: "tok" });
    expect(ConversionSchema.parse(conv)).toEqual(CONVERSION_FIXTURE);
    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/analytics/conversion?period=30d");
  });

  it("fetchConversion rejects malformed payloads", async () => {
    mockFetchOnce({ period: "all", found_to_applied: "not-a-number" }, 200);
    await expect(fetchConversion("all", { token: "tok" })).rejects.toThrow();
  });
});
