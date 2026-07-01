/**
 * Jobs API client (P2-S02).
 *
 * Thin, validated wrapper over the FastAPI job endpoints. Every response is
 * parsed with Zod so malformed payloads fail loudly at the boundary rather than
 * propagating `any` through the UI.
 *
 * Requests send `credentials: 'include'` so the NextAuth session cookie is
 * forwarded to the backend for the authenticated endpoints.
 */
import { z } from 'zod';

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

/** Runtime schema for a job posting as returned by the API (camelCase). */
export const JobSchema = z.object({
  id: z.string(),
  title: z.string(),
  company: z.string(),
  location: z.string().nullable().optional(),
  remote: z.boolean(),
  description: z.string(),
  requirements: z.array(z.string()).default([]),
  source: z.string(),
  sourceUrl: z.string().nullable().optional(),
  status: z.string(),
  fitScore: z.number().nullable().optional(),
  atsScore: z.number().nullable().optional(),
  saved: z.boolean(),
  createdAt: z.string(),
});

export type Job = z.infer<typeof JobSchema>;

const JobListSchema = z.array(JobSchema);

export interface JobFilters {
  status?: string;
  source?: string;
  saved?: boolean;
}

function buildHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json' };
}

function buildQuery(filters?: JobFilters): string {
  if (!filters) return '';
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.source) params.set('source', filters.source);
  if (typeof filters.saved === 'boolean') params.set('saved', String(filters.saved));
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

async function parseJson(res: Response): Promise<unknown> {
  if (!res.ok) {
    throw new Error(`Jobs API request failed with status ${res.status}`);
  }
  return res.json();
}

/** List the authenticated user's jobs, optionally filtered. */
export async function fetchJobs(filters?: JobFilters): Promise<Job[]> {
  const res = await fetch(`${API_BASE_URL}/jobs${buildQuery(filters)}`, {
    method: 'GET',
    headers: buildHeaders(),
    credentials: 'include',
  });
  return JobListSchema.parse(await parseJson(res));
}

/** Fetch a single job by id. */
export async function fetchJob(id: string): Promise<Job> {
  const res = await fetch(`${API_BASE_URL}/jobs/${encodeURIComponent(id)}`, {
    method: 'GET',
    headers: buildHeaders(),
    credentials: 'include',
  });
  return JobSchema.parse(await parseJson(res));
}

/** Toggle the `saved` flag on a job and return the updated record. */
export async function toggleSaveJob(id: string): Promise<Job> {
  const res = await fetch(
    `${API_BASE_URL}/jobs/${encodeURIComponent(id)}/save`,
    {
      method: 'POST',
      headers: buildHeaders(),
      credentials: 'include',
    },
  );
  return JobSchema.parse(await parseJson(res));
}

/** Trigger the Scout agent for the authenticated user (fire-and-forget). */
export async function runScoutAgent(
  query: string,
  location: string,
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/agents/scout/run`, {
    method: 'POST',
    headers: buildHeaders(),
    credentials: 'include',
    body: JSON.stringify({ query, location }),
  });
  if (!res.ok) {
    throw new Error(`Scout run failed with status ${res.status}`);
  }
}
