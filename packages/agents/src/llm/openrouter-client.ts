/**
 * Live OpenRouter transport implementing {@link LLMClient}.
 *
 * This is only exercised in `record` mode (and the non-blocking nightly live
 * job) — never in normal test/CI runs, which replay committed fixtures. The
 * API key is read once and NEVER logged, echoed, or serialised anywhere.
 *
 * `fetch` is injectable so it can be unit-tested without real network access.
 */
import type { LLMClient, LLMRequest, LLMResponse } from './types.js';

type FetchLike = typeof globalThis.fetch;

export interface OpenRouterOptions {
  /** OpenRouter API key. Required; kept private and never logged. */
  apiKey: string;
  /** Override the base URL (defaults to the public OpenRouter endpoint). */
  baseUrl?: string;
  /** Sent as `HTTP-Referer` for OpenRouter attribution. */
  referer?: string;
  /** Sent as `X-Title` for OpenRouter attribution. */
  title?: string;
  /** Injectable fetch (defaults to the global). */
  fetchImpl?: FetchLike;
}

const DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1';

interface OpenRouterChatResponse {
  model?: string;
  choices?: Array<{ message?: { content?: string } }>;
}

export class OpenRouterClient implements LLMClient {
  readonly #apiKey: string;
  private readonly baseUrl: string;
  private readonly referer: string;
  private readonly title: string;
  private readonly fetchImpl: FetchLike;

  constructor(options: OpenRouterOptions) {
    if (!options.apiKey) {
      throw new Error('OpenRouterClient requires an API key.');
    }
    this.#apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, '');
    this.referer = options.referer ?? 'https://github.com/Victordtesla24/aether-job-career-agent';
    this.title = options.title ?? 'Aether';
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
  }

  async complete(request: LLMRequest): Promise<LLMResponse> {
    const res = await this.fetchImpl(`${this.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${this.#apiKey}`,
        'HTTP-Referer': this.referer,
        'X-Title': this.title,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: request.model,
        messages: request.messages,
        temperature: request.temperature ?? 0,
        max_tokens: request.maxTokens,
      }),
    });

    if (!res.ok) {
      // Never include auth headers/key in the error — status + body only.
      const body = await res.text().catch(() => '');
      throw new Error(`OpenRouter request failed (${res.status}): ${body.slice(0, 500)}`);
    }

    const data = (await res.json()) as OpenRouterChatResponse;
    const content = data.choices?.[0]?.message?.content ?? '';
    return { model: data.model ?? request.model, content };
  }
}
