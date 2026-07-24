# G-A adversarial models-live re-sample — 2026-07-24 (W-F, qa-adversary role)

Fresh evidence from THIS run (prior phase reports treated as testimony only).

## 1. Fresh catalog pull (2026-07-24T02:10Z)

- Upstream `GET /models` (OpenRouter, backend key — never printed): **343 models**.
- App catalog `GET /api/agents/providers/openrouter/models` (prod, authed): **333 models**.
- Delta fully accounted for (10): 5 exact-id denylist per ADR-ML-4 (`allenai/olmo-3-32b-think`, `inflection/inflection-3-pi`, `relace/relace-apply-3`, `morph/morph-v3-fast`, `openai/o3-deep-research` — proven permanently non-chat/404) + 5 sentinel dynamic-priced rows with pricing = −1 (`openrouter/auto`, `auto-beta`, `bodybuilder`, `fusion`, `pareto-code`) excluded by the negative-price guard. **0 app-catalog models missing upstream** — no stale entries.

## 2. Selection re-sample (≥20% floor)

Random sample (seed 20260724) of **70/333 models (21%)** set on `resumeTailoring` via `PUT /api/agents/config/resumeTailoring` on prod, each read back via GET: **70/70 persisted correctly, 0 failures**; original model (`z-ai/glm-5.2`) restored and verified. Raw result: `selection-resample.json`.

## 3. Live probes (≥5 floor) — transcripts in `adversarial-probe-transcripts.txt` (key redacted)

| Model | Outcome | Cost |
|---|---|---|
| openai/gpt-4o-mini | OK (content "OK", 13 tok) | $0.0000024 |
| google/gemini-2.5-flash-lite | OK (6 tok) | ~$0.0000009 |
| deepseek/deepseek-chat-v3-0324 | OK (11 tok) | $0.0000074 |
| meta-llama/llama-3.3-70b-instruct | OK (18 tok) | $0.0000029 |
| anthropic/claude-haiku-4.5 | OK (16 tok) | $0.0000317 |
| z-ai/glm-5.2 | OK (reasoning model; finish_reason=length at max_tokens=16 — expected behaviour, not a failure) | <$0.0001 |

Stale-id control: `anthropic/claude-3.5-haiku` (NOT in app catalog) honestly 404s upstream ("No endpoints found") — confirms the app catalog correctly excludes dead ids rather than displaying them. Total probe spend < $0.0002.

## 4. Real agent run through the app (prod)

`POST /api/agents/tailor/run` (job cb82d1091f294eb6a3b685923) → 202 enqueued (async pipeline), run `c22f346076a07594120ffbdd4` → **completed** (worker executed live LLM via user-selected model). Plus scout + fit-scorer runs (200/202) — see `../runtime/final-observation-window.log` window exercises.

**Verdict: fresh catalog honest, selection persistence 100% on 21% sample, live probes 6/6 catalog members OK, real run executed. No new findings.**
