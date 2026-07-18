/**
 * AGT-STORY — Story Bank API client coverage.
 * Verifies the enriched story schema, the stats endpoint, and the star-toggle
 * helper (which must merge existing evidence metrics with the control flag).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteStory,
  fetchStories,
  fetchStoryStats,
  StorySchema,
  toggleStar,
  type Story,
} from "../../lib/api/stories";

const ENRICHED_STORY = {
  id: "cstory00000000000000000001",
  title: "Reduced ATO automation effort by 92%",
  situation: "Manual regression",
  task: "Lead automation",
  action: "Built CI framework",
  result: "92% effort reduction",
  metrics: { effortReductionPercent: 92 },
  tags: ["Delivery"],
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-01T00:00:00Z",
  category: "Delivery",
  impact: "92% impact",
  starred: false,
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

describe("Story Bank client — enrichment", () => {
  it("StorySchema parses enriched display fields", () => {
    const story = StorySchema.parse(ENRICHED_STORY);
    expect(story.category).toBe("Delivery");
    expect(story.impact).toBe("92% impact");
    expect(story.starred).toBe(false);
  });

  it("StorySchema still parses a legacy payload without enrichment", () => {
    const { category, impact, starred, ...legacy } = ENRICHED_STORY;
    void { category, impact, starred };
    const story = StorySchema.parse(legacy);
    expect(story.category).toBeUndefined();
    expect(story.title).toBe(ENRICHED_STORY.title);
  });

  it("fetchStories returns enriched stories from GET /stories", async () => {
    const fetchMock = mockFetchOnce([ENRICHED_STORY]);
    const stories = await fetchStories({ token: "tok" });
    expect(stories).toHaveLength(1);
    expect(stories[0]!.category).toBe("Delivery");
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/stories");
  });

  it("fetchStories accepts an optional category query param", async () => {
    const fetchMock = mockFetchOnce([ENRICHED_STORY]);
    const stories = await fetchStories({ token: "tok", category: "Delivery" });
    expect(stories).toHaveLength(1);
    const url = String(fetchMock.mock.calls[0]![0]);
    expect(url).toContain("/stories?category=Delivery");
  });

  it("fetchStoryStats parses the stats payload from GET /stories/stats", async () => {
    const fetchMock = mockFetchOnce({
      total: 34,
      quantified: 30,
      starred: 4,
      categories: 3,
    });
    const stats = await fetchStoryStats({ token: "tok" });
    expect(stats.total).toBe(34);
    expect(stats.quantified).toBe(30);
    expect(stats.starred).toBe(4);
    expect(stats.categories).toBe(3);
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/stories/stats");
  });

  it("toggleStar PUTs merged metrics with the flipped control flag", async () => {
    const story: Story = { ...ENRICHED_STORY, starred: false };
    const fetchMock = mockFetchOnce({ ...ENRICHED_STORY, starred: true });
    const updated = await toggleStar(story, { token: "tok" });
    expect(updated.starred).toBe(true);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain(`/stories/${story.id}`);
    expect((init as RequestInit).method).toBe("PUT");
    const body = JSON.parse(String((init as RequestInit).body));
    // evidence metric preserved + control flag flipped on
    expect(body.metrics.effortReductionPercent).toBe(92);
    expect(body.metrics.__starred).toBe(true);
  });
});

describe("Story Bank client — DELETE response handling (MV-story-bank-004)", () => {
  it("drains the empty 204 response body instead of leaving it unread", async () => {
    // Chromium reports a fetch() whose 204 body stream is never read/cancelled
    // as a client-observed net::ERR_ABORTED on the network panel, even though
    // the server completed the request correctly. Every other response branch
    // in apiRequest() already consumes the body (`.json()` or the error-path
    // `.text()`); the 204 fast path must do the same.
    const textSpy = vi.fn().mockResolvedValue("");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      text: textSpy,
      json: vi.fn(),
    });
    vi.stubGlobal("fetch", fetchMock);

    await deleteStory("cstory00000000000000000001", { token: "tok" });

    expect(textSpy).toHaveBeenCalledTimes(1);
  });
});
