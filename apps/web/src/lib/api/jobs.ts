/**
 * Typed jobs API client (P2-S02).
 *
 * Thin fetch wrapper over the FastAPI backend with zod response validation.
 * Framework-free on purpose so it is usable from server components, client
 * components, and unit tests alike.
 */
import { z } from "zod";

/** Where the FastAPI backend lives. Overridable per environment. */
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export const JobStatusSchema = z.enum([
  "discovered",
  "screening",
  "matched",
  "tailoring",
  "ready",
  "applied",
  "archived",
  "rejected",
]);

export const JobSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  company: z.string().min(1),
  location: z.string().nullish(),
  remote: z.boolean(),
  description: z.string(),
  requirements: z.array(z.string()).nullish(),
  source: z.string().min(1),
  sourceUrl: z.string().nullish(),
  status: JobStatusSchema,
  fitScore: z.number().nullish(),
  atsScore: z.number().nullish(),
  saved: z.boolean(),
  postedAt: z.string().nullish(),
  createdAt: z.string().optional(),
  updatedAt: z.string().optional(),
});

export type Job = z.infer<typeof JobSchema>;
export type JobStatus = z.infer<typeof JobStatusSchema>;

/** Per-source discovery sync status row (GAP-SRC-003), from the JobSourceStatus table. */
export const ScoutSourceStatusSchema = z.object({
  source: z.string().min(1),
  lastSyncAt: z.string().nullish(),
  lastFetched: z.number(),
  lastPersisted: z.number(),
  lastError: z.string().nullish(),
  status: z.string().min(1),
});

export type ScoutSourceStatus = z.infer<typeof ScoutSourceStatusSchema>;

/** Backend-derived per-source availability (ML-audit-seek-fe-hardcode-001). */
export const SourceAvailabilitySchema = z.object({
  source: z.string().min(1),
  available: z.boolean(),
  reason: z.string().nullable(),
});

export type SourceAvailability = z.infer<typeof SourceAvailabilitySchema>;

export interface JobFilters {
  status?: JobStatus;
  source?: string;
  saved?: boolean;
  sort?: "createdAt" | "fitScore" | "title" | "company";
}

export interface RequestOptions {
  /** Bearer token for the Authorization header. */
  token: string;
  /** Override the API base URL (mainly for tests). */
  baseUrl?: string;
}

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request(
  path: string,
  options: RequestOptions,
  init: RequestInit = {},
): Promise<unknown> {
  const base = options.baseUrl ?? API_BASE_URL;
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${options.token}`,
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new ApiError(`Request to ${path} failed (${response.status})`, response.status);
  }
  return response.json();
}

/** List the authenticated user's jobs, optionally filtered. */
export async function fetchJobs(
  filters: JobFilters | undefined,
  options: RequestOptions,
): Promise<Job[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.source) params.set("source", filters.source);
  if (filters?.saved !== undefined) params.set("saved", String(filters.saved));
  if (filters?.sort) params.set("sort", filters.sort);
  const query = params.size > 0 ? `?${params.toString()}` : "?";
  const body = await request(`/jobs${query}`, options);
  return z.array(JobSchema).parse(body);
}

/** Fetch a single job by id. */
export async function fetchJob(id: string, options: RequestOptions): Promise<Job> {
  const body = await request(`/jobs/${encodeURIComponent(id)}`, options);
  return JobSchema.parse(body);
}

/** Toggle a job's saved flag; returns the updated job. */
export async function toggleSaveJob(id: string, options: RequestOptions): Promise<Job> {
  const body = await request(`/jobs/${encodeURIComponent(id)}/save`, options, {
    method: "POST",
  });
  return JobSchema.parse(body);
}

/** Trigger a scout discovery run (202 Accepted). */
export async function runScoutAgent(
  query: string,
  location: string,
  options: RequestOptions,
): Promise<void> {
  await request("/agents/scout/run", options, {
    method: "POST",
    body: JSON.stringify({ query, location }),
  });
}

/** Per-source discovery sync status — counts, last sync time, ok/error/skipped. */
export async function fetchScoutSources(
  options: RequestOptions,
): Promise<ScoutSourceStatus[]> {
  const body = await request("/agents/scout/sources", options);
  return z.array(ScoutSourceStatusSchema).parse(body);
}

/**
 * Backend-derived per-source availability — which sources are live-filterable
 * right now and, when not, the honest reason (ML-audit-seek-fe-hardcode-001).
 */
export async function fetchSourceAvailability(
  options: RequestOptions,
): Promise<SourceAvailability[]> {
  const body = await request("/agents/scout/sources/availability", options);
  return z.array(SourceAvailabilitySchema).parse(body);
}
