/**
 * Agent orchestration types shared between the queue, agents and api layers.
 */

/** High-level phase of an agent run. */
export type AgentPhase =
  | 'idle'
  | 'planning'
  | 'executing'
  | 'awaiting_approval'
  | 'completed'
  | 'failed';

/** The kind of agent performing work. */
export type AgentKind =
  | 'scout'
  | 'matcher'
  | 'tailor'
  | 'networker'
  | 'scribe'
  | 'orchestrator';

/** A single step recorded during an agent run. */
export interface AgentStep {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  output?: Record<string, unknown>;
  startedAt: string;
  completedAt?: string;
  error?: string;
}

/**
 * Serializable state carried through an agent run. Kept intentionally generic so
 * individual agents can extend the `context` bag without schema churn.
 */
export interface AetherAgentState {
  runId: string;
  kind: AgentKind;
  phase: AgentPhase;
  goal: string;
  steps: AgentStep[];
  context: Record<string, unknown>;
  /** Whether a human approval gate is currently blocking progress. */
  awaitingApproval: boolean;
  createdAt: string;
  updatedAt: string;
}
