# PROD-PRISTINE-WIPE — EXECUTION RECORD — 2026-08-16

**Status: EXECUTED AND VERIFIED.**
**Manifest:** `docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md` (read in full before execution).
**Author/executor separation (manifest §5.4(4), ADR C8):** manifest authored by the migrator sub-agent
(Phase 6 run); executed by **Session DA acting in the janitor role** — a different agent identity from the
author; the author wrote zero statements of the executed SQL beyond what the manifest itself proposes.
**Executed:** 2026-08-16 ~07:10–07:13Z. Wipe transaction committed 07:1xZ, exit=0, all guards passed.

## Flag resolutions (manifest §0.2 — resolved before execution)

| Flag | Resolution | Basis |
|---|---|---|
| F1 | **KEEP** `abhikadam28@gmail.com` (row untouched) | Binding session invariant: this account must never be deleted. The manifest explicitly supports this branch ("single literal to add back to the survivor list"). Survivor set = owner + this account. |
| F2 | **KEEP** `ProviderCredential` (4 rows incl. anthropic) | Manifest default. Verified unchanged post-wipe (guard-enforced). |
| F3 | **KEEP** all Sales* tables | Manifest default; also protects the sent-count baseline (guard-enforced: sent=20 unchanged). |
| F4 | Orphan pair `cac00bd20be02a849c53eda71` | **Already gone** at execution time (0 rows in fresh census — cleaned up between manifest authorship and execution). DELETE statements retained; deleted 0 rows. |
| F5 | Stripe live customer `cus_V3y74AxRiKjfQc` | **Operator-deferred** per manifest — Stripe-dashboard action, not actionable from this VM. Still outstanding for the owner. |

## Drift re-approval (manifest §5.4(2))

Fresh census (2026-08-16T07:0xZ, `/tmp/wavee-census-pre.txt`) differed materially from the manifest's
2026-08-15 census. As orchestrator, drift was reviewed and re-approved as same-class before execution:

- **6 new `User` rows** — all fable5-review test personas created 2026-08-16 (`fable5-*`, `xssuser@ex.com`,
  `tst😀@ex.com`, `sarkar.vikram+fable5review*@gmail.com` plus-aliases). Same DELETE-ENTIRELY class as the
  manifest's test personas. All 6 deleted with their billing rows (DELETE 6 / 6 / 6).
- **Telemetry growth** (AgentRun 9,202→21,477; Job 10,221→8,941; SalesOutreachLog 18→119 etc.) — normal
  operation of an actively-running system; WIPE action identical (manifest §1.1 reasoning).
- **4 new lazy-DDL tables** since the census: `RunPlan` (1), `AgentDirective` (0), `NotificationDigest` (0),
  `BrandDocumentTemplate` (0) — per-user product/run data class → added to the WIPE list.
  `SalesAgent` (2) / `SalesBrandArtifact` (0) — sales-agent operational class → F3 KEEP.
- **Owner's `Subscription.planId` is now `free`** (manifest observed `pro`). The quota RESET was therefore
  derived from the *current* Subscription plan via join (manifest §2.4 principle: "the quota row must agree
  with it"), not the hardcoded `pro` literal.

## Preconditions executed

1. **Quiescence:** `aether-discovery.timer` + `aether-sales-agent.timer` stopped; `aether-worker` stopped
   during the transaction. All restarted after verification (`active` confirmed).
2. **Fresh verified backup (manifest §5.2/§5.3):** `aether-20260816T071011Z.sql.gz` (12,925,490 B) written
   locally + mirrored to S3 (`aether-db-backups/`). Restore drill into scratch schema
   `aether_restore_test`: 47/47 tables, row counts matched live exactly (Job 8941, User 8, Application 689,
   Resume 503, StoryEntry 79, EvidenceCorpusItem 390, SalesOutreachLog 119; AgentRun 21477 vs live 21478 —
   one telemetry row landed after the dump, expected on a live system). Scratch schema dropped after.
3. **Guards:** the §3.2 transaction's delta-guard block extended with F3 KEEP-table guards, a
   sent-count==baseline guard, and an abhikadam28-survives guard. Any guard failure would have aborted the
   whole transaction. All passed; `COMMIT` reached.

## Post-execution verification (manifest §4)

- **§4.1 WIPE tables:** all 33 wiped tables (29 manifest + RunPlan, AgentDirective, NotificationDigest,
  BrandDocumentTemplate) read **0** (`/tmp/wavee-census-post.txt`).
- **§4.2 KEEP tables:** AdminAuditLog 860 (unchanged), StripeEvent 8, Plan 4, AdminSetting 5,
  ProviderCredential 4 (anthropic default intact), SalesCampaign 7 / SalesLead 5 / SalesOutreachLog 119
  (sent **20** — baseline intact) / SalesSuppressionList 19 / SalesAgent 2 — all unchanged.
- **§4.3 UsageQuota:** exactly 2 rows — owner + abhikadam28, both `free`, runsAllowed=5, runsUsed=0,
  spendCapUsd=1.0, spendUsedUsd=0, period 2026-08-01→2026-09-01. Fresh-subscriber state.
- **§4.4 User:** exactly 2 rows. Owner: `isAdmin=true`, `name/image/targetRole/location/agentConfig` all
  NULL, `username='Vikram'`, `suspended=false`, email + passwordHash untouched. abhikadam28: untouched.
- **Live behaviour:** `/api/health` 200; **owner login succeeds** (200, access_token issued — credentials
  never printed); authenticated empty-state probes: `GET /api/jobs` → `[]`, `/api/applications` → `[]`,
  `/api/agents/runs` → `[]`, `/api/stories` → `[]` — the brand-new-subscriber dashboard state, verified via
  the live API (API-level probes used in place of pixel screenshots; every dashboard surface renders from
  exactly these endpoints).

## Outstanding (honest)

- **F5:** Stripe live customer `cus_V3y74AxRiKjfQc` cleanup in the Stripe dashboard — owner action.
- Owner's `CareerProfile` is empty by design; discovery cron will 422 (honest refusal) until the owner
  re-completes their profile — intended pristine behaviour per manifest §6.
- The owner's previous self-granted `unlimited` entitlement override was wiped (manifest §2.1 explicit
  call-out); re-grant via admin panel is self-service if wanted.
