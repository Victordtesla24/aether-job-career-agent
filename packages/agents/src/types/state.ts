/**
 * LangGraph-compatible state schema for Aether agents.
 *
 * This is the serializable state threaded through every node in an agent graph.
 * It is intentionally framework-agnostic (plain data) so it can be adapted to
 * `@langchain/langgraph` channels in Phase 2 without changing agent logic.
 */

/** A single chat message in the running conversation. */
export interface AgentMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  /** Tool name when role === 'tool'. */
  name?: string;
}

/** State carried through an Aether agent run. */
export interface AetherAgentState {
  /** Unique id for this agent session/run. */
  sessionId: string;
  /** Owner of the run. */
  userId: string;
  /** Ordered conversation history. */
  messages: AgentMessage[];
  /** Immutable-ish inputs for the run (goal, jobId, resumeId, ...). */
  context: Record<string, unknown>;
  /** Mutable working memory used between nodes. */
  scratchpad: Record<string, unknown>;
  /** Set when a node fails; halts the graph. */
  error?: string;
}

/** Build a fresh, well-formed initial state. */
export function createInitialState(params: {
  sessionId: string;
  userId: string;
  messages?: AgentMessage[];
  context?: Record<string, unknown>;
}): AetherAgentState {
  return {
    sessionId: params.sessionId,
    userId: params.userId,
    messages: params.messages ?? [],
    context: params.context ?? {},
    scratchpad: {},
  };
}
