# Aether Model Catalog — Per-Agent Live Model Choice

**Status:** Built and live in production. Delivered in the **MODELS-LIVE** run (2026-07-22; all code
fixes live @ commit `51f1ec8`) atop the model-choice feature shipped 2026-07-21 (`64cb4fc`,
`ceb8c23`).

**Production:** https://5cb5f0620.abacusai.cloud
**Repo:** `apps/api/app/services/llm_client.py` (catalog fetch/cache/curation, `resolve_provider`),
`apps/api/app/routers/agents.py` (catalog/config/validation endpoints), `apps/web/src/components/agents/AgentModelPicker.tsx` (per-agent UI).
**Evidence root:** `uat/reports/evidence/models-live/models/` and `uat/reports/evidence/models-live/catalog/`.

---

## 1. What this is

Every LLM-backed agent (`resumeTailoring`/backend `tailor`, `coverLetter`, `emailAgent`) has its
own model picker on `/dashboard/agents`, sourced from OpenRouter's live `/models` catalog. A user
can choose any model by budget — a frontier model or a free open-source one — independently per
agent. The choice persists to that agent's own `AgentConfig.model` row and is what the agent
actually runs on the next time it executes; it is not a single global default.

Deterministic agents (`scout`, `fitScorer`, `matcher`, `supervisor`) make no LLM call at all, and
`storyExtraction` (backend `storyExtractor`) runs on a fixed `STRUCTURED`-tier model that is
deliberately **not** user-overridable (kept off the picker to guarantee reliable structured JSON
output). Both cases render an honest **"Fixed model — not user-selectable"** lock in the UI instead
of a picker whose selection would silently be ignored.

## 2. Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/agents/providers/{provider}/models` | Live, curated catalog for `provider`. Cached (see §3); never fabricates a list — an honest `400` when no credential/catalog is reachable and nothing cached. |
| `POST` | `/api/agents/providers/{provider}/models/refresh` | Forces a fresh upstream fetch, bypassing the TTL. Same response envelope as the `GET`. On an upstream failure with a warm cache, still serves the last-good data (`stale: true`) rather than blocking. |
| `GET` | `/api/agents/catalog` | Per-agent view: current model, `modelOverridable` (the authoritative signal the FE picker lock reads), run status. |
| `PUT` | `/api/agents/config/{agentKey}` | Saves a per-agent model choice (and provider/credential/temperature/thinking-effort). Validates the model id (§4). |

`{provider}` is `openrouter` (the only provider with a genuine live catalog today) or `anthropic`
(a small hardcoded, indicative — **not** exhaustive — shortlist of 3 current Claude models, since
Anthropic has no open `/models` listing endpoint the app can call).

Response envelope (`GET`/`POST refresh`):

```json
{
  "provider": "openrouter",
  "models": [
    {"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash",
     "promptPerM": 0.14, "completionPerM": 0.28, "contextLength": 131072,
     "tier": "budget", "reasoning": false}
  ],
  "count": 357,
  "lastRefreshedAt": "2026-07-22T23:06:57.764850+00:00",
  "stale": false
}
```

`count` always equals `len(models)`. `tier` is a budget bucket derived from the prompt price
(`free` / `budget` ≤ $0.50/M / `standard` ≤ $3/M / `premium`), used to group the picker's rows.

**Fresh, on-the-spot verification** (this doc's own evidence, not a stale prior sweep):
`GET /api/agents/providers/openrouter/models` called against production at
`2026-07-22T23:06:57Z` returned `count: 357`, `lastRefreshedAt` equal to the call time (cold-cache
fetch), `stale: false`, and confirmed all 5 denylisted ids (§5) absent. Prior sweeps in this same
run recorded `337` (§3.4.2 baseline) and `335` (§8 Stage-3 re-sample) — the count is **not** a fixed
number; it tracks OpenRouter's own upstream catalog, which adds and removes models over time. Do
not treat any single count in this document (or in `README.md`) as a permanent fact — re-pull the
endpoint for the current number.

## 3. Caching and freshness

- The OpenRouter catalog is fetched with the signed-in user's own OpenRouter credential when one is
  configured, else the deployment credential (the catalog itself is identical for any valid key, so
  a bad personal key falls back rather than hiding the catalog).
- Successful fetches are cached in-process for **1 hour** (`_MODEL_CATALOG_TTL = 3600.0` seconds,
  `apps/api/app/services/llm_client.py`).
- `lastRefreshedAt` is the real wall-clock moment the currently-served list was fetched from
  upstream (not the moment of the API call); `stale` is `true` only when that cached fetch is past
  the TTL **and** the most recent refresh attempt failed — i.e. the UI is looking at last-good, not
  current, data.
- `POST .../models/refresh` forces a new upstream call regardless of TTL (the manual "Refresh
  catalog" affordance). If every credential's fetch attempt fails, the last-good cache is served
  (flagged `stale: true`) rather than leaving the picker empty or fabricating a list; only when
  there is genuinely no cache **and** no working upstream does the endpoint return an honest `400`.
- Model-id **validation** on save (`PUT /api/agents/config/{agentKey}`) never opens a network
  connection — a cold/never-warmed cache makes the id *accepted* rather than rejected on a
  transient gap (it then fails honestly at run time if the id turns out to be wrong).

## 4. Validation (honest 422, no silent substitution)

`PUT /api/agents/config/{agentKey}` rejects an OpenRouter model id that is not present in the
currently-cached live catalog:

```
HTTP 422
{"detail": "model '<id>' is not in the live openrouter catalog — choose one from the catalog."}
```

A bare `claude-…`/`anthropic…` id (direct-Anthropic, no `/`) or the literal `deterministic` sentinel
is always accepted — the static Anthropic shortlist is indicative, not an exhaustive allowlist, so
it is never used to *reject* a model (that would be the hardcoded-allowlist antipattern this
project deliberately avoids).

Separately, at **run time**, if a user's chosen model fails (upstream error, malformed output,
timeout, etc.), the run fails honestly and any reserved quota is refunded — it is **never** silently
retried against a different ("fallback") model and reported as a success. This is verified live in
`uat/reports/evidence/models-live/models/NO-SUBSTITUTION-PROOF.md` (a deliberately-chosen
denylisted id was run end-to-end; the job terminated `failed`, quota was refunded, and no other
model was substituted).

## 5. Curation: the proven-broken denylist

OpenRouter's `/models` payload carries **no availability signal** — a permanently dead model has
the exact same schema entry as a working one. A heuristic chat-compatibility filter (e.g. "reject
any model whose `supported_parameters` omits `temperature`") was considered and rejected as
dishonest: it would also hide 50+ genuinely functional `anthropic/*`-via-OpenRouter models that use
native parameters instead of `temperature`.

Instead, `_curate_openrouter_models` (`apps/api/app/services/llm_client.py`) filters exactly 5
model ids, by exact string match only, maintained as `_OPENROUTER_PROVEN_BROKEN_IDS`:

| Model id | Failure class | Evidence |
|---|---|---|
| `allenai/olmo-3-32b-think` | no-endpoint 404 (every attempt) | `uat/reports/evidence/models-live/models/RUN-SWEEP.md` |
| `inflection/inflection-3-pi` | no-endpoint 404 (every attempt) | same |
| `relace/relace-apply-3` | structurally non-chat (`apply` endpoint rejects multi-turn chat requests) | same |
| `morph/morph-v3-fast` | structurally non-chat (`apply/diff` endpoint) | same |
| `openai/o3-deep-research` | structurally non-chat (deep-research needs a different API surface than chat-completion) | same |

These 5 were identified by a real 82-model run sweep of `resumeTailoring`/`tailor` against a real
job + résumé (`RUN-SWEEP.md` §"Failure classification") — not a synthetic test. **Only** permanent
failure classes (no-endpoint 404, structurally-incompatible 400) qualify for this list.
**Transient** failures — rate-limits, timeouts, a one-off malformed response — must never be added,
even when observed on the production-default model (`RUN-SWEEP.md` records exactly such a transient
blip on `deepseek/deepseek-v4-pro`, which stays in the catalog because the failure did not
reproduce). Extending the list requires citing new run-sweep evidence of a *permanent* failure, by
exact id.

## 6. Provider / billing routing

`resolve_provider(model_id)` (`apps/api/app/services/llm_client.py`) is the single source of truth
every billing/verify/run-time code path calls to decide which credential a model id bills against:

- **Any id containing a `/`** (e.g. `deepseek/deepseek-v4-flash`, or OpenRouter's own
  `anthropic/claude-3-haiku`) is OpenRouter-namespaced and **always bills through OpenRouter** —
  including the 15+ `anthropic/*` ids OpenRouter itself serves. Those do **not** route to the
  direct Anthropic API even though the id starts with `anthropic/`; the presence of the slash wins.
- **A bare id** starting with `claude-` or `anthropic` (no slash) routes to the **direct Anthropic
  API**.
- Any other bare id defaults to OpenRouter.

This distinction exists specifically because early code used a `startswith("anthropic/")` heuristic
that silently crossed the billing boundary for OpenRouter's own `anthropic/*` catalog entries — a
real defect caught in adversarial review of the original model-choice feature (`ceb8c23`) and now
covered by the slash-first rule above. The per-agent picker states this routing implication directly
in the UI next to every agent's model list ("These models come from the OpenRouter catalog —
choosing one routes this agent's runs through OpenRouter…").

## 7. Anthropic credential (separate from the OpenRouter catalog)

The Anthropic provider is configured independently of the OpenRouter model picker, via two paths:

1. **Manual paste** — a Console API key (`sk-ant-api…`) or a pasted Claude Code OAuth token
   (`sk-ant-oat<N>-…`, the output of `claude setup-token`), auto-detected from the secret prefix.
2. **"Connect with Anthropic (subscription)"** — an in-app OAuth flow: the button opens Anthropic's
   own authorize page (`https://claude.com/cai/oauth/authorize`) in a new tab; the operator approves
   and pastes back a one-time `code#state`; the server exchanges it server-side via PKCE
   (`https://platform.claude.com/v1/oauth/token`) and stores the access + refresh token encrypted.
   The access token auto-refreshes ~5 minutes before expiry; a failed refresh marks the credential
   `needs_reauth` and the UI shows a "Renew now" / reconnect affordance rather than silently reusing
   a stale token or falling back to a different provider. See
   `apps/api/app/services/anthropic_oauth.py` and `docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md`
   (`ADR-ML-1`, `ADR-ML-2`, `ADR-ML-2a`, `ADR-ML-5`) for the full mechanics and rulings.

Both paths land in the same `ProviderCredential('anthropic')` seam that `resolve_provider` /
`resolve_credential` read, so a bare `claude-…` run resolves it the same way regardless of which
path was used to configure it.
