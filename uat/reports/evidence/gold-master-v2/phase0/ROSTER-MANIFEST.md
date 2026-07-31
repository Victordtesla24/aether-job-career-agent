# GOLD-MASTER-V2 Sub-Agent Roster Manifest

Generated: 2026-07-30T22:36:50Z  |  Run: GOLD-MASTER-V2  |  Orchestrator: claude-opus-5[1m] (xhigh, brain-only)

## §0.2 required roster — verification

| agent | required model | on-disk model | status |
|---|---|---|---|
| scout | claude-haiku-4-5 | claude-haiku-4-5 | OK |
| evidence | claude-haiku-4-5 | claude-haiku-4-5 | OK |
| runtime-monitor | claude-haiku-4-5 | claude-haiku-4-5 | OK |
| browser-monitor | claude-haiku-4-5 | claude-haiku-4-5 | OK |
| deployer | claude-haiku-4-5 | claude-haiku-4-5 | OK |
| janitor | claude-haiku-4-5 | claude-haiku-4-5 | OK |
| test-author | claude-sonnet-4 | claude-sonnet-4 | OK |
| fixer-medium | claude-sonnet-4 | claude-sonnet-4 | OK |
| screen-tester | claude-sonnet-4 | claude-sonnet-4 | OK |
| reviewer | claude-sonnet-4 | claude-sonnet-4 | OK |
| doc-updater | claude-sonnet-4 | claude-sonnet-4 | OK |
| ai-loop-engineer | claude-sonnet-4 | claude-sonnet-4 | OK |
| fixer-hard | claude-opus-4 | claude-opus-4 | OK |
| qa-adversary | claude-opus-4 | claude-opus-4 | OK |
| risk-officer | claude-opus-4 | claude-opus-4 | OK |

## `model: inherit` audit (FORBIDDEN per §0.2)

Files with `model: inherit`: **0** (required: 0)

## Full .claude/agents inventory

```
ai-loop-engineer.md      claude-sonnet-4
arch.md                  claude-opus-4-8
billing-arch.md          claude-opus-4-8
browser-monitor.md       claude-haiku-4-5
catalog-engineer.md      claude-opus-4
claim-auditor.md         claude-sonnet-5
dedup-surgeon.md         claude-sonnet-4
deploy.md                haiku
deployer.md              claude-haiku-4-5
doc-audit.md             haiku
doc-updater.md           claude-sonnet-4
evidence.md              claude-haiku-4-5
fixer-hard.md            claude-opus-4
fixer-medium.md          claude-sonnet-4
fixer.md                 opus
infra-discovery.md       claude-haiku-4-5
janitor.md               claude-haiku-4-5
log-tailer.md            claude-haiku-4-5
migrator.md              claude-sonnet-5
model-prober.md          claude-sonnet-4
qa-adversary.md          claude-opus-4
qa-reviewer.md           sonnet
qa.md                    claude-sonnet-5
researcher.md            claude-haiku-4-5
reviewer.md              claude-sonnet-4
risk-officer.md          claude-opus-4
runtime-monitor.md       claude-haiku-4-5
scout.md                 claude-haiku-4-5
screen-tester.md         claude-sonnet-4
test-author.md           claude-sonnet-4
tester.md                sonnet
ux-perfectionist.md      claude-sonnet-4
writer-audit.md          claude-sonnet-5
```
