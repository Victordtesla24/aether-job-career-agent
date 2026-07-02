/** Job: submit / advance a job application (gated by human approval). */
import type { QueuedJob } from './discovery.job.js';

export const APPLICATION_JOB = 'application' as const;

export interface ApplicationJobPayload {
  userId: string;
  applicationId: string;
  /** When true, only prepare the submission and await approval. */
  dryRun?: boolean;
}

/** Build a well-typed application job payload. */
export function buildApplicationJob(
  payload: ApplicationJobPayload,
): QueuedJob<ApplicationJobPayload> {
  return { name: APPLICATION_JOB, data: payload };
}
