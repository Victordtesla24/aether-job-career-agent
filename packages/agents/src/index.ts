/**
 * @aether/agents — base agent contracts and orchestration primitives.
 */
export { BaseAgent } from './base/agent.base.js';
export { ToolRegistry, type AgentTool } from './base/tool.registry.js';
export {
  createInitialState,
  type AetherAgentState,
  type AgentMessage,
} from './types/state.js';
export {
  FixtureStore,
  fixtureKey,
  RecordReplayLLMClient,
  resolveMode,
  OpenRouterClient,
  type LLMClient,
  type LLMMessage,
  type LLMRequest,
  type LLMResponse,
  type LLMMode,
  type RecordReplayOptions,
  type OpenRouterOptions,
} from './llm/index.js';
