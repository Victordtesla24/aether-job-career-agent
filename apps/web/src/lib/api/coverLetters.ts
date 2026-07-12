/** Typed cover letters API client (P2-S06). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const CoverLetterSchema = z.object({
  id: z.string(),
  jobId: z.string(),
  resumeId: z.string(),
  status: z.string(),
  coverLetter: z.string().nullish(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type CoverLetter = z.infer<typeof CoverLetterSchema>;

export async function fetchCoverLetters(options: RequestOptions = {}): Promise<CoverLetter[]> {
  return z.array(CoverLetterSchema).parse(await apiRequest<unknown>("/cover-letters", options));
}

export interface CoverLetterRunResult {
  cover_letter_id: string;
  cover_letter: string;
  approval_id: string;
  approval_status: string;
}

export async function runCoverLetterAgent(
  jobId: string,
  options: RequestOptions = {},
): Promise<CoverLetterRunResult> {
  return apiRequest<CoverLetterRunResult>("/agents/cover-letter/run", {
    ...options,
    method: "POST",
    body: { job_id: jobId },
  });
}
