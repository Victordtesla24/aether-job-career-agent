/**
 * @aether/shared — cross-cutting types and utilities used by every workspace.
 */

/** Package version; kept in sync with package.json. */
export const VERSION = '0.1.0';

// Result utilities
export {
  type Result,
  ok,
  err,
  isOk,
  isErr,
  mapResult,
} from './utils/result.js';

// Structured logging + secret redaction
export {
  type LogLevel,
  type Logger,
  createLogger,
  redactSecrets,
} from './utils/logger.js';

// Validation helpers
export { validate, schemas, z } from './utils/validation.js';

// Domain types
export type {
  Job,
  JobEmbedding,
  JobSource,
  JobStatus,
  JobWorkMode,
} from './types/job.js';
export type {
  Resume,
  ResumeSection,
  ResumeEntry,
  EvidenceRef,
} from './types/resume.js';
export type {
  AetherAgentState,
  AgentKind,
  AgentPhase,
  AgentStep,
} from './types/agent.js';
export type {
  ApiResponse,
  ApiError,
  PageInfo,
  PaginatedResponse,
} from './types/api.js';
