# CI configuration

This folder holds the project's continuous-integration definition as an **inert
template**:

- [`github-actions-ci.yml`](./github-actions-ci.yml) — a GitHub Actions workflow
  that runs the full gate on every push/PR:
  - **web** (Node 20): `pnpm install --frozen-lockfile` → lint → type-check →
    unit tests (Vitest) → build
  - **api** (Python 3.11): ruff → mypy → pytest

## Why it lives here (and not in `.github/workflows/`)

GitHub blocks a GitHub App from creating or updating files under
`.github/workflows/` unless the app has been granted the **`workflows`**
permission. To keep merges to `main` friction-free (per the "no CI-CD
complication" directive), the workflow is version-controlled here where it is
**not** auto-executed by GitHub Actions.

## Activating CI

When you're ready to turn CI on, either:

1. **Grant the permission + move the file** — grant the Abacus GitHub App the
   `workflows` permission at
   <https://github.com/apps/abacusai/installations/select_target>, then:
   ```bash
   mkdir -p .github/workflows
   git mv ci/github-actions-ci.yml .github/workflows/ci.yml
   git commit -m "ci: activate GitHub Actions workflow"
   git push
   ```
2. **Or add it directly in the GitHub UI** — copy the file contents into a new
   `.github/workflows/ci.yml` via the web editor (the UI push is performed as
   *you*, not the app, so no extra permission is needed).

The test harness itself (Vitest + pytest configs, scripts) is already wired in
the repo and runs locally regardless of whether the workflow is active.
