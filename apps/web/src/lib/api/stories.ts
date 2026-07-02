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
});

export type Story = z.infer<typeof StorySchema>;

export async function fetchStories(options: RequestOptions = {}): Promise<Story[]> {
  return z.array(StorySchema).parse(await apiRequest<unknown>("/stories", options));
}

export async function runStoryExtractor(
  options: RequestOptions = {},
): Promise<{ created: number; dropped: string[] }> {
  return apiRequest("/agents/story-extractor/run", { ...options, method: "POST" });
}

export async function deleteStory(id: string, options: RequestOptions = {}): Promise<void> {
  await apiRequest<void>(`/stories/${id}`, { ...options, method: "DELETE" });
}
