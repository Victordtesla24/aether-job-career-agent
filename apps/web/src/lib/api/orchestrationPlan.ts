/**
 * GET /agents/orchestration/plan · POST /agents/orchestration/run-everything ·
 * GET /agents/orchestration/plans/{id} — the Supervisor's plan, the global run,
 * and the RECORDED plan the console narrates from (ADR-AGI-3 P1-A → P1-B).
 *
 * THE SCHEMAS ARE WRITTEN AGAINST THE LIVE PAYLOAD, not against a spec's idea
 * of it. The P1-B scout brief described plan steps carrying
 * `agentKey`/`agentName`/`stage`/`stageIndex`/`alsoCovers`/`costEstimate`;
 * production (captured 2026-08-14, checked in at
 * `src/__tests__/agents/fixtures/orchestration-plan.prod.json`) serves
 * `key`/`backend`/`execClass`/`dependsOn`/`coversCards`/`cardNames`/`group`/
 * `exclusive`/`metered`/`rationale`. A schema written from the brief would have
 * thrown on every real response — so the fixture, not the prose, is the
 * contract, and a test parses it on every run.
 *
 * WHY `.passthrough()` IS DELIBERATE HERE: P1-A may add fields to a step (the
 * narration slice is explicitly staged to), and a strict object would drop them
 * silently. Unknown keys are carried, never invented.
 */
import { z } from "zod";

import { apiRequest, type RequestOptions } from "./client";

/**
 * One step of the plan. On the PREVIEW (`/orchestration/plan`) it describes
 * what would run; on a RECORDED plan row the same object additionally carries
 * `state`/`detail`, stamped by the executor as each transition is persisted —
 * which is why both live in one schema rather than two that could drift.
 */
export const OrchestrationPlanStepSchema = z
  .object({
    /** The dispatch's backend key, e.g. `scout` — the executor's step id. */
    key: z.string(),
    /** Same value as `key`; the API writes both deliberately (agents.py). */
    backend: z.string().nullish(),
    /** `sequential` | `independent` | `silo` — charter data, not a guess. */
    execClass: z.string().nullish(),
    dependsOn: z.array(z.string()).default([]),
    /** Catalog card keys this ONE dispatch covers (server-side dedup, R-2a). */
    coversCards: z.array(z.string()).default([]),
    /** The same cards' display names, as the server names them. */
    cardNames: z.array(z.string()).default([]),
    /**
     * `[[param, sourceStepKey, field], …]` — how a step's input is taken from
     * an earlier step's output (e.g. tailor's `job_id` comes from matcher's
     * `top_job_id`). A triple, not a name: the P1-B scout brief described this
     * as a list of strings, production serves the triples.
     */
    paramsFrom: z.array(z.array(z.string())).default([]),
    onRefusal: z.string().nullish(),
    /** Parallel group index — steps sharing one index may run together. */
    group: z.number().nullish(),
    exclusive: z.boolean().nullish(),
    siloBasis: z.string().nullish(),
    unmetDependencies: z.array(z.string()).default([]),
    /** True when the step reserves a paid run at dispatch. */
    metered: z.boolean().nullish(),
    /** The server's own sentence explaining why the step sits where it does. */
    rationale: z.string().nullish(),
    /** Recorded plans only: `pending` → `running` → terminal. */
    state: z.string().nullish(),
    detail: z.record(z.unknown()).nullish(),
  })
  .passthrough();

export type OrchestrationPlanStep = z.infer<typeof OrchestrationPlanStepSchema>;

export const OrchestrationPlanSchema = z
  .object({
    concurrency: z.number(),
    concurrencyBasis: z.string(),
    spacingSeconds: z.number(),
    /** Dispatches — 19 in production, NOT the card count. */
    agentCount: z.number(),
    /** Catalog cards those dispatches cover — 21 in production. */
    cardCount: z.number(),
    duplicateCardsCollapsed: z.number(),
    meteredStepCount: z.number(),
    /** Literally 0: the plan endpoint dispatches nothing and calls no model. */
    estimatedCostUsd: z.number(),
    groups: z.array(z.array(z.string())).default([]),
    steps: z.array(OrchestrationPlanStepSchema).default([]),
    notes: z.array(z.string()).default([]),
    asyncEnabled: z.boolean(),
    runnable: z.boolean(),
    refusal: z.string().nullable(),
  })
  .passthrough();

export type OrchestrationPlan = z.infer<typeof OrchestrationPlanSchema>;

/**
 * A RECORDED plan (the `RunPlan` row). `status` is intentionally a bare string:
 * the server's terminal set is `completed | partial | halted | failed` over a
 * live set of `planned | running`, and a status this client has never heard of
 * must be shown verbatim rather than rejected or mapped onto a happier word.
 */
export const RunPlanRecordSchema = z
  .object({
    id: z.string(),
    status: z.string(),
    initiator: z.string().nullish(),
    concurrency: z.number().nullish(),
    spacingSeconds: z.number().nullish(),
    steps: z.array(OrchestrationPlanStepSchema).default([]),
    summary: z.record(z.unknown()).nullish(),
    haltedAtStep: z.string().nullish(),
    haltReason: z.string().nullish(),
    startedAt: z.string().nullish(),
    finishedAt: z.string().nullish(),
    createdAt: z.string().nullish(),
    updatedAt: z.string().nullish(),
  })
  .passthrough();

export type RunPlanRecord = z.infer<typeof RunPlanRecordSchema>;

/** The 202 envelope POST /orchestration/run-everything answers with. */
export const RunEverythingAcceptedSchema = z
  .object({
    job_id: z.string(),
    planId: z.string(),
    status: z.string(),
    stepCount: z.number(),
    cardCount: z.number(),
    concurrency: z.number().nullish(),
  })
  .passthrough();

export type RunEverythingAccepted = z.infer<typeof RunEverythingAcceptedSchema>;

/** Plan statuses that mean the server is still working. */
export const LIVE_PLAN_STATUSES: readonly string[] = ["planned", "running"];

/** Plan statuses the server treats as terminal (repositories/run_plan.py). */
export const TERMINAL_PLAN_STATUSES: readonly string[] = [
  "completed",
  "partial",
  "halted",
  "failed",
];

export function isTerminalPlanStatus(status: string | null | undefined): boolean {
  return status != null && TERMINAL_PLAN_STATUSES.includes(status);
}

/** The Supervisor's plan, before anything runs. Costs $0 by construction. */
export async function fetchOrchestrationPlan(
  options: RequestOptions = {},
): Promise<OrchestrationPlan> {
  return OrchestrationPlanSchema.parse(
    await apiRequest<unknown>("/agents/orchestration/plan", options),
  );
}

/**
 * Start the whole plan as ONE server-recorded run.
 *
 * Deliberately NOT routed through `resolveRun` (lib/api/agents): that helper
 * polls a BackgroundJob to a terminal state and returns its result, which for a
 * 19-dispatch plan would mean holding a promise open for the length of the run
 * and reporting a JOB's state as if it were the PLAN's. The plan row is the
 * record of what happened, so the caller polls that instead.
 */
export async function startRunEverything(
  options: RequestOptions = {},
): Promise<RunEverythingAccepted> {
  return RunEverythingAcceptedSchema.parse(
    await apiRequest<unknown>("/agents/orchestration/run-everything", {
      ...options,
      method: "POST",
      body: {},
    }),
  );
}

/** One recorded plan and the live state of each of its steps (owner-scoped). */
export async function fetchRunPlan(
  planId: string,
  options: RequestOptions = {},
): Promise<RunPlanRecord> {
  return RunPlanRecordSchema.parse(
    await apiRequest<unknown>(`/agents/orchestration/plans/${planId}`, options),
  );
}
