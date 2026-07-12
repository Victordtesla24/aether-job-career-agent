/** Typed resumes API client (P2-S05). */
import { z } from "zod";

import { ApiError, apiBaseUrl, apiRequest, clearToken, getToken, type RequestOptions } from "./client";

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

/**
 * Download a resume version as a format-preserving PDF.
 *
 * Streams `GET /resumes/{id}/download` (a binary PDF, so it bypasses the JSON
 * `apiRequest` helper), then triggers a browser download of the returned blob.
 * The base resume comes back as the original PDF bytes; tailored versions come
 * back as the original layout with only the reworded bullets redrawn.
 */
export async function downloadResume(id: string, options: RequestOptions = {}): Promise<void> {
  const baseUrl = options.baseUrl ?? apiBaseUrl();
  const fetchPdf = async (token: string): Promise<Response> =>
    fetch(`${baseUrl}/resumes/${id}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    });

  let token = options.token ?? (await getToken());
  let res = await fetchPdf(token);
  if (res.status === 401 && !options.token) {
    clearToken();
    token = await getToken();
    res = await fetchPdf(token);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(`GET /resumes/${id}/download failed (${res.status}): ${detail}`, res.status);
  }

  const blob = await res.blob();
  if (typeof document !== "undefined" && typeof URL !== "undefined") {
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `resume-${id.slice(0, 8)}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  }
}

export async function runTailorAgent(jobId: string, options: RequestOptions = {}): Promise<TailorRunResult> {
  return apiRequest<TailorRunResult>("/agents/tailor/run", {
    ...options,
    method: "POST",
    body: { job_id: jobId },
  });
}
