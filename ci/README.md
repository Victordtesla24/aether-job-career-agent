# CI configuration

Continuous integration runs from
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). This folder keeps a
**verbatim mirror** at [`github-actions-ci.yml`](./github-actions-ci.yml) as a
reviewable, always-tracked copy (see "Why the mirror exists" below).

## What the pipeline runs

On every push to `main` / `phase-*/**` and every PR into `main`:

- **security scan** — fails if `.env` is ever tracked, or if a real-looking
  OpenRouter key (`sk-or-v1-<long>`) appears anywhere in source. The regex
  requires a long alphanumeric tail so short, clearly-synthetic
  test/doc placeholders are not flagged.
- **node workspace** (Node 20): `pnpm install --frozen-lockfile` →
  lint → type-check → unit tests (Vitest, `@aether/web`) → build.
  (The orphaned `packages/*` TS layer and its Prisma-client generation step
  were removed in the Workstream C dedup; `packages/db/src/schema.prisma`
  remains as the documentation-only schema-of-record.) Agent tests run with
  `AETHER_LLM_MODE=replay`, so they replay committed fixtures and never touch
  the network.
- **api** (Python 3.11): ruff → mypy → pytest.
- **e2e smoke** (Playwright): builds the web app and runs the dashboard smoke
  suite against a real Chromium (runs after `node` succeeds).

On a nightly schedule (and manual `workflow_dispatch`) only:

- **live OpenRouter** (non-blocking, `continue-on-error`): refreshes fixtures
  against real models using the `OPENROUTER_API_KEY` repository secret. It is
  skipped automatically when the secret is unset and never gates PRs.

## Why the mirror exists

GitHub blocks a GitHub App from creating or updating files under
`.github/workflows/` unless the app has been granted the **`workflows`**
permission. If a push that touches `.github/workflows/ci.yml` is rejected for
that reason, the mirror in this folder still carries the exact, up-to-date
workflow so it can be applied another way (see below). Keep the two files
identical when editing:

```bash
cp .github/workflows/ci.yml ci/github-actions-ci.yml   # after any change
```

## If a workflow push is rejected

If `git push` is refused because the app lacks the `workflows` scope, use either:

1. **Grant the permission**, then re-push — grant the Abacus GitHub App the
   `workflows` permission at
   <https://github.com/apps/abacusai/installations/select_target> and push again.
2. **Add it via the GitHub UI** — copy `ci/github-actions-ci.yml` into
   `.github/workflows/ci.yml` using the web editor (a UI commit is performed as
   *you*, not the app, so no extra permission is needed).

The test harness (Vitest + pytest configs, scripts) is wired into the repo and
runs locally regardless of whether the hosted workflow is active.
