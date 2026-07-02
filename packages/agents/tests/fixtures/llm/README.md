# LLM fixtures (record / replay)

This directory holds **recorded LLM responses** used to keep agent tests
deterministic and completely offline. Every fixture is a single JSON file named
after the SHA‑256 digest of its request:

```
<fixtureKey>.json
```

`fixtureKey` (see `packages/agents/src/llm/fixture-store.ts`) hashes the
_canonicalised_ request — model, messages, `temperature`, and `maxTokens`. Two
structurally-identical requests therefore map to the same key and the same
recorded response, with no network access and no API key required.

## File shape

```jsonc
{
  "request":  { "model": "...", "messages": [ ... ], "temperature": 0, "maxTokens": 16 },
  "response": { "model": "...", "content": "..." }
}
```

`request` is echoed only for human context; lookup is purely by filename key.
`response` is what `FixtureStore.load()` returns on replay.

## Modes (`RecordReplayLLMClient`)

Controlled by the `AETHER_LLM_MODE` environment variable:

| Mode      | Behaviour                                                                 | Needs live client? | Needs `OPENROUTER_API_KEY`? |
| --------- | ------------------------------------------------------------------------- | ------------------ | --------------------------- |
| `replay`  | **Default.** Serve only from committed fixtures. Fully offline.           | No                 | No                          |
| `record`  | Call the live client, then persist the response as a fixture.             | Yes                | Yes                         |
| `auto`    | Replay if a fixture exists, otherwise record it.                          | Yes                | Yes                         |

Unset / unknown values fall back to `replay`.

## How CI uses these

- **Unit tests & CI run in `replay` mode only** — deterministic, hermetic, and
  key-free. This is what the `test` scripts and the GitHub Actions workflow run.
- A **separate, non-blocking nightly job** may run in `record`/`auto` mode with a
  real `OPENROUTER_API_KEY` to refresh fixtures against live models. Its failures
  never block the main pipeline.

## Recording a new fixture

1. Add or update a test that issues the request you want to capture.
2. Run it once with a real key, in record mode:

   ```bash
   AETHER_LLM_MODE=record OPENROUTER_API_KEY=sk-... \
     pnpm --filter @aether/agents test
   ```

3. Commit the newly written `<fixtureKey>.json`. Subsequent runs replay it
   offline.

## Ground rules

- **Never commit an API key.** `OPENROUTER_API_KEY` is only ever read from the
  environment for `record`/`auto`; it is never logged, echoed, or written into a
  fixture file.
- Fixtures are **committed on purpose** — they are the offline source of truth
  for tests.
- Keep fixture responses small and clearly synthetic; they exist to pin
  behaviour, not to mirror full production payloads.
