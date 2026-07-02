/**
 * Base contract for every Aether agent.
 *
 * An agent is a named unit of work that transforms {@link AetherAgentState} and
 * may invoke registered tools. Concrete agents (Scout, Matcher, Tailor, ...)
 * extend this class. In Phase 2 each `execute` becomes a LangGraph node.
 */
import { createLogger, type Logger } from '@aether/shared';
import { ToolRegistry } from './tool.registry.js';
import type { AetherAgentState } from '../types/state.js';

export abstract class BaseAgent {
  /** Stable, unique agent name (used for logging and run records). */
  abstract readonly name: string;

  /** Scoped structured logger (redacts secrets). */
  protected readonly logger: Logger;

  constructor(public readonly tools: ToolRegistry) {
    this.logger = createLogger('agent');
  }

  /** Advance the state one step. Implementations must be pure w.r.t. inputs. */
  abstract execute(state: AetherAgentState): Promise<AetherAgentState>;
}
