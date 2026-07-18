/**
 * Typed interviews API client (MV-interview-center-001 / -003).
 *
 * Wires the Interview Center screen to the real InterviewSchedule CRUD router
 * (apps/api/app/routers/interviews.py). The backend serialises rows in
 * snake_case (see ``InterviewResponse``), so the wire schema below mirrors that
 * exactly — no silent camelCase remap that could drift from the contract.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

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
});

export type Interview = z.infer<typeof InterviewSchema>;

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
): Promise<Interview> {
  return InterviewSchema.parse(
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
