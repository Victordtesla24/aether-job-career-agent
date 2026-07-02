/** Typed resumes API client (P2-S05). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const ResumeSchema = z.object({
  id: z.string().min(1),
  userId: z.string(),
  version: z.number(),
  label: z.string().nullish(),
  sections: z.record(z.unknown()),
  sourceJobId: z.string().nullish(),
  parentId: z.string().nullish(),
  formatHash: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type Resume = z.infer<typeof ResumeSchema>;

export const ResumeDiffSchema = z.object({
  resume_id: z.string(),
  parent_id: z.string().nullish(),
  changes: z.array(
    z.object({
      evidenceRef: z.string().nullish(),
      before: z.string(),
      after: z.string().nullish(),
    }),
  ),
});

export type ResumeDiff = z.infer<typeof ResumeDiffSchema>;

export async function fetchResumes(options: RequestOptions = {}): Promise<Resume[]> {
  const data = await apiRequest<unknown>("/resumes", options);
  return z.array(ResumeSchema).parse(data);
}

export async function fetchResume(id: string, options: RequestOptions = {}): Promise<Resume> {
  return ResumeSchema.parse(await apiRequest<unknown>(`/resumes/${id}`, options));
}

export async function fetchResumeDiff(id: string, options: RequestOptions = {}): Promise<ResumeDiff> {
  return ResumeDiffSchema.parse(await apiRequest<unknown>(`/resumes/${id}/diff`, options));
}

export interface TailorRunResult {
  resume_id: string;
  changes: number;
  rejected: string[];
}

export async function runTailorAgent(jobId: string, options: RequestOptions = {}): Promise<TailorRunResult> {
  return apiRequest<TailorRunResult>("/agents/tailor/run", {
    ...options,
    method: "POST",
    body: { job_id: jobId },
  });
}
