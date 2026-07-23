/** Typed applications API client (P2 frontend wiring). */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

export const ApplicationSchema = z.object({
  id: z.string(),
  jobId: z.string(),
  resumeId: z.string(),
  status: z.enum(["draft", "submitted", "screening", "interview", "offer", "rejected", "withdrawn"]),
  coverLetter: z.string().nullish(),
  jobTitle: z.string(),
  company: z.string(),
  applyUrl: z.string().nullish(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type Application = z.infer<typeof ApplicationSchema>;

export async function fetchApplications(options: RequestOptions = {}): Promise<Application[]> {
  return z.array(ApplicationSchema).parse(await apiRequest<unknown>("/applications", options));
}

/** Single application detail — resume version + cover letter (audit defect D7). */
export async function fetchApplication(
  id: string,
  options: RequestOptions = {},
): Promise<Application> {
  return ApplicationSchema.parse(await apiRequest<unknown>(`/applications/${id}`, options));
}

/** Mark a draft application as submitted, recording the real apply URL used. */
export async function submitApplication(
  id: string,
  appliedUrl?: string | null,
  options: RequestOptions = {},
): Promise<Application> {
  return ApplicationSchema.parse(
    await apiRequest<unknown>(`/applications/${id}/submit`, {
      ...options,
      method: "POST",
      body: { applied_url: appliedUrl ?? null },
    }),
  );
}
