/** Job: tailor a resume for a specific job posting. */
import type { QueuedJob } from './discovery.job.js';

export const TAILORING_JOB = 'tailoring' as const;

export interface TailoringJobPayload {
  userId: string;
  jobId: string;
  resumeId: string;
  /** Optional target tone / voice profile id. */
  voiceProfileId?: string;
}

/** Build a well-typed tailoring job payload. */
export function buildTailoringJob(payload: TailoringJobPayload): QueuedJob<TailoringJobPayload> {
  return { name: TAILORING_JOB, data: payload };
}
