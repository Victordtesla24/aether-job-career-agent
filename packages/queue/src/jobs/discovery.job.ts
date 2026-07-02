/** Job: discover new job postings for a user across sources. */
import type { JobSource } from '@aether/shared';

export const DISCOVERY_JOB = 'discovery' as const;

export interface DiscoveryJobPayload {
  userId: string;
  query: string;
  sources: JobSource[];
  /** Optional location filter. */
  location?: string;
}

export interface QueuedJob<T> {
  name: string;
  data: T;
}

/** Build a well-typed discovery job payload. */
export function buildDiscoveryJob(payload: DiscoveryJobPayload): QueuedJob<DiscoveryJobPayload> {
  return { name: DISCOVERY_JOB, data: payload };
}
