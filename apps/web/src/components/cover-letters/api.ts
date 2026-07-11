/** Cover Letter Studio API client — insights / refine / PDF export (R11). */
import { z } from "zod";

import { apiBaseUrl, apiRequest, getToken } from "../../lib/api/client";

export const EvidenceRowSchema = z.object({
  claim: z.string(),
  storyId: z.string().nullable(),
  storyTitle: z.string().nullable(),
  grounded: z.boolean(),
});
export type EvidenceRow = z.infer<typeof EvidenceRowSchema>;

export const LetterInsightsSchema = z.object({
  letterId: z.string(),
  jobId: z.string(),
  jobTitle: z.string().nullable(),
  company: z.string().nullable(),
  wordCount: z.number(),
  evidence: z.array(EvidenceRowSchema),
  keywords: z.object({
    covered: z.number(),
    total: z.number(),
    items: z.array(z.object({ keyword: z.string(), covered: z.boolean() })),
  }),
  voice: z.object({
    authenticity: z.number(),
    aiDetectionRisk: z.number(),
    aiDetectionLabel: z.string(),
  }),
  versions: z.array(
    z.object({
      id: z.string(),
      version: z.number(),
      createdAt: z.string(),
      current: z.boolean(),
    }),
  ),
});
export type LetterInsights = z.infer<typeof LetterInsightsSchema>;

export async function fetchLetterInsights(letterId: string): Promise<LetterInsights> {
  return LetterInsightsSchema.parse(
    await apiRequest<unknown>(`/cover-letters/${letterId}/insights`),
  );
}

export interface RefineResult {
  cover_letter_id: string;
  cover_letter: string;
  approval_id: string;
  approval_status: string;
}

export async function refineCoverLetter(
  letterId: string,
  body: { instructions?: string; tone?: number; formality?: number },
): Promise<RefineResult> {
  return apiRequest<RefineResult>(`/cover-letters/${letterId}/refine`, {
    method: "POST",
    body,
  });
}

/** Fetch the letter PDF with auth and trigger a browser download. */
export async function downloadCoverLetterPdf(
  letterId: string,
  filenameHint: string,
): Promise<void> {
  const token = await getToken();
  const res = await fetch(`${apiBaseUrl()}/cover-letters/${letterId}/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `cover-letter-${filenameHint}.pdf`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
