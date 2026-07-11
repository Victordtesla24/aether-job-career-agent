/**
 * AGT-STORY — Story Bank API client coverage.
 * Verifies the enriched story schema, the stats endpoint, and the star-toggle
 * helper (which must merge existing evidence metrics with the control flag).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
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
  voiceMatch: 96,
  usedInResumes: 6,
  interviewAnswers: 3,
  usedThisMonth: 2,
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
    expect(story.voiceMatch).toBe(96);
    expect(story.starred).toBe(false);
  });

  it("StorySchema still parses a legacy payload without enrichment", () => {
    const { category, impact, voiceMatch, usedInResumes, interviewAnswers, usedThisMonth, starred, ...legacy } =
      ENRICHED_STORY;
    void { category, impact, voiceMatch, usedInResumes, interviewAnswers, usedThisMonth, starred };
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

  it("fetchStoryStats parses the stats payload from GET /stories/stats", async () => {
    const fetchMock = mockFetchOnce({
      total: 34,
      quantified: 30,
      usedThisMonth: 11,
      voiceMatchAvg: 92,
    });
    const stats = await fetchStoryStats({ token: "tok" });
    expect(stats.total).toBe(34);
    expect(stats.quantified).toBe(30);
    expect(stats.voiceMatchAvg).toBe(92);
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
