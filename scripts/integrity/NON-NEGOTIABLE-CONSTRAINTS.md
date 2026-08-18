# Non-negotiable engineering constraints

Binding on every contributor — human or AI agent — in **every** environment
(dev, test, staging, production). These are enforced mechanically, not on trust:
see "Enforcement" below. Bypassing an enforcement point is itself a violation.

## Prohibited absolutely

1. **No fabricated implementations.** No placeholder, mock, stub or simulated
   code in a shipped path. No `MOCK_MODE`/`SIMULATE`/`USE_FAKE` flags.
2. **No dummy credentials.** No test/example API keys, no `changeme`,
   `password123`, `your-key-here` literals.
3. **No fabricated data or modes.** `AETHER_LLM_MODE=replay|fixture|mock`,
   discovery fixtures, and dry-run flags are forbidden in any deployed
   environment — they produce results that look real and are not.
4. **No duplicate code.** Before creating a file, confirm an equivalent does not
   already exist. Byte-identical copies are rejected.
5. **No misplaced files.** Shipped source belongs in an approved directory.
6. **No masked errors or suppressed warnings.** No broad `except: pass`, empty
   `catch {}`, `@ts-nocheck`, `@ts-ignore`, file-wide `eslint-disable`, blanket
   `# noqa` / `# type: ignore` without a stated reason.
7. **No disabled verification.** No unconditional skipped tests, no
   `continue-on-error`, no `|| true` after a test/lint/build command.
8. **No ignoring defects by calling them legacy.** Runtime errors, warnings,
   browser exceptions, UI/UX defects and partial implementations are to be fixed
   or explicitly reported — never dismissed as pre-existing.

8b. **No lingering branches or pull requests.** `main` is the single source of
   truth and must always hold the latest deployed code. A working branch is
   permitted during development but must be merged and deleted as soon as its
   code is deployed and verified. No open PRs may be left standing.
   Enforced by the guardian (R8): fully-merged branches are deleted
   automatically; branches holding unmerged commits are **escalated, never
   destroyed** — the guardian will not discard work.

## Prohibited in reporting

9. **No partial delivery claimed as complete.** If any requirement is unmet, the
   work is incomplete — say so, and say exactly which part.
10. **No claiming a feature, component or capability exists** without having
    exercised it.
11. **No confirming anything to the user that has not been verified twice** by
    direct observation (run it, read the real output). Assumption is not
    verification; a passing harness that was never proven to detect failure is
    not verification either.
12. **No excuses, no palming work back to the user, no "good enough".**

## Enforcement (mechanical, not advisory)

| Point | What runs | Effect |
|---|---|---|
| Pre-commit | `.git/hooks/pre-commit` -> `integrity_guard.py` | commit blocked |
| CI | "Integrity guard (blocking)" step in `vps-staging.yml` | pipeline fails |
| Service start | `ExecStartPre=runtime_env_guard.sh` on all 5 units | service refuses to boot |

Rules R1-R7 are implemented in `scripts/integrity/integrity_guard.py`. The guard
is calibrated for **high signal**: it targets executable constructs and config
values, never prose, because a guard that cries wolf gets ignored. Its detection
was proven by planting one deliberate violation per rule and confirming each was
caught (exit 1), then confirming a clean tree passes (exit 0).

### Waivers
`scripts/integrity/waivers.txt`, one `path::rule::reason` per line. A waiver with
no reason fails the guard. Waivers are for documented, deliberate decisions —
never for convenience.

### Verification standard before claiming done
Run and read the output of:
```
python3 scripts/integrity/integrity_guard.py     # must exit 0
pnpm lint && pnpm type-check && pnpm test && pnpm build
python3 scripts/integrity/../../.agent/verify/api_sweep.py <base> <label>   # 0 x 5xx
node .agent/verify/ui/ui_pages.mjs <base> <label> <email> <pw>              # 0 JS/API errors
```
