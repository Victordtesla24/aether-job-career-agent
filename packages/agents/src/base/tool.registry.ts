/**
 * A minimal, type-safe registry of tools an agent may invoke.
 *
 * Tools are the only sanctioned side-effecting surface for an agent, which keeps
 * approval-gating and cost accounting centralized. Registration is fail-fast:
 * duplicate names and unknown lookups throw rather than silently no-op.
 */

/** A callable tool exposed to agents. */
export interface AgentTool<I = unknown, O = unknown> {
  /** Unique tool name (used for lookup and logging). */
  name: string;
  /** Human-readable description for planning / prompting. */
  description: string;
  /** Execute the tool with a validated input payload. */
  execute: (input: I) => Promise<O>;
}

export class ToolRegistry {
  private readonly tools = new Map<string, AgentTool>();

  /** Register a tool; throws if the name is already taken. */
  register(tool: AgentTool): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`Tool "${tool.name}" is already registered`);
    }
    this.tools.set(tool.name, tool);
  }

  /** True if a tool with this name exists. */
  has(name: string): boolean {
    return this.tools.has(name);
  }

  /** Fetch a tool by name; throws if it is not registered. */
  get(name: string): AgentTool {
    const tool = this.tools.get(name);
    if (!tool) {
      throw new Error(`Tool "${name}" is not registered`);
    }
    return tool;
  }

  /** All registered tools, in insertion order. */
  list(): AgentTool[] {
    return [...this.tools.values()];
  }
}
