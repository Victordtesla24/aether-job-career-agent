/**
 * P2-S02 — typed jobs API client (fetch + zod validation).
 *
 * RED first: `src/lib/api/jobs.ts` does not exist yet.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchJob,
  fetchJobs,
  runScoutAgent,
  toggleSaveJob,
} from "../../lib/api/jobs";

const JOB_FIXTURE = {
  id: "cjob123456789012345678901",
  title: "Senior Software Engineer (Python)",
  company: "Canva",
  location: "Sydney NSW",
  remote: false,
  description: "Build the backend platform.",
  source: "seek",
  sourceUrl: "https://www.seek.com.au/job/82650341",
  status: "discovered",
  fitScore: null,
  atsScore: null,
  saved: false,
};

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.fn().mockResolvedValue(response);
}

describe("jobs API client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetchOnce([JOB_FIXTURE]));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchJobs returns an array of validated jobs", async () => {
    const jobs = await fetchJobs(undefined, { token: "test-token" });
    expect(Array.isArray(jobs)).toBe(true);
    expect(jobs).toHaveLength(1);
    expect(jobs[0]!.title).toBe(JOB_FIXTURE.title);
    expect(jobs[0]!.source).toBe("seek");
  });

  it("fetchJobs sends the bearer token and filter query params", async () => {
    const fetchMock = mockFetchOnce([JOB_FIXTURE]);
    vi.stubGlobal("fetch", fetchMock);
    await fetchJobs({ status: "discovered", saved: true }, { token: "tok-abc" });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/jobs?");
    expect(String(url)).toContain("status=discovered");
    expect(String(url)).toContain("saved=true");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-abc",
    });
  });

  it("fetchJob returns a single validated job", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(JOB_FIXTURE));
    const job = await fetchJob(JOB_FIXTURE.id, { token: "t" });
    expect(job.id).toBe(JOB_FIXTURE.id);
  });

  it("toggleSaveJob returns the updated job", async () => {
    vi.stubGlobal("fetch", mockFetchOnce({ ...JOB_FIXTURE, saved: true }));
    const job = await toggleSaveJob(JOB_FIXTURE.id, { token: "t" });
    expect(job.saved).toBe(true);
  });

  it("runScoutAgent resolves on a 202 response", async () => {
    vi.stubGlobal("fetch", mockFetchOnce({ status: "accepted" }, 202));
    await expect(
      runScoutAgent("software engineer", "Sydney", { token: "t" }),
    ).resolves.toBeUndefined();
  });

  it("fetchJobs rejects when the response fails validation", async () => {
    vi.stubGlobal("fetch", mockFetchOnce([{ nonsense: true }]));
    await expect(fetchJobs(undefined, { token: "t" })).rejects.toThrow();
  });
});
