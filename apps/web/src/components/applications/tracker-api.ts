/**
 * Application Tracker — screen-scoped API clients.
 *
 * Extends the shared application schema with the tracker fields the router
 * now returns (`answers` jsonb metadata + joined `fitScore`) and adds the
 * canonical sankey + agent-config fetchers, without touching shared clients.
 */
import { z } from "zod";

import { ApplicationSchema } from "../../lib/api/applications";
import { apiRequest, type RequestOptions } from "../../lib/api/client";

export const TrackerApplicationSchema = ApplicationSchema.extend({
  answers: z.record(z.unknown()).nullish(),
  fitScore: z.number().nullish(),
  // GOLD-MASTER-V2 §12.4 / W-J item 5: the API already returns a distinct
  // atsScore alongside fitScore (see Job.atsScore in lib/api/jobs.ts), but
  // zod's default "strip unknown keys" parsing silently dropped it here —
  // the Application/tracker card never saw it at all.
  atsScore: z.number().nullish(),
});

export type TrackerApplication = z.infer<typeof TrackerApplicationSchema>;

export async function fetchTrackerApplications(
  options: RequestOptions = {},
): Promise<TrackerApplication[]> {
  return z
    .array(TrackerApplicationSchema)
    .parse(await apiRequest<unknown>("/applications", options));
}

/**
 * Fetch applied/terminal applications — jobs the user has already applied to.
 * These are excluded from the active board and shown in a separate
 * \"Applied\" / \"History\" section (phase4).
 */
export async function fetchAppliedApplications(
  options: RequestOptions = {},
): Promise<TrackerApplication[]> {
  return z
    .array(TrackerApplicationSchema)
    .parse(
      await apiRequest<unknown>("/applications?include_applied=true", options),
    );
}

export async function fetchTrackerApplication(
  id: string,
  options: RequestOptions = {},
): Promise<TrackerApplication> {
  return TrackerApplicationSchema.parse(
    await apiRequest<unknown>(`/applications/${id}`, options),
  );
}

// ---- SUB-010: the answer pack ---------------------------------------------

/**
 * One profile field the employer's form will ask for — present with its
 * source, or absent with the place to go and fix it. `absence` is a sentence,
 * never a blank: a form field the user cannot fill is a fact worth stating.
 */
export const AnswerPackFieldSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.string().nullable(),
  present: z.boolean(),
  source: z.string().nullable(),
  absence: z.string().nullable(),
});

/**
 * One question with the user's OWN answer, or an honest blank.
 *
 * `wouldAutoSend` is reported, never acted on here: it is the Answer Bank's
 * transmission gate ("may Aether send this unattended?"), which is a different
 * question from "may the owner of this answer read it back" — the pack exists
 * so the user can copy their own words into the form themselves.
 */
export const AnswerPackEntrySchema = z.object({
  question: z.string(),
  questionSource: z.string(),
  sensitivity: z.string(),
  answered: z.boolean(),
  answer: z.string().nullable(),
  answerSource: z.string().nullable(),
  bankedQuestion: z.string().nullable(),
  matchConfidence: z.number().nullable(),
  matchMethod: z.string().nullable(),
  wouldAutoSend: z.boolean(),
  gateReason: z.string(),
  absence: z.string().nullable(),
});

export const AnswerPackSchema = z.object({
  applicationId: z.string(),
  jobId: z.string(),
  jobTitle: z.string(),
  company: z.string(),
  applyUrl: z.string().nullable(),
  honesty: z.object({
    transmitted: z.boolean(),
    claim: z.string(),
    statement: z.string(),
    readOnly: z.boolean(),
    note: z.string(),
    evidenceRef: z.string().nullish(),
    transmittedAt: z.string().nullish(),
  }),
  profile: z.object({
    fields: z.array(AnswerPackFieldSchema),
    presentCount: z.number(),
    missingCount: z.number(),
    otherResumeContactLines: z.array(z.string()),
  }),
  answers: z.object({
    entries: z.array(AnswerPackEntrySchema),
    answeredCount: z.number(),
    unansweredCount: z.number(),
    note: z.string(),
  }),
  resume: z.object({
    present: z.boolean(),
    resumeId: z.string().nullable(),
    version: z.number().nullish(),
    label: z.string().nullable(),
    tailoredToThisJob: z.boolean(),
    downloadPath: z.string().nullable(),
    updatedAt: z.string().nullish(),
    absence: z.string().nullable(),
  }),
  coverLetter: z.object({
    present: z.boolean(),
    text: z.string().nullable(),
    characterCount: z.number(),
    downloadPath: z.string().nullable(),
    absence: z.string().nullable(),
  }),
});

export type AnswerPack = z.infer<typeof AnswerPackSchema>;
export type AnswerPackEntry = z.infer<typeof AnswerPackEntrySchema>;
export type AnswerPackField = z.infer<typeof AnswerPackFieldSchema>;

/**
 * SUB-010 — the read-only pack for ONE application (GET, no body, no write).
 *
 * Nothing is submitted or transmitted by opening it; the server assembles the
 * pack from rows it already holds and reports every missing piece as absent.
 */
export async function fetchAnswerPack(
  applicationId: string,
  options: RequestOptions = {},
): Promise<AnswerPack> {
  return AnswerPackSchema.parse(
    await apiRequest<unknown>(`/applications/${applicationId}/answer-pack`, options),
  );
}

/**
 * Re-confirm a submission whose approval aged out (U5 stale-approval guard).
 *
 * The backend refuses to auto-execute an approval older than
 * `AETHER_APPROVAL_MAX_AGE_DAYS` and records `manualStepReason =
 * "approval_expired"` instead; this is the one-click path back. It creates a
 * FRESH `ApprovalRequest` server-side (the existing approval machinery, not a
 * second implementation) and clears ONLY the expired state — an obstacle a
 * re-approval cannot fix (CAPTCHA, login wall) is answered 409 and left alone.
 */
export async function reconfirmSubmission(
  id: string,
  options: RequestOptions = {},
): Promise<{ reconfirmed: boolean; approvalId: string; applicationId: string }> {
  return apiRequest<{ reconfirmed: boolean; approvalId: string; applicationId: string }>(
    `/applications/${id}/reconfirm-submission`,
    { ...options, method: "POST" },
  );
}

// ---- FEAT-B2: stage moves ----------------------------------------------------

/**
 * Move an application card to another application-fed stage
 * (POST /applications/{id}/move). The server enforces the legal-transition
 * matrix and answers 422 for job-fed or unknown targets.
 */
export async function moveApplication(
  id: string,
  toStage: string,
  options: RequestOptions = {},
): Promise<TrackerApplication> {
  return TrackerApplicationSchema.parse(
    await apiRequest<unknown>(`/applications/${id}/move`, {
      ...options,
      method: "POST",
      body: { to_stage: toStage },
    }),
  );
}

const PipelineMoveResultSchema = z.object({
  id: z.string(),
  status: z.string(),
  stage: z.string(),
});

type PipelineMoveResult = z.infer<typeof PipelineMoveResultSchema>;

/**
 * Move an agent-pipeline job card (no application yet) to another job-fed
 * stage (POST /applications/pipeline/{jobId}/move).
 */
export async function movePipelineJob(
  jobId: string,
  toStage: string,
  options: RequestOptions = {},
): Promise<PipelineMoveResult> {
  return PipelineMoveResultSchema.parse(
    await apiRequest<unknown>(`/applications/pipeline/${jobId}/move`, {
      ...options,
      method: "POST",
      body: { to_stage: toStage },
    }),
  );
}

// ---- FEAT-CLEAR: Clear Pipeline (archive all agent-pipeline job cards) ------

const ClearPipelineResultSchema = z.object({
  archived: z.number(),
  jobIds: z.array(z.string()),
});

export type ClearPipelineResult = z.infer<typeof ClearPipelineResultSchema>;

/**
 * Archive every agent-pipeline job card (Discovered / Evaluating / Tailoring
 * columns — jobs with no application yet). POST /applications/pipeline/clear.
 * Soft-archive only; jobs stay recoverable in the history view. The server
 * rejects the call without ``confirm: true``; the UI must show a confirmation
 * gate first.
 */
export async function clearPipeline(
  options: RequestOptions = {},
): Promise<ClearPipelineResult> {
  return ClearPipelineResultSchema.parse(
    await apiRequest<unknown>("/applications/pipeline/clear", {
      ...options,
      method: "POST",
      body: { confirm: true },
    }),
  );
}

// ---- Canonical sankey (REQ-R2: 847 → 412 → 156 → 23 → 4) -------------------

const SankeyStageSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.number(),
  color: z.string(),
});

export const SankeyDataSchema = z.object({
  stages: z.array(SankeyStageSchema).min(2),
  dropoffs: z.array(
    z.object({ after: z.string(), count: z.number(), reason: z.string() }),
  ),
  insight: z.string(),
});

export type SankeyData = z.infer<typeof SankeyDataSchema>;

export async function fetchSankey(options: RequestOptions = {}): Promise<SankeyData> {
  return SankeyDataSchema.parse(
    await apiRequest<unknown>("/applications/funnel/sankey", options),
  );
}

// ---- Agent guardrail state (auto-apply banner) ------------------------------

export const AgentConfigSchema = z.object({
  autoApply: z.boolean(),
  approvalGate: z.boolean(),
  matchThreshold: z.number(),
});

export type AgentConfig = z.infer<typeof AgentConfigSchema>;

export async function fetchAgentConfig(
  options: RequestOptions = {},
): Promise<AgentConfig> {
  const settings = await apiRequest<{ agentConfig?: unknown }>(
    "/workspaces/settings",
    options,
  );
  return AgentConfigSchema.parse(settings.agentConfig);
}

// ---- Application Timeline (SESSION TL-VIZ) ---------------------------------

const TimelineEventSchema = z.object({
  id: z.string(),
  applicationId: z.string(),
  fromStatus: z.string().nullable(),
  toStatus: z.string(),
  at: z.string(),
  source: z.string(),
});

export const TimelinePayloadSchema = z.object({
  items: z.array(
    z.object({
      application: TrackerApplicationSchema,
      events: z.array(TimelineEventSchema),
    }),
  ),
  range: z.object({
    start: z.string().nullable(),
    end: z.string().nullable(),
  }),
});

export type TimelinePayload = z.infer<typeof TimelinePayloadSchema>;

export async function fetchTimeline(
  options: RequestOptions = {},
): Promise<TimelinePayload> {
  return TimelinePayloadSchema.parse(
    await apiRequest<unknown>("/applications/timeline", options),
  );
}

