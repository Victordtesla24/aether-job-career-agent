/** Typed resumes API client (P2-S05). */
import { z } from "zod";

import { ApiError, apiBaseUrl, apiRequest, clearToken, getToken, type RequestOptions } from "./client";
import { resolveRun } from "./agents";

export const ResumeSchema = z.object({
  id: z.string().min(1),
  userId: z.string(),
  version: z.number(),
  label: z.string().nullish(),
  sections: z.record(z.unknown()),
  sourceJobId: z.string().nullish(),
  parentId: z.string().nullish(),
  formatHash: z.string(),
  // Human-in-the-loop review state (MV-resume-studio-001). Nullish for backward
  // compatibility with any payload predating the column; defaults to "approved".
  approvalStatus: z.string().nullish(),
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


export async function fetchResumeDiff(id: string, options: RequestOptions = {}): Promise<ResumeDiff> {
  return ResumeDiffSchema.parse(await apiRequest<unknown>(`/resumes/${id}/diff`, options));
}

/** Deterministic before/after ATS re-score + estimated conversion lift (GAP-E2). */
export interface ConversionMetrics {
  baselineATSScore: number;
  tailoredATSScore: number;
  estimatedConversionLift: string;
  methodology: string;
  confidence: string;
}

export interface TailorRunResult {
  /** Null on an honest no-op run (no version created — MV-resume-studio-003). */
  resume_id: string | null;
  changes: number;
  rejected: string[];
  /** Null on a no-op run (no tailored version was scored). */
  conversionMetrics: ConversionMetrics | null;
  /** True and backed by a real pending ApprovalRequest (MV-resume-studio-001). */
  approvalRequired?: boolean;
  approval_id?: string | null;
  approval_status?: string | null;
  /** Honest no-op: the guards rejected every edit, nothing billed or created. */
  noChangesApplied?: boolean;
  message?: string;
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
  const body = await apiRequest<TailorRunResult>("/agents/tailor/run", {
    ...options,
    method: "POST",
    body: { job_id: jobId },
  });
  // Dual-shape (GAP-P7-ASYNC-001 §6): unwrap a 202 enqueue envelope by polling
  // to completion; a legacy synchronous body passes through unchanged.
  return resolveRun(body, options);
}
