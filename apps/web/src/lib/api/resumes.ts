/** Typed resumes API client (P2-S05). */
import { z } from "zod";

import {
  ApiError,
  apiBaseUrl,
  apiRequest,
  clearToken,
  gatewayErrorMessage,
  getToken,
  isNonApiHtmlBody,
  type RequestOptions,
} from "./client";
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
  // MON-011 (MONITORING-LEDGER.md): true ONLY when GET /resumes/{id}/download
  // would genuinely reproduce the original document (resolve_original_pdf
  // finds a bundled-asset digest match) — the exact condition the download
  // endpoint branches on. Nullish for backward compatibility with any fixture
  // or cached payload predating this field; a missing value is NOT treated as
  // an affirmative preservation claim (see page.tsx's per-version logic).
  formatPreserved: z.boolean().nullish(),
  // U2b (R-F2/R-F4): the API's own per-version fidelity report — WHICH
  // mechanism a download uses ("docx-native", "pdf-in-place-splice",
  // "original-bytes", "text-native", "reflow-template", "unknown"), how
  // confident that is, and an honest note in the user's own terms. A bare
  // boolean cannot distinguish a genuine native-DOCX preservation from a
  // low-confidence re-flow, so Resume Studio renders this note instead of
  // hard-coded, mechanism-agnostic copy. Nullish for payloads predating it.
  formatFidelity: z
    .object({
      method: z.string(),
      confidence: z.string(),
      note: z.string(),
    })
    .nullish(),
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
  /**
   * True exactly when the score-aware TailoringLoop stopped at its iteration
   * cap without reaching the 85 ATS target (tailor_agent.py). Wired
   * alongside the top-level `warning` string below (§5.3.1 pt 5).
   */
  requires_review?: boolean;
  /**
   * GMV4-ats-002: true iff the baseline and/or tailored re-score's semantic
   * component was "degraded" (no genuine embedding model or HF Inference API
   * available — apps/api/app/services/ats_engine.py's ATSScore.semantic_path).
   * When true, the delta these numbers imply is not a trustworthy measurement.
   */
  baselineDegraded?: boolean;
  tailoredDegraded?: boolean;
  scoringDegraded?: boolean;
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
  /**
   * Honest sub-85 warning from the score-aware TailoringLoop (§5.3.1 pt 5),
   * sourced verbatim from `TailoringLoopResult.warning`
   * (apps/api/app/services/tailoring_loop.py) via
   * `apps/api/app/routers/agents.py:2309`. Null when the loop reached the
   * 85 ATS target — never rendered as an error, never as success.
   */
  warning?: string | null;
}

/**
 * Download a resume version as a PDF.
 *
 * Streams `GET /resumes/{id}/download` (a binary PDF, so it bypasses the JSON
 * `apiRequest` helper), then triggers a browser download of the returned blob.
 *
 * MON-011 (MONITORING-LEDGER.md): whether the returned PDF actually
 * reproduces the original document's layout depends on the server's
 * `resolve_original_pdf` match (apps/api/app/services/resume_pdf.py) — true
 * only for the bundled seed PDFs and versions tailored from them. Every real
 * user upload (base or tailored) falls through to the generic branded
 * template instead. This function makes no promise about which happened;
 * callers must read the resume's own `formatPreserved` flag (`ResumeSchema`
 * above) before telling the user their layout was preserved.
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
    // MON-020: this handler builds its own `fetch` (it needs the PDF blob, not
    // JSON), so it does not get `apiRequest`'s guard for free — and its message
    // is rendered VERBATIM in the Résumé Studio download note. An intermediary's
    // HTML error page (the same Cloudflare 524 that started MON-020) must never
    // get that far, so the shared predicate/sentence pair is applied here too.
    // A JSON body from our own API keeps the exact prefixed shape it always had.
    if (isNonApiHtmlBody(res.headers.get("Content-Type"), detail)) {
      throw new ApiError(gatewayErrorMessage(res.status), res.status);
    }
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

// ---------------------------------------------------------------------------
// GET /resumes/{id}/tailoring-impact — the ONE before/after authority (R-01/R-03)
// ---------------------------------------------------------------------------

/**
 * Wire shape of one half of the pair. `ats` and `atsMeasured` are siblings on
 * the wire; the parser below collapses them so downstream components only ever
 * see a number they are allowed to render.
 */
const TailoringImpactHalfWireSchema = z.object({
  label: z.string().nullish(),
  ats: z.number().nullish(),
  atsMeasured: z.boolean().nullish(),
  unmeasuredReason: z.string().nullish(),
  dimensions: z
    .array(
      z.object({
        label: z.string(),
        score: z.number().nullish(),
        degraded: z.boolean().nullish(),
      }),
    )
    .default([]),
});

export interface TailoringImpactDimension {
  label: string;
  score: number;
  degraded: boolean;
}

export interface TailoringImpactHalf {
  label: string;
  /** `null` == not measured. FAIL CLOSED: a half that does not explicitly
   *  attest `atsMeasured: true` alongside a real number yields `null`, so an
   *  unattested payload can never render as a measurement. */
  ats: number | null;
  unmeasuredReason: string | null;
  dimensions: TailoringImpactDimension[];
}

export interface TailoringImpact {
  resumeId: string;
  jobId: string;
  jobTitle: string | null;
  company: string | null;
  before: TailoringImpactHalf;
  after: TailoringImpactHalf;
}

const TailoringImpactWireSchema = z.object({
  resumeId: z.string(),
  jobId: z.string(),
  jobTitle: z.string().nullish(),
  company: z.string().nullish(),
  before: TailoringImpactHalfWireSchema,
  after: TailoringImpactHalfWireSchema,
});

function halfFrom(
  raw: z.infer<typeof TailoringImpactHalfWireSchema>,
  fallbackLabel: string,
): TailoringImpactHalf {
  const measured = raw.atsMeasured === true && typeof raw.ats === "number";
  return {
    label: raw.label ?? fallbackLabel,
    ats: measured ? (raw.ats as number) : null,
    unmeasuredReason: raw.unmeasuredReason ?? null,
    // Same fail-closed rule as `lib/scoring/provenance.ts::fitDimensionsFrom`:
    // only an explicit `degraded: false` next to a real number is a
    // measurement; absent, true, or a non-number all read as degraded.
    dimensions: raw.dimensions.map((d) => ({
      label: d.label,
      score: typeof d.score === "number" ? d.score : 0,
      degraded: !(d.degraded === false && typeof d.score === "number"),
    })),
  };
}

/**
 * Both halves of a tailored version's before/after pair, blended and rounded
 * by ONE server-side authority (`routers/jobs.py::build_fit_dimensions` +
 * `_round`). The browser does no blending and no rounding of its own — that
 * duplication is exactly what put rounding artefacts into the displayed delta
 * and let a placeholder-contaminated baseline render as measured.
 */
export async function fetchTailoringImpact(
  resumeId: string,
  options: RequestOptions = {},
): Promise<TailoringImpact> {
  const raw = TailoringImpactWireSchema.parse(
    await apiRequest<unknown>(`/resumes/${resumeId}/tailoring-impact`, options),
  );
  return {
    resumeId: raw.resumeId,
    jobId: raw.jobId,
    jobTitle: raw.jobTitle ?? null,
    company: raw.company ?? null,
    before: halfFrom(raw.before, "Baseline résumé"),
    after: halfFrom(raw.after, "Tailored version"),
  };
}
