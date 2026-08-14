/** Typed agents API client (P2-S08). */
import { z } from "zod";

import { ApiError, apiRequest, type RequestOptions } from "./client";

export const AgentSummarySchema = z.object({
  name: z.string(),
  status: z.string(),
  last_run: z.string().nullish(),
  approval_gated: z.boolean(),
});

export type AgentSummary = z.infer<typeof AgentSummarySchema>;

export const AgentRunSchema = z.object({
  id: z.string(),
  agentName: z.string(),
  status: z.enum(["queued", "running", "completed", "failed"]),
  input: z.record(z.unknown()).nullish(),
  output: z.record(z.unknown()).nullish(),
  error: z.string().nullish(),
  costUsd: z.union([z.number(), z.string()]).nullish(),
  startedAt: z.string().nullish(),
  completedAt: z.string().nullish(),
  createdAt: z.string(),
  // Stamped by the executing worker while a run is actually progressing
  // (AgentRun.heartbeatAt). Optional because rows written before that column
  // existed carry no stamp at all — see `lib/agent-run-health`, which treats a
  // FRESH heartbeat as proof of life (a legitimately long run is then never
  // called stalled) and falls back to wall-clock age when there is none.
  heartbeatAt: z.string().nullish(),
  // B6 — the id of the AgentRun that CAUSED this one (e.g. every pipeline
  // step's supervisor run), or null for a run with no recorded parent (every
  // pre-B6 row, and every directly-triggered single run). `.nullish()` — not
  // `.optional()` — so a row that carries the key with a real value round-
  // trips exactly, matching the backend's "always present, None where there
  // is no parent" contract (`apps/api/tests/test_b6_parent_run_id.py`); an
  // omitted key parses the same as an explicit null rather than erroring on
  // an older cached response shape.
  parentRunId: z.string().nullish(),
});

export type AgentRun = z.infer<typeof AgentRunSchema>;

export async function fetchAgents(options: RequestOptions = {}): Promise<AgentSummary[]> {
  return z.array(AgentSummarySchema).parse(await apiRequest<unknown>("/agents", options));
}

export async function fetchAgentRuns(options: RequestOptions = {}): Promise<AgentRun[]> {
  return z.array(AgentRunSchema).parse(await apiRequest<unknown>("/agents/runs", options));
}

// ---------------------------------------------------------------------------
// Async background generation dual-shape resolver (GAP-P7-ASYNC-001 §6).
// When AETHER_ASYNC_GENERATION is ON the run endpoints return a 202 enqueue
// envelope ({ job_id, status: "enqueued" }); we poll GET /agents/jobs/{id}
// every 3s to a terminal state. When OFF the endpoints return the legacy
// synchronous body and this resolver returns it unchanged (dormant, §6.3).
// ---------------------------------------------------------------------------

interface BackgroundJobStatus {
  job_id: string;
  status: "enqueued" | "processing" | "completed" | "failed";
  agentKey?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  createdAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
}

const JOB_POLL_INTERVAL_MS = 3000; // §16.2 / J3 step 2

/**
 * How long the client keeps polling before it stops waiting.
 *
 * MON-020 raised this from 10 min. It must sit at or above the point where the
 * SERVER guarantees the job has reached a terminal state, otherwise the client
 * announces "taking longer than expected" while the worker is still legitimately
 * working — the client-side twin of the watchdog bug fixed in
 * `routers/agents.py::_job_stale_thresholds`. That point is the worker's own
 * per-job ceiling (`AETHER_WORKER_JOB_TIMEOUT_SECONDS`, default 1200s) plus the
 * 120s watchdog settling margin = 22 min, by which time the job is either
 * completed or has been marked failed (and refunded) by the lazy watchdog.
 *
 * Background discovery is what made the gap reachable: a real scout pass
 * measures 255-473s with a 968s worst case (production discovery-cron log),
 * so runs past the old 10-min cap are a normal tail, not an anomaly.
 */
const JOB_POLL_CAP_MS = 22 * 60 * 1000;

/** Poll a single background job's status (owner-scoped on the server). */
async function pollJob(
  jobId: string,
  options: RequestOptions = {},
): Promise<BackgroundJobStatus> {
  return apiRequest<BackgroundJobStatus>(`/agents/jobs/${jobId}`, options);
}

function jobDelay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Resolve a run response of EITHER shape to the final result. A legacy
 * synchronous body is returned as-is; a 202 enqueue envelope is polled to a
 * terminal state. On `failed` it throws an ApiError carrying the honest server
 * error (never a fabricated result); on the 10-min cap it throws an honest
 * "still processing in the background" message (the job persists server-side).
 */
export async function resolveRun<T>(body: T, options: RequestOptions = {}): Promise<T> {
  const env = body as unknown as { job_id?: unknown; status?: unknown };
  if (typeof env.job_id !== "string" || env.status !== "enqueued") {
    return body; // legacy synchronous result — render immediately
  }
  const jobId = env.job_id;
  const deadline = Date.now() + JOB_POLL_CAP_MS;
  await jobDelay(JOB_POLL_INTERVAL_MS);
  for (;;) {
    const job = await pollJob(jobId, options);
    if (job.status === "completed") {
      return (job.result ?? {}) as T;
    }
    if (job.status === "failed") {
      throw new ApiError(
        job.error?.trim() || "Generation failed. Please try again.",
        502,
      );
    }
    if (Date.now() >= deadline) {
      throw new ApiError(
        "This is taking longer than expected. Your run is still processing in the " +
          "background — it will appear in your Agents activity shortly.",
        202,
      );
    }
    await jobDelay(JOB_POLL_INTERVAL_MS);
  }
}

/**
 * Trigger an agent and resolve its real result.
 *
 * `background` (MON-020) asks the endpoint to enqueue rather than run the work
 * inside the request; `resolveRun` then polls the job to a terminal state, so
 * the caller still awaits a real result and a real failure. Only endpoints that
 * implement the flag act on it (today: `/agents/scout/run`) — everywhere else
 * FastAPI ignores the unknown query param and the call stays synchronous, so
 * this can never silently change another agent's semantics.
 */
export async function runAgent(
  name: string,
  params: Record<string, unknown> = {},
  options: RequestOptions = {},
  { background = false }: { background?: boolean } = {},
): Promise<Record<string, unknown>> {
  const path = `/agents/${name}/run${background ? "?background=true" : ""}`;
  const body = await apiRequest<Record<string, unknown>>(path, {
    ...options,
    method: "POST",
    body: params,
  });
  return resolveRun(body, options);
}

export async function runPipeline(options: RequestOptions = {}): Promise<Record<string, unknown>> {
  const body = await apiRequest<Record<string, unknown>>("/agents/pipeline/run", {
    ...options,
    method: "POST",
    body: {},
  });
  return resolveRun(body, options);
}
