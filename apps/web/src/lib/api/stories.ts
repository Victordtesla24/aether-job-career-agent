/** Typed story bank API client (P2-S09). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const StorySchema = z.object({
  id: z.string(),
  title: z.string(),
  situation: z.string(),
  task: z.string(),
  action: z.string(),
  result: z.string(),
  metrics: z.record(z.unknown()).nullish(),
  tags: z.array(z.string()),
  createdAt: z.string(),
  updatedAt: z.string(),
  // Display enrichment derived server-side from the persisted row (stable
  // across refreshes). Optional so older payloads still parse.
  category: z.string().optional(),
  impact: z.string().nullish(),
  voiceMatch: z.number().optional(),
  usedInResumes: z.number().optional(),
  interviewAnswers: z.number().optional(),
  usedThisMonth: z.number().optional(),
  starred: z.boolean().optional(),
});

export type Story = z.infer<typeof StorySchema>;

export const StoryStatsSchema = z.object({
  total: z.number(),
  quantified: z.number(),
  usedThisMonth: z.number(),
  voiceMatchAvg: z.number(),
});

export type StoryStats = z.infer<typeof StoryStatsSchema>;

export async function fetchStories(options: RequestOptions = {}): Promise<Story[]> {
  return z.array(StorySchema).parse(await apiRequest<unknown>("/stories", options));
}

export async function fetchStoryStats(options: RequestOptions = {}): Promise<StoryStats> {
  return StoryStatsSchema.parse(await apiRequest<unknown>("/stories/stats", options));
}

export async function runStoryExtractor(
  options: RequestOptions = {},
): Promise<{ created: number; dropped: string[] }> {
  return apiRequest("/agents/story-extractor/run", { ...options, method: "POST" });
}

export async function deleteStory(id: string, options: RequestOptions = {}): Promise<void> {
  await apiRequest<void>(`/stories/${id}`, { ...options, method: "DELETE" });
}

/** Manual story creation payload (POST /stories) — audit defect D6. */
export interface StoryInput {
  title: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  metrics?: Record<string, unknown> | null;
  tags?: string[];
}

export async function createStory(input: StoryInput, options: RequestOptions = {}): Promise<Story> {
  return StorySchema.parse(
    await apiRequest<unknown>("/stories", { ...options, method: "POST", body: input }),
  );
}

export async function updateStory(
  id: string,
  input: Partial<StoryInput>,
  options: RequestOptions = {},
): Promise<Story> {
  return StorySchema.parse(
    await apiRequest<unknown>(`/stories/${id}`, { ...options, method: "PUT", body: input }),
  );
}

/**
 * Persist the starred flag. The backend stores it inside the ``metrics`` JSON
 * under a reserved key, so we merge the story's existing evidence metrics with
 * the control flag to avoid clobbering the evidence numbers.
 */
export async function toggleStar(story: Story, options: RequestOptions = {}): Promise<Story> {
  const evidence = (story.metrics ?? {}) as Record<string, unknown>;
  return updateStory(
    story.id,
    { metrics: { ...evidence, __starred: !story.starred } },
    options,
  );
}
