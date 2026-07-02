/**
 * @aether/agents/llm — LLM client contracts and the record/replay test seam.
 *
 * Import surface:
 *  - {@link LLMClient} / {@link LLMRequest} / {@link LLMResponse} — the contract.
 *  - {@link FixtureStore} / {@link fixtureKey} — deterministic on-disk fixtures.
 *  - {@link RecordReplayLLMClient} — offline-first client used by tests & CI.
 *  - {@link OpenRouterClient} — live transport (record mode / nightly only).
 */
export type { LLMClient, LLMMessage, LLMRequest, LLMResponse } from './types.js';
export { FixtureStore, fixtureKey } from './fixture-store.js';
export {
  RecordReplayLLMClient,
  resolveMode,
  type LLMMode,
  type RecordReplayOptions,
} from './record-replay-client.js';
export { OpenRouterClient, type OpenRouterOptions } from './openrouter-client.js';
