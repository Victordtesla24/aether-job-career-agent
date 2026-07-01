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
