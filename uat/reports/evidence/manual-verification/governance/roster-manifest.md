# MANUAL-VERIFICATION Run — Sub-Agent Roster Manifest (§0.2 Step 0)
- Generated: 2026-07-17T13:05:40Z · Repo HEAD at run start: 53f0e084da5b460835c32d3e07d496e6e67a8616
- Locations: /home/ubuntu/.claude/agents/ AND /home/ubuntu/github_repos/aether-job-career-agent/.claude/agents/ (identical copies)
- Verification: zero `model: inherit` in either dir; zero fable-tier models in any roster file (checked 2026-07-17T13:05:40Z).

| File | model: |
|---|---|
| screen-tester.md | claude-sonnet-4 |
| claim-auditor.md | claude-sonnet-4 |
| evidence.md | claude-haiku-4-5 |
| log-tailer.md | claude-haiku-4-5 |
| scout.md | claude-haiku-4-5 |
| fixer-medium.md | claude-sonnet-4 |
| fixer-hard.md | claude-opus-4 |
| test-author.md | claude-sonnet-4 |
| reviewer.md | claude-sonnet-4 |
| qa-adversary.md | claude-opus-4 |
| deployer.md | claude-haiku-4-5 |
| doc-updater.md | claude-sonnet-4 |

Governance: orchestrator = claude-fable-5 (brain only, per §0.1). Any fable-tier sub-agent spawn = CRITICAL VIOLATION → kill, log in docs/delivery/MANUAL-VERIFICATION-GOVERNANCE-AUDIT.md, respawn on correct model.
Pre-existing non-roster agent files from prior phases remain on disk (arch, billing-arch, migrator, qa, qa-reviewer, tester, researcher, infra-discovery, writer-audit, fixer, deploy, doc-audit) — none use inherit/fable; they are NOT part of this run's roster.

## Amendment 1 — 2026-07-17T13:13:10Z (model availability remap)
`claude-sonnet-4` / `claude-opus-4` are not available in this harness (spawn API error). Remapped same-tier, all 12 files in both dirs: sonnet-4→**claude-sonnet-5** (screen-tester, claim-auditor, fixer-medium, test-author, reviewer, doc-updater); opus-4→**claude-opus-4-8** (fixer-hard, qa-adversary); haiku files unchanged (claude-haiku-4-5 valid). Zero inherit / zero fable re-verified. Rationale + spawn-error evidence logged in docs/delivery/MANUAL-VERIFICATION-GOVERNANCE-AUDIT.md entry 1.
