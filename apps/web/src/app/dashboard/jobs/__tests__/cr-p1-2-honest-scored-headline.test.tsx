// @vitest-environment jsdom
/**
 * CR-P1-2 (RUN-20260818T0223Z, commercial-readiness audit
 * `docs/delivery/evidence/RUN-20260818T0223Z/COMMERCIAL-READINESS/job-discovery/audit.md`)
 *
 * The Jobs page header subtitle was a fixed, unconditional string —
 * "Every role below was discovered by your agents and scored against your
 * résumé." — rendered verbatim no matter how many jobs were actually
 * scored. On a real run this produced "610 discovered · 0 scored against
 * your résumé · 610 not yet scored" one line below a headline that had just
 * claimed scoring already happened for every role. That is a truth-claim
 * contradiction on the single highest-traffic screen in the product.
 *
 * The fix derives the subtitle (`jobs-header-subtitle`) from the SAME
 * `stats` object the honest footnote (`jobs-stats`) already uses, so the two
 * lines can never disagree:
 *   - 0 jobs discovered            -> no scoring claim at all
 *   - jobs discovered, 0 scored    -> honestly says none are scored yet
 *   - some scored, not all         -> honest partial count
 *   - all discovered jobs scored   -> the original claim, now true
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const getToken = vi.fn();
const apiBaseUrl = vi.fn();
const fetchScoutSources = vi.fn();
const fetchSourceAvailability = vi.fn();
const fetchMe = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...(args as [string])),
  apiBaseUrl: () => apiBaseUrl(),
  getToken: () => getToken(),
  ApiError: class ApiError extends Error {},
  describeApiError: (e: unknown, fallback: string) =>
    e instanceof Error ? e.message : fallback,
}));

vi.mock("../../../../lib/api/jobs", () => ({
  fetchScoutSources: (...args: unknown[]) => fetchScoutSources(...args),
  fetchSourceAvailability: (...args: unknown[]) => fetchSourceAvailability(...args),
}));

vi.mock("../../../../lib/api/admin", () => ({
  fetchMe: (...args: unknown[]) => fetchMe(...args),
}));

// eslint-disable-next-line import/first
import JobsPage from "../page";

function job(id: string, fitScore: number | null) {
  return {
    id,
    title: `Role ${id}`,
    company: "Acme",
    location: "Sydney NSW",
    remote: false,
    description: "",
    source: "greenhouse",
    sourceUrl: `https://greenhouse.io/job/${id}`,
    status: "matched",
    fitScore,
    saved: false,
    createdAt: "2026-08-01T00:00:00Z",
  };
}

function installApiRequestMock(jobs: ReturnType<typeof job>[]) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith("/jobs?")) return jobs;
    if (/^\/jobs\/[^/]+\/insights$/.test(path)) {
      return Promise.reject(new Error("insights not fetched in this fixture"));
    }
    if (path === "/agents") return [{ name: "scout", last_run: "2026-08-01T00:00:00Z" }];
    throw new Error(`unexpected apiRequest(${path})`);
  });
}

beforeEach(() => {
  getToken.mockResolvedValue("test-token");
  apiBaseUrl.mockReturnValue("http://test.local");
  fetchScoutSources.mockResolvedValue([]);
  fetchSourceAvailability.mockResolvedValue([]);
  fetchMe.mockResolvedValue({
    id: "u-1",
    email: "subscriber@example.com",
    name: "Subscriber",
    isAdmin: false,
    targetRole: "Staff Engineer",
    location: "Austin, TX",
  });
});

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  fetchScoutSources.mockReset();
  fetchSourceAvailability.mockReset();
  fetchMe.mockReset();
});

async function renderWithJobs(jobs: ReturnType<typeof job>[]) {
  installApiRequestMock(jobs);
  render(<JobsPage />);
  await waitFor(() => expect(screen.getByTestId("jobs-stats")).toBeTruthy());
  return {
    stats: screen.getByTestId("jobs-stats"),
    subtitle: screen.getByTestId("jobs-header-subtitle"),
  };
}

describe("CR-P1-2 — Jobs page headline never claims scoring that has not happened", () => {
  it("does NOT claim jobs were 'scored against your résumé' when 0 of 610 are scored", async () => {
    const jobs = Array.from({ length: 610 }, (_, i) => job(`job-${i}`, null));
    const { stats, subtitle } = await renderWithJobs(jobs);

    // The honest footnote must show the real split.
    expect(stats.textContent).toMatch(/610 discovered/);
    expect(stats.textContent).toMatch(/0 scored against your résumé/);

    // The headline directly above it must not assert the scoring claim the
    // footnote itself contradicts.
    expect(subtitle.textContent).not.toBe(
      "Every role below was discovered by your agents and scored against your résumé.",
    );
    expect(subtitle.textContent).not.toMatch(/and scored against your résumé/);
  });

  it("states the real discovered count honestly when nothing is scored yet", async () => {
    const jobs = Array.from({ length: 610 }, (_, i) => job(`job-${i}`, null));
    const { subtitle } = await renderWithJobs(jobs);
    expect(subtitle.textContent).toMatch(/610/);
    expect(subtitle.textContent).toMatch(/not.*scored|none.*scored|0 scored/i);
  });

  it("renders the original claim once every discovered job IS scored", async () => {
    const jobs = [job("a", 82), job("b", 71), job("c", 90)];
    const { subtitle } = await renderWithJobs(jobs);
    expect(subtitle.textContent).toBe(
      "Every role below was discovered by your agents and scored against your résumé.",
    );
  });

  it("renders an honest partial claim when some, but not all, jobs are scored", async () => {
    const jobs = [job("a", 82), job("b", null), job("c", null)];
    const { subtitle } = await renderWithJobs(jobs);
    expect(subtitle.textContent).not.toBe(
      "Every role below was discovered by your agents and scored against your résumé.",
    );
    expect(subtitle.textContent).toMatch(/\b1\b/);
    expect(subtitle.textContent).toMatch(/\b3\b/);
    expect(subtitle.textContent).toMatch(/scored/);
  });

  it("makes no scoring claim at all when zero jobs have been discovered", async () => {
    const { subtitle } = await renderWithJobs([]);
    expect(subtitle.textContent).not.toMatch(/scored against your résumé/);
  });
});
