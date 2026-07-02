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
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type Application = z.infer<typeof ApplicationSchema>;
export type ApplicationStatus = Application["status"];

export async function fetchApplications(options: RequestOptions = {}): Promise<Application[]> {
  return z.array(ApplicationSchema).parse(await apiRequest<unknown>("/applications", options));
}
