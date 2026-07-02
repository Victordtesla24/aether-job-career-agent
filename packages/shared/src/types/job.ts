/**
 * Job domain types shared across web, api and agent layers.
 */

/** Where a job posting was discovered. */
export type JobSource =
  | 'linkedin'
  | 'seek'
  | 'indeed'
  | 'greenhouse'
  | 'lever'
  | 'company'
  | 'referral'
  | 'other';

/** Lifecycle status of a job in the Aether pipeline. */
export type JobStatus =
  | 'discovered'
  | 'screening'
  | 'matched'
  | 'tailoring'
  | 'ready'
  | 'applied'
  | 'archived'
  | 'rejected';

/** Employment arrangement. */
export type JobWorkMode = 'onsite' | 'hybrid' | 'remote';

/** A normalized job posting. */
export interface Job {
  id: string;
  source: JobSource;
  externalId?: string;
  url?: string;
  title: string;
  company: string;
  location?: string;
  workMode?: JobWorkMode;
  description: string;
  requirements?: string[];
  salaryMin?: number;
  salaryMax?: number;
  currency?: string;
  status: JobStatus;
  matchScore?: number;
  postedAt?: string;
  discoveredAt: string;
}

/** A vector embedding for semantic job matching. */
export interface JobEmbedding {
  id: string;
  jobId: string;
  model: string;
  dimension: number;
  createdAt: string;
}
