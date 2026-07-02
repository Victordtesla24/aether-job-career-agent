/**
 * Minimal, framework-agnostic LLM contracts used by Aether agents.
 *
 * These types intentionally describe only what the agents need: a chat-style
 * completion request and its textual response. Concrete transports
 * (OpenRouter live client, record/replay fixture client) implement
 * {@link LLMClient}. Keeping this surface tiny makes it trivial to swap in a
 * deterministic fixture client during tests and CI.
 */

/** A single chat message sent to (or received from) the model. */
export interface LLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

/** A chat-completion request. The shape is deliberately provider-neutral. */
export interface LLMRequest {
  /** Fully-qualified model id, e.g. `meta-llama/llama-3.1-8b-instruct:free`. */
  model: string;
  /** Ordered conversation turns. */
  messages: LLMMessage[];
  /** Sampling temperature. Omitted → provider default. */
  temperature?: number;
  /** Upper bound on generated tokens. Omitted → provider default. */
  maxTokens?: number;
}

/** A chat-completion response (text only — tool calls arrive in Phase 2). */
export interface LLMResponse {
  /** Model that actually produced the completion. */
  model: string;
  /** The assistant message content. */
  content: string;
}

/** Anything that can turn an {@link LLMRequest} into an {@link LLMResponse}. */
export interface LLMClient {
  complete(request: LLMRequest): Promise<LLMResponse>;
}
