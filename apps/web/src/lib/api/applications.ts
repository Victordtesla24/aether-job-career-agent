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
  // U5 — the honest "or an actionable manual step" half of the NO-PREPARED-ONLY
  // invariant (apps/api/app/services/apply_executor.py record_manual_step /
  // apply_channel_resolver.py). Additive nullable DB columns
  // (applyChannel/manualStepReason/manualStepDetail/manualStepAt); NOT YET
  // selected by GET /applications as of the U5a/U5b backend contract this was
  // built against (apps/api/app/routers/applications.py `_COLUMNS` /
  // apps/api/app/services/application_submission.py `submission_view` — read,
  // never modified, from this FE-only slice). Declared here as nullish so the
  // schema parses successfully either way: absent today reads as "unknown,
  // don't claim a manual step" (the same honest-degrade rule `transmitted`
  // already uses below), and the UI below picks the fields up the moment the
  // backend adds them to the SELECT — no second FE deploy required.
  applyChannel: z.string().nullish(),
  manualStepReason: z.string().nullish(),
  manualStepDetail: z.string().nullish(),
  manualStepAt: z.string().nullish(),
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
