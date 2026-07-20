/** Typed cover letters API client (P2-S06). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";
import { resolveRun } from "./agents";

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
  cover_letter_id?: string;
  cover_letter?: string;
  approval_id?: string;
  approval_status?: string;
  // NF-final-resid-002: an honest no-résumé refusal (backend
  // apps/api/app/workers/tasks.py's `except MissingResumeError` handler)
  // completes the BackgroundJob with THIS shape instead — no letter was
  // generated, so none of the fields above are present.
  missingResume?: boolean;
  message?: string;
}

export async function runCoverLetterAgent(
  jobId: string,
  options: RequestOptions = {},
): Promise<CoverLetterRunResult> {
  const body = await apiRequest<CoverLetterRunResult>("/agents/cover-letter/run", {
    ...options,
    method: "POST",
    body: { job_id: jobId },
  });
  // Dual-shape (GAP-P7-ASYNC-001 §6): poll a 202 enqueue envelope to completion;
  // a legacy synchronous body passes through unchanged.
  return resolveRun(body, options);
}
