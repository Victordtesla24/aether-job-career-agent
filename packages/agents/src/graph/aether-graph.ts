/**
 * AetherGraph — LangGraph orchestration of the agent fleet (P2-S08).
 *
 * Nodes: supervisor → scout → matcher → fitScorer → tailor → coverLetter.
 * After the tailor / coverLetter nodes, `approvalRequired` is set on the
 * state: the graph never submits anything without a human approval (the
 * Python approval gateway enforces the same rule server-side).
 *
 * Every node execution is recorded in `runs[]` (agentName, status,
 * timestamp) mirroring the Prisma `AgentRun` audit table.
 */
import { StateGraph, END, START, Annotation } from '@langchain/langgraph';

/** Canonical node names, in pipeline order (supervisor routes first). */
export const NODE_NAMES = [
  'supervisor',
  'scout',
  'matcher',
  'fitScorer',
  'tailor',
  'coverLetter',
] as const;

export type NodeName = (typeof NODE_NAMES)[number];

/** Nodes whose output is gated behind human approval. */
export const APPROVAL_GATED_NODES: readonly NodeName[] = ['tailor', 'coverLetter'];

/** State threaded through the orchestration graph. */
export interface GraphState {
  userId: string;
  /** Free-form working memory written by nodes. */
  scratchpad: Record<string, unknown>;
  /** True once a human must approve before anything is submitted. */
  approvalRequired: boolean;
  /** Ordered list of nodes that have executed. */
  visited: NodeName[];
  error?: string;
}

/** Audit record for a single node execution (mirrors Prisma AgentRun). */
export interface GraphRunRecord {
  agentName: NodeName;
  status: 'completed' | 'failed';
  /** ISO-8601 execution timestamp. */
  timestamp: string;
  durationMs: number;
}

const GraphAnnotation = Annotation.Root({
  userId: Annotation<string>({ reducer: (_prev, next) => next, default: () => '' }),
  scratchpad: Annotation<Record<string, unknown>>({
    reducer: (prev, next) => ({ ...prev, ...next }),
    default: () => ({}),
  }),
  approvalRequired: Annotation<boolean>({
    // Once approval is required it can never be un-set by a later node.
    reducer: (prev, next) => prev || next,
    default: () => false,
  }),
  visited: Annotation<NodeName[]>({
    reducer: (prev, next) => [...prev, ...next],
    default: () => [],
  }),
  error: Annotation<string | undefined>({
    reducer: (_prev, next) => next,
    default: () => undefined,
  }),
});

type NodeUpdate = Partial<GraphState>;

export class AetherGraph {
  /** Audit trail of every node executed through this instance. */
  readonly runs: GraphRunRecord[] = [];

  private readonly nodeImpls: Record<NodeName, (state: GraphState) => NodeUpdate> = {
    supervisor: () => ({ scratchpad: { plan: [...NODE_NAMES.slice(1)] } }),
    scout: () => ({ scratchpad: { discovered: true } }),
    matcher: () => ({ scratchpad: { matched: true } }),
    fitScorer: () => ({ scratchpad: { scored: true } }),
    tailor: () => ({ scratchpad: { tailored: true }, approvalRequired: true }),
    coverLetter: () => ({ scratchpad: { letterDrafted: true }, approvalRequired: true }),
  };

  /** Canonical node names known to the graph. */
  getNodeNames(): NodeName[] {
    return [...NODE_NAMES];
  }

  /** Execute a single node against a state, recording the run. */
  runNode(name: NodeName, state: GraphState): GraphState {
    const impl = this.nodeImpls[name];
    if (!impl) {
      throw new Error(`Unknown node '${name}'`);
    }
    const startedAt = Date.now();
    try {
      const update = impl(state);
      const next: GraphState = {
        ...state,
        ...update,
        scratchpad: { ...state.scratchpad, ...(update.scratchpad ?? {}) },
        approvalRequired: state.approvalRequired || Boolean(update.approvalRequired),
        visited: [...state.visited, name],
      };
      this.record(name, 'completed', startedAt);
      return next;
    } catch (error) {
      this.record(name, 'failed', startedAt);
      throw error;
    }
  }

  /** Build the compiled LangGraph pipeline (supervisor → … → coverLetter). */
  buildGraph() {
    const graph = new StateGraph(GraphAnnotation);
    for (const name of NODE_NAMES) {
      graph.addNode(name, (state) => {
        const startedAt = Date.now();
        const update = this.nodeImpls[name](state as GraphState);
        this.record(name, 'completed', startedAt);
        return { ...update, visited: [name] };
      });
    }
    graph.addEdge(START, 'supervisor');
    graph.addEdge('supervisor', 'scout');
    graph.addEdge('scout', 'matcher');
    graph.addEdge('matcher', 'fitScorer');
    graph.addEdge('fitScorer', 'tailor');
    graph.addEdge('tailor', 'coverLetter');
    graph.addEdge('coverLetter', END);
    return graph.compile();
  }

  /** Run the full pipeline through LangGraph and return the final state. */
  async run(userId: string): Promise<GraphState> {
    const compiled = this.buildGraph();
    const finalState = await compiled.invoke({ userId });
    return finalState as GraphState;
  }

  private record(agentName: NodeName, status: GraphRunRecord['status'], startedAt: number): void {
    this.runs.push({
      agentName,
      status,
      timestamp: new Date(startedAt).toISOString(),
      durationMs: Date.now() - startedAt,
    });
  }
}

export function createInitialGraphState(userId: string): GraphState {
  return { userId, scratchpad: {}, approvalRequired: false, visited: [] };
}
