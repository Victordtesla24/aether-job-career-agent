/**
 * @aether/db — Prisma client singleton, generated types and repositories.
 */
export { prisma } from './client.js';
export * from './repositories/index.js';

// Re-export the generated Prisma namespace + enums for consumers.
export { Prisma, PrismaClient } from '@prisma/client';
export type {
  User,
  Job,
  JobEmbedding,
  Resume,
  Application,
  ApprovalRequest,
  Contact,
  EmailThread,
  StoryEntry,
  AgentRun,
  JobStatus,
  ApplicationStatus,
  ApprovalType,
  ApprovalStatus,
  ContactStage,
  AgentRunStatus,
} from '@prisma/client';
