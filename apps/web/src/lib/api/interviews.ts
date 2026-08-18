/**
 * Typed interviews API client (MV-interview-center-001 / -003, ML-W4B-OBS-1).
 *
 * Wires the Interview Center screen to the real InterviewSchedule CRUD router
 * (apps/api/app/routers/interviews.py). The backend serialises rows in
 * snake_case (see ``InterviewResponse``), so the wire schema below mirrors that
 * exactly — no silent camelCase remap that could drift from the contract.
 *
 * Also carries the Interview Prep brief (``GET /workspaces/interviews/prep``,
 * apps/api/app/routers/workspaces.py) — a per-job question brief with
 * story-grounded STAR+R answer sketches produced by the ``interviewPrep``
 * agent. ML-W4B-OBS-1: this endpoint has worked end-to-end since wave-4B, but
 * no shipped frontend file ever requested it — the panel below is the fix.
 */
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

/** Valid InterviewSchedule.type values (mirrors the backend allow-list). */
export const INTERVIEW_TYPES = [
  "phone",
  "video",
  "onsite",
  "technical",
  "panel",
  "hr",
] as const;
export type InterviewType = (typeof INTERVIEW_TYPES)[number];

/** Valid InterviewSchedule.status values (mirrors the backend allow-list). */
export const INTERVIEW_STATUSES = [
  "scheduled",
  "confirmed",
  "completed",
  "cancelled",
  "rescheduled",
  "no_show",
] as const;
export type InterviewStatus = (typeof INTERVIEW_STATUSES)[number];

/** Statuses that are still "live" — a completed/cancelled interview is terminal. */
export const ACTIVE_INTERVIEW_STATUSES: readonly InterviewStatus[] = [
  "scheduled",
  "confirmed",
  "rescheduled",
];

/**
 * Outcome of the Google Calendar write attempted when an interview is created
 * (W-CAL / ADR-CALENDAR-V4). `status` is the backend's own honest verdict —
 * `event_id` is non-null ONLY when Google returned an id, so the UI can never
 * announce an event that does not exist.
 */
export const CalendarResultSchema = z.object({
  status: z.enum([
    "created",
    "not_connected",
    "scope_missing",
    "needs_reauth",
    "failed",
  ]),
  event_id: z.string().nullable(),
  html_link: z.string().nullable(),
  message: z.string(),
});

export type CalendarResult = z.infer<typeof CalendarResultSchema>;

export const InterviewSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  application_id: z.string().nullable(),
  type: z.string(),
  status: z.string(),
  scheduled_at: z.string(),
  duration_minutes: z.number(),
  location: z.string().nullable(),
  meeting_link: z.string().nullable(),
  notes: z.string().nullable(),
  contact_name: z.string().nullable(),
  contact_email: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  // W-CAL calendar linkage. Optional so a response produced before the
  // additive columns existed still parses; nullable because "no event" is the
  // honest value whenever the calendar leg did not succeed.
  calendar_event_id: z.string().nullable().optional(),
  calendar_html_link: z.string().nullable().optional(),
  calendar_sync_status: z.string().nullable().optional(),
  calendar_synced_at: z.string().nullable().optional(),
});

export type Interview = z.infer<typeof InterviewSchema>;

/** POST /interviews also reports what happened on the calendar, in the same
 * response. Optional so a backend that has not shipped W-CAL still parses. */
export const CreatedInterviewSchema = InterviewSchema.extend({
  calendar: CalendarResultSchema.optional(),
});

export type CreatedInterview = z.infer<typeof CreatedInterviewSchema>;

/** Payload for scheduling a new interview (POST /interviews). */
export interface InterviewInput {
  application_id: string;
  type: InterviewType;
  /** ISO-8601 timestamp (send UTC — ``new Date(local).toISOString()``). */
  scheduled_at: string;
  duration_minutes?: number;
  location?: string | null;
  meeting_link?: string | null;
  notes?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
}

export async function fetchInterviews(options: RequestOptions = {}): Promise<Interview[]> {
  return z.array(InterviewSchema).parse(await apiRequest<unknown>("/interviews", options));
}

export async function createInterview(
  input: InterviewInput,
  options: RequestOptions = {},
): Promise<CreatedInterview> {
  return CreatedInterviewSchema.parse(
    await apiRequest<unknown>("/interviews", { ...options, method: "POST", body: input }),
  );
}

export async function completeInterview(
  id: string,
  options: RequestOptions = {},
): Promise<Interview> {
  return InterviewSchema.parse(
    await apiRequest<unknown>(`/interviews/${id}/complete`, { ...options, method: "POST" }),
  );
}

export async function cancelInterview(
  id: string,
  options: RequestOptions = {},
): Promise<Interview> {
  return InterviewSchema.parse(
    await apiRequest<unknown>(`/interviews/${id}/cancel`, { ...options, method: "POST" }),
  );
}

export async function deleteInterview(id: string, options: RequestOptions = {}): Promise<void> {
  await apiRequest<void>(`/interviews/${id}`, { ...options, method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Interview Prep brief (ML-W4B-OBS-1) — GET /workspaces/interviews/prep.
//
// The wire shape is whatever ``InterviewPrepResult`` (a dataclass, wave-4B)
// serialises to via ``asdict`` once persisted as an ``AgentRun.output`` row —
// see apps/api/app/agents/interview_prep_agent.py and
// apps/api/tests/test_ml_w4b_interview_panel_attribution.py for the exact
// shape a real run produces. A legacy/pre-4B run can carry a bare
// ``{"question": "..."}`` with none of the other fields (backward-compat
// case covered by that same test file), so every field but ``question``
// itself is optional/nullable here — a strict schema would crash the whole
// page on an old row instead of rendering it with honest gaps.
// ---------------------------------------------------------------------------

export const InterviewPrepAnswerSketchSchema = z.object({
  situation: z.string(),
  task: z.string(),
  action: z.string(),
  result: z.string(),
  reflection: z.string(),
});

export type InterviewPrepAnswerSketch = z.infer<typeof InterviewPrepAnswerSketchSchema>;

export const InterviewPrepQuestionSchema = z.object({
  question: z.string(),
  category: z.string().nullish(),
  whyAsked: z.string().nullish(),
  suggestedStoryId: z.string().nullish(),
  suggestedStoryTitle: z.string().nullish(),
  answerSketch: InterviewPrepAnswerSketchSchema.nullish(),
  preparationNote: z.string().nullish(),
  guardActions: z.array(z.string()).nullish(),
});

export type InterviewPrepQuestion = z.infer<typeof InterviewPrepQuestionSchema>;

export const InterviewPrepPackFileSchema = z.object({
  name: z.string(),
  kind: z.string(),
  branded: z.boolean(),
  bytes_len: z.number().optional(),
  agent: z.string().optional(),
  note: z.string().optional(),
});

export const InterviewPrepPackSchema = z.object({
  jobId: z.string().optional(),
  assembledAt: z.string().nullish(),
  folder: z.string().nullish(),
  files: z.array(InterviewPrepPackFileSchema),
  gaps: z.array(z.string()),
  plan: z.array(z.string()).optional(),
  message: z.string().optional(),
  downloadPath: z.string().optional(),
  zipBytes: z.number().nullish(),
});

export const InterviewPrepBriefingSchema = z.object({
  logistics: z.array(z.string()).optional(),
  traps: z
    .array(z.object({ title: z.string(), detail: z.string() }))
    .optional(),
  companyNotes: z.array(z.string()).optional(),
  interviewerNotes: z.array(z.string()).optional(),
  questionsToAsk: z.array(z.string()).optional(),
  guidelines: z.array(z.string()).optional(),
  closing: z.array(z.string()).optional(),
  documentMarkdown: z.string().optional(),
});

export const InterviewPrepBriefSchema = z.object({
  session: z
    .object({
      role: z.string(),
      company: z.string(),
      round: z.string(),
      scheduledFor: z.string().nullable(),
      format: z.string(),
      jobId: z.string().nullish(),
      location: z.string().nullish(),
    })
    .nullable(),
  compliance: z.object({ message: z.string(), level: z.string() }),
  brief: z
    .object({
      columns: z.array(z.object({ title: z.string(), items: z.array(z.string()) })),
      insight: z.string(),
    })
    .nullable(),
  questions: z.array(InterviewPrepQuestionSchema),
  // Non-null ONLY when a real prep brief exists but belongs to another job
  // (see the workspaces.py docstring) — never invented by the client.
  questionsNote: z.string().nullish(),
  briefing: InterviewPrepBriefingSchema.nullish(),
  pack: InterviewPrepPackSchema.nullish(),
  liveAssist: z.object({
    enabled: z.boolean(),
    fillerWordsPerMin: z.number(),
    wordsPerMin: z.number(),
    talkListenRatio: z.object({ talk: z.number(), listen: z.number() }),
    coachingCue: z.string().nullish(),
  }),
  debrief: z
    .object({
      company: z.string(),
      round: z.string(),
      score: z.number(),
      strengths: z.array(z.string()),
      warnings: z.array(z.string()),
    })
    .nullable(),
});

export type InterviewPrepBrief = z.infer<typeof InterviewPrepBriefSchema>;

export async function fetchInterviewPrep(
  options: RequestOptions = {},
): Promise<InterviewPrepBrief> {
  return InterviewPrepBriefSchema.parse(
    await apiRequest<unknown>("/workspaces/interviews/prep", options),
  );
}

export async function assembleInterviewPack(
  options: RequestOptions & { jobId?: string; runMissing?: boolean } = {},
): Promise<unknown> {
  const params = new URLSearchParams();
  if (options.jobId) params.set("job_id", options.jobId);
  if (options.runMissing) params.set("run_missing", "true");
  const q = params.toString();
  return apiRequest<unknown>(`/workspaces/interviews/pack${q ? `?${q}` : ""}`, {
    ...options,
    method: "POST",
  });
}

async function fetchInterviewPackBlob(
  path: string,
  options: RequestOptions = {},
): Promise<Blob> {
  const baseUrl = options.baseUrl ?? apiBaseUrl();
  const fetchBlob = async (token: string): Promise<Response> =>
    fetch(`${baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

  let token = options.token ?? (await getToken());
  let res = await fetchBlob(token);
  if (res.status === 401 && !options.token) {
    clearToken();
    token = await getToken();
    res = await fetchBlob(token);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    if (isNonApiHtmlBody(res.headers.get("Content-Type"), detail)) {
      throw new ApiError(gatewayErrorMessage(res.status), res.status);
    }
    throw new ApiError(`GET ${path} failed (${res.status}): ${detail}`, res.status);
  }
  return res.blob();
}

function saveBlob(blob: Blob, filename: string): void {
  if (typeof document === "undefined" || typeof URL === "undefined") return;
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function downloadInterviewPack(
  jobId: string,
  options: RequestOptions = {},
): Promise<void> {
  const blob = await fetchInterviewPackBlob(
    `/workspaces/interviews/pack/download?job_id=${encodeURIComponent(jobId)}`,
    options,
  );
  saveBlob(blob, "interview-pack.zip");
}

export async function downloadInterviewPackFile(
  jobId: string,
  name: string,
  options: RequestOptions = {},
): Promise<void> {
  const blob = await fetchInterviewPackBlob(
    `/workspaces/interviews/pack/file?job_id=${encodeURIComponent(jobId)}&name=${encodeURIComponent(name)}`,
    options,
  );
  saveBlob(blob, name.split("/").pop() || name);
}
