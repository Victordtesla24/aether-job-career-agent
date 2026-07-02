// RED: contracts for the base agent, tool registry and agent state.
import { describe, it, expect } from 'vitest';
import { BaseAgent } from '../base/agent.base.js';
import { ToolRegistry } from '../base/tool.registry.js';
import { createInitialState } from '../types/state.js';
import type { AetherAgentState } from '../types/state.js';

describe('createInitialState', () => {
  it('produces a well-formed initial state', () => {
    const state = createInitialState({ sessionId: 's1', userId: 'u1' });
    expect(state.sessionId).toBe('s1');
    expect(state.userId).toBe('u1');
    expect(state.messages).toEqual([]);
    expect(state.context).toEqual({});
    expect(state.scratchpad).toEqual({});
    expect(state.error).toBeUndefined();
  });

  it('carries through seed messages', () => {
    const state = createInitialState({
      sessionId: 's1',
      userId: 'u1',
      messages: [{ role: 'user', content: 'hi' }],
    });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toEqual({ role: 'user', content: 'hi' });
  });
});

describe('ToolRegistry', () => {
  const makeTool = (name: string) => ({
    name,
    description: `desc-${name}`,
    execute: async (input: unknown) => input,
  });

  it('registers and retrieves a tool', () => {
    const reg = new ToolRegistry();
    const tool = makeTool('search');
    reg.register(tool);
    expect(reg.has('search')).toBe(true);
    expect(reg.get('search')).toBe(tool);
    expect(reg.list().map((t) => t.name)).toEqual(['search']);
  });

  it('throws when registering a duplicate tool', () => {
    const reg = new ToolRegistry();
    reg.register(makeTool('dup'));
    expect(() => reg.register(makeTool('dup'))).toThrow(/already registered/i);
  });

  it('throws when getting an unknown tool', () => {
    const reg = new ToolRegistry();
    expect(() => reg.get('missing')).toThrow(/not registered/i);
  });
});

describe('BaseAgent', () => {
  class EchoAgent extends BaseAgent {
    readonly name = 'echo';
    async execute(state: AetherAgentState): Promise<AetherAgentState> {
      return {
        ...state,
        messages: [...state.messages, { role: 'assistant', content: 'echo' }],
      };
    }
  }

  it('exposes a name and a tool registry', () => {
    const reg = new ToolRegistry();
    const agent = new EchoAgent(reg);
    expect(agent.name).toBe('echo');
    expect(agent.tools).toBe(reg);
  });

  it('transforms state via execute', async () => {
    const agent = new EchoAgent(new ToolRegistry());
    const next = await agent.execute(createInitialState({ sessionId: 's', userId: 'u' }));
    expect(next.messages.at(-1)).toEqual({ role: 'assistant', content: 'echo' });
  });
});
