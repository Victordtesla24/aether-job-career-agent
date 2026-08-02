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
  // W-SUB — the truth about transmission, which `status` alone cannot carry.
  //
  // `status: "submitted"` has always meant "marked as submitted"; it has NEVER
  // meant "Aether emailed this to the employer", because until W-SUB nothing
  // in the product could send an application at all. These fields make the
  // difference visible instead of letting the stage label imply a send:
  //   transmitted      — did a message actually leave the system?
  //   submissionState  — "transmitted" | "not_transmitted"
  //   transmittedTo/At — checkable evidence for a positive claim
  //   autoSubmittable  — does the posting publish an address we could send to?
  // Nullish-tolerant so an older API build (or a cached response) degrades to
  // "unknown" rather than throwing — the UI treats absent as "don't claim".
  transmitted: z.boolean().nullish(),
  submissionState: z.enum(["transmitted", "not_transmitted"]).nullish(),
  transmittedAt: z.string().nullish(),
  transmittedTo: z.string().nullish(),
  transmissionChannel: z.string().nullish(),
  transmissionRef: z.string().nullish(),
  autoSubmittable: z.boolean().nullish(),
  applyEmail: z.string().nullish(),
  applyEmailSource: z.string().nullish(),
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
