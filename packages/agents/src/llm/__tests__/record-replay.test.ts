import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  FixtureStore,
  RecordReplayLLMClient,
  fixtureKey,
  type LLMClient,
  type LLMRequest,
  type LLMResponse,
} from '../index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
// Committed, deterministic fixtures live here (shared across the suite).
const FIXTURE_DIR = resolve(HERE, '../../../tests/fixtures/llm');

const SAMPLE_REQUEST: LLMRequest = {
  model: 'meta-llama/llama-3.1-8b-instruct:free',
  messages: [
    { role: 'system', content: 'You are a deterministic test oracle.' },
    { role: 'user', content: 'Reply with exactly: pong' },
  ],
  temperature: 0,
  maxTokens: 16,
};

/** A stub live client that records how many times it was invoked. */
function makeStubClient(response: LLMResponse): { client: LLMClient; calls: () => number } {
  let count = 0;
  return {
    client: {
      async complete() {
        count += 1;
        return response;
      },
    },
    calls: () => count,
  };
}

describe('fixtureKey', () => {
  it('is stable for equivalent requests', () => {
    expect(fixtureKey(SAMPLE_REQUEST)).toBe(fixtureKey({ ...SAMPLE_REQUEST }));
  });

  it('changes when the model changes', () => {
    const other = { ...SAMPLE_REQUEST, model: 'qwen/qwen-2.5-72b-instruct:free' };
    expect(fixtureKey(other)).not.toBe(fixtureKey(SAMPLE_REQUEST));
  });

  it('changes when message content changes', () => {
    const other: LLMRequest = {
      ...SAMPLE_REQUEST,
      messages: [...SAMPLE_REQUEST.messages, { role: 'user', content: 'and again' }],
    };
    expect(fixtureKey(other)).not.toBe(fixtureKey(SAMPLE_REQUEST));
  });

  it('is a 64-char hex sha-256 digest', () => {
    expect(fixtureKey(SAMPLE_REQUEST)).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe('FixtureStore (committed fixtures)', () => {
  it('has the committed sample fixture', () => {
    const store = new FixtureStore(FIXTURE_DIR);
    expect(store.has(SAMPLE_REQUEST)).toBe(true);
  });

  it('loads the recorded response', () => {
    const store = new FixtureStore(FIXTURE_DIR);
    const res = store.load(SAMPLE_REQUEST);
    expect(res.content).toBe('pong');
    expect(res.model).toBe(SAMPLE_REQUEST.model);
  });
});

describe('RecordReplayLLMClient — replay mode', () => {
  it('returns the recorded response without calling the live client', async () => {
    const store = new FixtureStore(FIXTURE_DIR);
    const stub = makeStubClient({ model: 'x', content: 'SHOULD NOT BE USED' });
    const client = new RecordReplayLLMClient({ mode: 'replay', store, liveClient: stub.client });
    const res = await client.complete(SAMPLE_REQUEST);
    expect(res.content).toBe('pong');
    expect(stub.calls()).toBe(0);
  });

  it('throws a helpful error when a fixture is missing', async () => {
    const store = new FixtureStore(FIXTURE_DIR);
    const client = new RecordReplayLLMClient({ mode: 'replay', store });
    const missing: LLMRequest = {
      model: 'meta-llama/llama-3.1-8b-instruct:free',
      messages: [{ role: 'user', content: 'no fixture exists for this' }],
    };
    await expect(client.complete(missing)).rejects.toThrow(/No LLM fixture/i);
  });
});

describe('RecordReplayLLMClient — record & auto modes (temp dir)', () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(resolve(tmpdir(), 'aether-llm-fixtures-'));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('record mode calls the live client and persists a fixture', async () => {
    const store = new FixtureStore(dir);
    const stub = makeStubClient({
      model: SAMPLE_REQUEST.model,
      content: 'recorded-content',
    });
    const client = new RecordReplayLLMClient({ mode: 'record', store, liveClient: stub.client });

    const res = await client.complete(SAMPLE_REQUEST);
    expect(res.content).toBe('recorded-content');
    expect(stub.calls()).toBe(1);
    expect(existsSync(resolve(dir, `${fixtureKey(SAMPLE_REQUEST)}.json`))).toBe(true);

    // A fresh replay client now serves the newly recorded fixture — offline.
    const replay = new RecordReplayLLMClient({ mode: 'replay', store });
    const again = await replay.complete(SAMPLE_REQUEST);
    expect(again.content).toBe('recorded-content');
  });

  it('auto mode replays when present and records when absent', async () => {
    const store = new FixtureStore(dir);
    const stub = makeStubClient({ model: SAMPLE_REQUEST.model, content: 'from-live' });
    const client = new RecordReplayLLMClient({ mode: 'auto', store, liveClient: stub.client });

    // First call: absent → records via live client.
    const first = await client.complete(SAMPLE_REQUEST);
    expect(first.content).toBe('from-live');
    expect(stub.calls()).toBe(1);

    // Second call: present → replays, no additional live call.
    const second = await client.complete(SAMPLE_REQUEST);
    expect(second.content).toBe('from-live');
    expect(stub.calls()).toBe(1);
  });

  it('record mode without a live client throws', () => {
    const store = new FixtureStore(dir);
    expect(() => new RecordReplayLLMClient({ mode: 'record', store })).toThrow(
      /live client/i,
    );
  });
});
