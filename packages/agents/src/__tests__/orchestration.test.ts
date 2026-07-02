/**
 * P2-S08 — Multi-agent orchestration tests (LangGraph).
 */
import { describe, expect, it } from 'vitest';

import {
  AetherGraph,
  APPROVAL_GATED_NODES,
  createInitialGraphState,
  NODE_NAMES,
} from '../graph/aether-graph.js';

describe('AetherGraph — node registry', () => {
  it('defines the canonical nodes: supervisor, scout, matcher, fitScorer, tailor, coverLetter', () => {
    const graph = new AetherGraph();
    expect(graph.getNodeNames()).toEqual([
      'supervisor',
      'scout',
      'matcher',
      'fitScorer',
      'tailor',
      'coverLetter',
    ]);
  });

  it('marks tailor and coverLetter as approval-gated', () => {
    expect(APPROVAL_GATED_NODES).toContain('tailor');
    expect(APPROVAL_GATED_NODES).toContain('coverLetter');
  });
});

describe('AetherGraph — state transitions', () => {
  it('sets approvalRequired=true after the tailor node and keeps it set', () => {
    const graph = new AetherGraph();
    let state = createInitialGraphState('user-1');
    expect(state.approvalRequired).toBe(false);

    state = graph.runNode('supervisor', state);
    state = graph.runNode('scout', state);
    state = graph.runNode('matcher', state);
    state = graph.runNode('fitScorer', state);
    expect(state.approvalRequired).toBe(false);

    state = graph.runNode('tailor', state);
    expect(state.approvalRequired).toBe(true);

    // Later nodes must not reset the flag.
    state = graph.runNode('coverLetter', state);
    expect(state.approvalRequired).toBe(true);
    expect(state.visited).toEqual(NODE_NAMES.slice(0));
  });

  it('rejects unknown node names', () => {
    const graph = new AetherGraph();
    const state = createInitialGraphState('user-1');
    // @ts-expect-error — deliberately invalid node name
    expect(() => graph.runNode('rogueNode', state)).toThrow(/Unknown node/);
  });
});

describe('AetherGraph — AgentRun audit records', () => {
  it('logs every node transition with agentName, status and timestamp', () => {
    const graph = new AetherGraph();
    let state = createInitialGraphState('user-1');
    for (const name of graph.getNodeNames()) {
      state = graph.runNode(name, state);
    }
    expect(graph.runs).toHaveLength(NODE_NAMES.length);
    for (const [i, run] of graph.runs.entries()) {
      expect(run.agentName).toBe(NODE_NAMES[i]);
      expect(run.status).toBe('completed');
      expect(Date.parse(run.timestamp)).not.toBeNaN();
      expect(run.durationMs).toBeGreaterThanOrEqual(0);
    }
  });

  it('runs the compiled LangGraph pipeline end-to-end', async () => {
    const graph = new AetherGraph();
    const finalState = await graph.run('user-42');
    expect(finalState.approvalRequired).toBe(true);
    expect(finalState.visited).toEqual([...NODE_NAMES]);
    expect(graph.runs.map((r) => r.agentName)).toEqual([...NODE_NAMES]);
  });
});
