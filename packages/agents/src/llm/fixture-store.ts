/**
 * Deterministic, on-disk store of recorded LLM responses ("fixtures").
 *
 * A fixture is keyed by a stable SHA-256 digest of the *canonicalised* request
 * (model + messages + sampling params). This lets tests and CI replay real
 * model behaviour completely offline: identical requests map to identical keys,
 * so the recorded response is served without any network access or API key.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { LLMRequest, LLMResponse } from './types.js';

/**
 * Canonicalise a request into a stable string. Only the fields that can change
 * model output participate in the key; property order is fixed here so that two
 * structurally-equal requests always serialise identically.
 */
function canonicalise(request: LLMRequest): string {
  return JSON.stringify({
    model: request.model,
    messages: request.messages.map((m) => ({ role: m.role, content: m.content })),
    temperature: request.temperature ?? null,
    maxTokens: request.maxTokens ?? null,
  });
}

/** Stable 64-char hex SHA-256 digest identifying a request's fixture file. */
export function fixtureKey(request: LLMRequest): string {
  return createHash('sha256').update(canonicalise(request)).digest('hex');
}

/** Shape of a persisted fixture file on disk. */
interface FixtureFile {
  /** Echoed request (human-readable context; not used for lookup). */
  request: LLMRequest;
  /** The recorded response served on replay. */
  response: LLMResponse;
}

/**
 * Reads and writes LLM fixtures under a single directory. One JSON file per
 * request key: `<dir>/<fixtureKey>.json`.
 */
export class FixtureStore {
  constructor(private readonly dir: string) {}

  /** The fixture key for a request (exposed for tests and tooling). */
  key(request: LLMRequest): string {
    return fixtureKey(request);
  }

  /** Absolute path of the fixture file for a request. */
  private pathFor(request: LLMRequest): string {
    return resolve(this.dir, `${fixtureKey(request)}.json`);
  }

  /** True when a recorded fixture exists for the request. */
  has(request: LLMRequest): boolean {
    return existsSync(this.pathFor(request));
  }

  /**
   * Load the recorded response for a request.
   * @throws if no fixture has been recorded (message matches /No LLM fixture/).
   */
  load(request: LLMRequest): LLMResponse {
    const path = this.pathFor(request);
    if (!existsSync(path)) {
      throw new Error(
        `No LLM fixture found for key ${fixtureKey(request)} (model ${request.model}). ` +
          `Record it with AETHER_LLM_MODE=record before running offline.`,
      );
    }
    const parsed = JSON.parse(readFileSync(path, 'utf8')) as FixtureFile;
    return parsed.response;
  }

  /** Persist a response for a request, creating the directory if needed. */
  save(request: LLMRequest, response: LLMResponse): void {
    mkdirSync(this.dir, { recursive: true });
    const file: FixtureFile = { request, response };
    writeFileSync(this.pathFor(request), `${JSON.stringify(file, null, 2)}\n`, 'utf8');
  }
}
