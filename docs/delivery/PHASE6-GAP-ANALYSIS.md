# PHASE 6 — GAP ANALYSIS (master ledger)

**Run:** Aether Career Agent Phase 6 — subscription/billing/admin/sourcing-compliance/quality
**Prompt:** `/home/ubuntu/aether-subscription-prompt.md`
**Orchestrator:** `claude-fable-5 (xhigh)` — decision points only
**Started:** 2026-07-16 · **Prod:** https://5cb5f0620.abacusai.cloud (health ok, v0.2.0)
**Machine mirror:** `docs/delivery/phase6-gap-analysis.json` (authoritative) · **Evidence:** `uat/reports/evidence/phase6/`

Seeding rule (§4.3): gaps enter ONLY from PHASE-0 probe artifacts. Confirmed hypotheses become
gaps citing the probe artifact; refuted hypotheses are recorded REJECTED with the refuting artifact.

## Binding ADRs (do not re-litigate)

- **ADR-P6-SEEK** — Seek scraping is ToS-prohibited (`seek-tos-check.md`: VERDICT SCRAPING-PROHIBITED;
  robots.txt names `anthropic-ai`), reinforced by probe-13 (10/10 sampled Seek cards HTTP 403).
  Disable/remove the Firecrawl SeekAdapter; achieve GATE-07 volume via **Adzuna AU (licensed API)** +
  official ATS APIs (Greenhouse, Lever, Workable, Ashby) + Remotive/RemoteOK public APIs. Stale
  Seek-origin rows must not be shown as live.
- **ADR-P6-OAUTH** — Anthropic third-party subscription OAuth is prohibited (`anthropic-oauth-verification.md`:
  NOT-PUBLICLY-SUPPORTED). API-key auth only active; any OAuth code stays behind
  `AETHER_ANTHROPIC_OAUTH_ENABLED=false`, UI-disabled "coming soon". **GATE-04 = CONDITIONALLY-CLOSED**
  with the artifact as evidence — NOT awaited as a human gate.
- **ADR-TR-1** (inherited) — additive lazy idempotent DDL (`_ensure_*_tables` + `pg_advisory_xact_lock`);
  `.sql` files documentation-only; never DROP/ALTER TYPE.
- **ADR-P6-STRIPE-MOCK** — build all billing code now with MOCKED Stripe and unit tests; live
  round-trip gates (13/14/15/16/33) require human Stripe test creds → BLOCKED-ON-HUMAN; never fake
  a live invoice/webhook to close a gate.

## Gap ledger (22 active gaps)

| ID | Title | Sev | Cluster | Human-gated | Status | Key evidence |
|---|---|---|---|---|---|---|
| GAP-P6-BILL-001 | Subscription/billing architecture missing | CRIT | D | Yes (Stripe) | TRIAGED | probe-15, probe-19, inventories |
| GAP-P6-BILL-002 | No LLM spend-cap / agent-run quota | CRIT | D | No | TRIAGED | probe-15 |
| GAP-P6-PRICING-001 | No public /pricing page | HIGH | D | No | TRIAGED | inventory-fe |
| GAP-P6-ADMIN-001 | No admin panel (users/spend/health/settings) | CRIT | F | No | TRIAGED | inventories, probe-17 |
| GAP-P6-ADMIN-003 | AdminAuditLog + data export/delete missing | HIGH | F | No | TRIAGED | probe-15 |
| GAP-P6-SEC-001 | admin/admin123 rotation (post-admin-panel) | CRIT | F | Yes (env) | TRIAGED | probe-17 |
| GAP-P6-SRC-001 | Job sourcing volume (6 live jobs) | CRIT | C | No | TRIAGED | probe-07 |
| GAP-P6-SRC-002 | Seek scraper = ToS violation | CRIT | C | No | TRIAGED | seek-tos-check, inventory-be, probe-13 |
| GAP-P6-DATA-001 | Stale/unreachable Seek cards shown to users | HIGH | C | No | TRIAGED | probe-13, probe-05 |
| GAP-P6-WIRE-001 | 6 dead view-toggle controls | MED | B | No | TRIAGED | probe-06 |
| GAP-P6-AGCONF-001 | Verify all agents PUT config + billing routing (GATE-06) | MED | E | No | TRIAGED | inventory-be, probe-16 |
| GAP-P6-AUTH-OAUTH-001 | Enforce API-key-only + flag-gated OAuth (GATE-04) | HIGH | E | No | TRIAGED (COND-CLOSE) | oauth-verification, inventory-be |
| GAP-P6-MULTI-001 | Multi-Gmail verify (select_account, 2 accts) | HIGH | E | Yes (2 Gmail) | TRIAGED | inventory-be |
| GAP-P6-TAIL-001 | Resume tailoring craft (writer-audit) | HIGH | G | No | TRIAGED | inventory-be |
| GAP-P6-COV-001 | Cover letter craft (writer-audit) | HIGH | G | No | TRIAGED | inventory-be, probe-14 |
| GAP-P6-CONV-001 | Conversion estimate label+methodology+tooltip | MED | G | No | TRIAGED | inventory-fe |
| GAP-P6-MET-001 | Metric recompute delta (user-scoped verify) | MED | H | No | TRIAGED | probe-09 |
| GAP-P6-REPO-002 | 14 stale branches + 12 open PRs | MED | H | No | TRIAGED | probe-11 |
| GAP-P6-DIR-001 | Monorepo dir reorg | LOW | H | No | TRIAGED | inventories |
| GAP-P6-DOCS-001 | Docs stale + docs/subscription/ missing | MED | H | No | TRIAGED | inventory-fe |
| GAP-P6-EXEC-001 | EXECUTION-REPORT claims re-verify (8 vs 22 agents) | MED | H | No | TRIAGED | inventory-fe, probe-16 |

Full per-gap records (observed/expected/root_cause/fix_spec/tests/gates) live in the JSON mirror.

## Rejected hypotheses (probe-refuted — recorded, not fixed)

| Hypothesis | Verdict | Refuting artifact |
|---|---|---|
| H-001 LLM replay mode in prod | REJECTED | probe-03 (mode=auto) → GATE-02 PASS |
| H-020 no auth rate limiting | REJECTED | probe-18 (429 after 5) → GATE-32 PASS |
| H-014 non-prod code in apps/ | REJECTED | probe-12 (0 real hits) |
| PROBE-14 PDF defects | REJECTED | probe-14 (PDFs generate; craft verified in G) |
| H-002 provider-scoped credential PK | REJECTED | inventory-be (per-user UserProviderCredential) |
| H-003/H-004 AgentConfig cols / no PUT | REJECTED | probe-15 + inventory-be (cols + PUT exist) → residual = GATE-06 verify |
| H-021 admin/admin123 has admin privileges | PARTIALLY-REJECTED | probe-17 (no privilege system yet; rotation retained as SEC-001) |

## Cluster sequencing (§5.1)

- **A** authenticity/env — mostly REJECTED by probes; nothing to build (AUTH replay rejected, data-authenticity handled under Cluster C DATA-001).
- **B** wiring — GAP-P6-WIRE-001 (6 dead controls).
- **C** sourcing — SRC-002 (compliance, FIRST) → SRC-001 (volume, compliant sources) → DATA-001 (liveness). ADR-P6-SEEK binding.
- **D** billing — BILL-001, BILL-002, PRICING-001. Build with mocked Stripe; **BLOCKED-ON-HUMAN** for live verify.
- **E** auth modes + agent config — AGCONF-001, AUTH-OAUTH-001 (COND-CLOSE), MULTI-001 (Gmail human-gated).
- **F** admin panel — ADMIN-001, ADMIN-003, SEC-001. Depends on D schema.
- **G** tailoring/cover quality — TAIL-001, COV-001, CONV-001 (writer-audit verify).
- **H** (LAST) metrics/docs/repo — MET-001, REPO-002, DIR-001, DOCS-001, EXEC-001; EXECUTION-REPORT.md move here.

## Gate status snapshot

PASS now: 01, 02, 03, 23(likely), 27, 32, 31(now). FAIL/OPEN to fix: 07, 08, 06, 09, 10, 11, 17, 18,
19, 20, 21, 22, 28, 29, 30, 34, 04(cond), 12(confirm). BLOCKED-ON-HUMAN: 05, 13, 14, 15, 16, 33 (Stripe + Gmail).
Full per-gate detail in the JSON mirror `gate_status`.
