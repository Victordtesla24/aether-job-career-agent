# LAUNCH-READY Roster Manifest (spec §0.2)

- Generated: 2026-07-23T15:39:37Z (PHASE 0 Step 1, fresh run — no prior LAUNCH-READY-STATE.json)
- Requirement: 18 `.claude/agents/*.md` files with the EXACT `model:` frontmatter from §0.2; `model: inherit` FORBIDDEN anywhere.
- Verification: `grep -c 'model: inherit' .claude/agents/*.md` → zero matches across all files (including legacy prior-phase agent files left in place).
- Execution note: this run is performed by a single engineer acting in all roles; the roster documents the governance/cost tiering the spec mandates.

| File | Model | Tier rationale |
|---|---|---|
| .claude/agents/scout.md | claude-haiku-4-5 | inventory: code maps, file-system census, reference tracing |
| .claude/agents/janitor.md | claude-haiku-4-5 | executes APPROVED deletions/moves/archives only; never decides |
| .claude/agents/evidence.md | claude-haiku-4-5 | screenshots, transcripts, artifact filing, checkpoint writes |
| .claude/agents/runtime-monitor.md | claude-haiku-4-5 | ALWAYS-ON server console + journalctl log tailing |
| .claude/agents/browser-monitor.md | claude-haiku-4-5 | browser console/network exception capture |
| .claude/agents/deployer.md | claude-haiku-4-5 | build/deploy per runbook, health checks, branch hygiene |
| .claude/agents/screen-tester.md | claude-sonnet-4 | human-grade per-screen manual testing |
| .claude/agents/model-prober.md | claude-sonnet-4 | per-model live run verification (Workstream A) |
| .claude/agents/test-author.md | claude-sonnet-4 | failing tests BEFORE every fix/feature |
| .claude/agents/fixer-medium.md | claude-sonnet-4 | standard defect fixes + feature implementation |
| .claude/agents/reviewer.md | claude-sonnet-4 | code review (never the author) |
| .claude/agents/dedup-surgeon.md | claude-sonnet-4 | consolidation refactors from the de-dup inventory |
| .claude/agents/doc-updater.md | claude-sonnet-4 | docs refresh matching deployed truth (runs near-last) |
| .claude/agents/ux-perfectionist.md | claude-sonnet-4 | top-10-paid-app polish audit per screen (§7) |
| .claude/agents/fixer-hard.md | claude-opus-4 | cross-cutting/architectural fixes only |
| .claude/agents/catalog-engineer.md | claude-opus-4 | OpenRouter live-catalog feature (Workstream A FIX-1) |
| .claude/agents/qa-adversary.md | claude-opus-4 | 3rd-party independent adversarial reviewer |
| .claude/agents/risk-officer.md | claude-opus-4 | sole approver of RISKY deletions & destructive ops |

## Reconciliation vs pre-existing roster (prior MODELS-LIVE phase)

- Pre-existing files scout/evidence/runtime-monitor/browser-monitor/deployer already at claude-haiku-4-5 (unchanged).
- Drifted model values repaired to §0.2 exact values: screen-tester, model-prober, test-author, fixer-medium, reviewer, doc-updater (`claude-sonnet-5` → `claude-sonnet-4`); fixer-hard, catalog-engineer, qa-adversary (`claude-opus-4-8` → `claude-opus-4`).
- Newly created (missing from roster): janitor.md, dedup-surgeon.md, ux-perfectionist.md, risk-officer.md.
- Legacy prior-phase agent files (arch.md, billing-arch.md, claim-auditor.md, deploy.md, doc-audit.md, fixer.md, infra-discovery.md, log-tailer.md, migrator.md, qa-reviewer.md, qa.md, researcher.md, tester.md, writer-audit.md) left untouched — not on this subtask's deletion list; none contain `model: inherit`.
