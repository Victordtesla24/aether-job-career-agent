/**
 * Record/replay LLM client — the seam that keeps agent tests deterministic.
 *
 * Modes:
 *  - `replay` (default): serve responses only from committed fixtures. No live
 *    client and no network are ever used. This is what CI runs — offline and
 *    reproducible.
 *  - `record`: call the injected live client and persist the response as a
 *    fixture, so the exact interaction can be replayed later.
 *  - `auto`: replay when a fixture exists, otherwise record it. Handy for local
 *    development against real models.
 */
import { FixtureStore } from './fixture-store.js';
import type { LLMClient, LLMRequest, LLMResponse } from './types.js';

export type LLMMode = 'replay' | 'record' | 'auto';

/** Default execution mode, overridable via `AETHER_LLM_MODE`. */
export function resolveMode(env: NodeJS.ProcessEnv = process.env): LLMMode {
  const raw = (env.AETHER_LLM_MODE ?? '').toLowerCase();
  return raw === 'record' || raw === 'auto' ? raw : 'replay';
}

export interface RecordReplayOptions {
  /** Execution mode. Defaults to {@link resolveMode}. */
  mode?: LLMMode;
  /** Fixture store backing replay/record. */
  store: FixtureStore;
  /** Live client — required for `record`/`auto`, forbidden-to-omit there. */
  liveClient?: LLMClient;
}

export class RecordReplayLLMClient implements LLMClient {
  private readonly mode: LLMMode;
  private readonly store: FixtureStore;
  private readonly liveClient?: LLMClient;

  constructor(options: RecordReplayOptions) {
    this.mode = options.mode ?? resolveMode();
    this.store = options.store;
    this.liveClient = options.liveClient;

    if ((this.mode === 'record' || this.mode === 'auto') && !this.liveClient) {
      throw new Error(
        `RecordReplayLLMClient in "${this.mode}" mode requires a live client to call.`,
      );
    }
  }

  async complete(request: LLMRequest): Promise<LLMResponse> {
    if (this.mode === 'replay') {
      return this.store.load(request);
    }

    if (this.mode === 'auto' && this.store.has(request)) {
      return this.store.load(request);
    }

    // record, or auto-with-missing-fixture → call live and persist.
    const live = this.liveClient!;
    const response = await live.complete(request);
    this.store.save(request, response);
    return response;
  }
}
