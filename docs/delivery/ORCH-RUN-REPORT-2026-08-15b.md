# ORCH-EXEC Run Report (b) — Waves C/D/E close-out + final acceptance sweep (2026-08-15 → 16)

Session DA continuation run, branch `main` (direct-to-main per session convention; Session CLI
active concurrently). Per §11 convention: failures and unproven items FIRST, then completed work
with proof, then the ledger state. Companion docs: `PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md`,
`PROD-PRISTINE-WIPE-EXECUTION-2026-08-16.md`, `ORCH-RUN-REPORT-2026-08-15.md` (prior run).
Prod of record: `https://5cb5f0620.abacusai.cloud`, BUILD_ID **`DoT-qM7YAckJe1JoWnNGu`**, version 0.2.0.

## 1. FAILURES / UNPROVEN / OPEN — read this first

### 1a. Global gates G1–G5 — status this session

<!-- BATTERY-BLOCK-START -->
**Full regression battery: RUNNING at time of writing (not yet complete).** An authoritative,
env-isolated full battery was launched detached (`scripts/run-tests.sh -q -p no:cacheprovider`,
status `/home/ubuntu/fable5-review/logs/battery-final-status.log`, output `battery-pytest-full.log`)
covering the full pytest DB suite (**4,316 tests collected**) plus the already-green tsc and vitest
gates from the prior battery pass (`battery-status.log`: tsc exit=0, vitest exit=0). Until the
pytest run reports a clean `PYEXIT=0` with a triaged failure list, **G1, G2, G3 remain UNFLIPPED**
— honest per the zero-failures directive.
<!-- BATTERY-BLOCK-END -->

- **G4 (PROD verify loop clean):** supported by this session's prod evidence — 7 admin surfaces
  captured at 1440×900 with **0 browser console errors** (`final-closeout/r1.1-admin-desktop/`),
  all admin routes 200, health 200, honest DB-sourced data. Flipped only if the four zeros hold
  end-to-end after the battery (paired with G3).
- **G5 (adversarial review clean):** the Fable 5 adversarial review completed with verdict
  **FAIL (narrow)** / READY-TO-ONBOARD **NO**, driven solely by the Critical finding **INV-C-001**
  (secret references under `refs/deepagent/*` + prod secret rotation), which is **BLOCKED-ON-OWNER**.
  G5 therefore **CANNOT be honestly flipped this session** — the four zeros cannot be re-proven
  while a Critical adversarial finding is open and owner-gated. Left UNFLIPPED with this reason.

### 1b. BLOCKED-ON-OWNER (documented only — NOT attempted, per invariants)

1. **Gmail sending-mailbox authorisation.** Live gmail import/send path returns 409 pending
   consent; only the owner can complete OAuth consent for the sending mailbox. No workaround
   attempted. Sending stays disarmed (sent-count invariant held at 20).
2. **INV-C-001 (Critical) — secret-reference purge + prod secret rotation.** Requires purging
   `refs/deepagent/*` history references and rotating the exposed production secrets. Owner-only
   (repo history + secret store). This is the sole reason the adversarial verdict is FAIL/NO and
   the sole blocker on G5. Also tracked: SEC-SLIP-DA-01.
3. **F5 — Stripe live-customer cleanup.** Live Stripe customer `cus_V3y74AxRiKjfQc` must be
   removed from the Stripe dashboard (operator action, deferred per pristine-wipe manifest).

### 1c. Other open/uncertain items

- **CI does not run the DB pytest suite.** `DATABASE_URL_TEST` secret is unset in the repo, so CI
  annotates "DB test suite skipped". Local env-isolated `scripts/run-tests.sh` is the DB-test
  evidence of record — honest, but a weaker gate than CI-enforced.
- **Concurrent-session note:** the current full-battery run's first ~13% overlapped with this
  session's live R2 prod probes + admin screenshot capture; any transient failures in that early
  window are re-verified in isolation before attribution (see §1a). Session CLI's 449ee966 remains
  on origin but undeployed (CLI's scope to ship).

## 2. Completed this session (with proof)

### R1.1 — admin metric/dashboard surfaces render only real, honest data ✅ (flipped)
7 admin surfaces captured at 1440×900 (fullPage), **0 console errors**
(`final-closeout/r1.1-admin-desktop/console-errors.txt`): overview, health, subscriptions, spend,
audit-log, billing, sales-agent. Verified honest rendering — real DB values (MRR A$0.00, paid 0,
real signup series, real audit trail showing this session's own admin actions), and explicit
"Not enough data yet" / "Not measured" states where a metric is genuinely unavailable (no
fabricated zeros presented as truth). Capture script `apps/web/e2e/r1_1-admin-screenshots.mjs`.

### R1.3 — design-system consistency / beauty-sweep verdict ✅ (flipped)
Verdict artifact `final-closeout/R1.3-beauty-sweep-verdict.md` (PASS). Brand fonts live in prod
(built CSS references AB-Marquee + AB-Sans; `/fonts/ab/AB-Marquee-Bold.ttf` and
`AB-Sans-Regular.ttf` both serve `200 font/ttf`). DS consistency (typography, single dark surface
family, one amber accent, danger reserved to single red, honesty affordances) confirmed on the
fresh admin captures; 0 visual regression corroborated by the prior independent S-UI judge record
(`s-ui/beauty1/after/judge-report.json` consoleErrors:[]; `s-ui/b3/judge/B3-JUDGE-REPORT.md`
per-page scores 8/8/9).

### R2.1–R2.5 — inherited admin flows independently re-verified in prod ✅ (all flipped, implementer ≠ verifier)
All exercised live against prod with the owner token; every mutation reversible and restored;
audit deltas confirmed. Evidence under `final-closeout/`:
- **R2.1 / R2.3 / R2.5** (`R2-admin-superuser-verify.log`): full synthetic-user lifecycle —
  create → password reset (`{newPassword}`) → suspend/unsuspend → entitlement override/clear →
  soft-delete (`{confirmEmail}`, hidden from default list) → restore → hard-purge
  (`{confirmEmail}`), all 200; audit rows for each action. **Synthetic user fully hard-purged
  (DB residue = 0); no residual state.**
- **R2.2** (`R2.2-pricing-verify.log`): catalog plan-pricing reversible round-trip on `starter`
  (annual 179→180→179, all 200, restored); DELETE subscription-record route runs (200 idempotent
  no-op); per-user override honest (entitlement 200; subscription/price 409 when no live sub).
- **R2.4** (`R2.4-template-editing-verify.log`): brand template/footer editing — PUT
  `/api/admin/sales-agent/brand/templates/auto_reply` (footer override → 200, read-back present,
  audit-logged `brand_template.updated`, restored).

### Prod health (independent snapshot)
`final-closeout/prod-health-20260816T090416Z.md`: /api/health 200 `{"status":"ok","version":"0.2.0"}`;
services aether-api/web/worker + `aether-sales-agent.timer` all ACTIVE; BUILD_ID
`DoT-qM7YAckJe1JoWnNGu`; **sent-count invariant HOLDS = 20** (SalesOutreachLog outcome='sent'=20;
zero new real sends this session).

### Prior waves (from earlier this session, proof in ledger + companion docs)
Wave C (R3.1–R3.4 promo autonomy), Wave D (R4 LinkedIn manual-file import, zero automation — 24
passed, CI green 547cd842), Wave E (R5 pristine production purge — executed 2026-08-16 ~07:10Z,
backup verified by scratch-schema restore, wipe COMMIT with in-transaction guards, sent==20
preserved). Deploy of record a0fdc4b0 → BUILD_ID `DoT-qM7YAckJe1JoWnNGu`.

## 3. Ledger state (`/home/ubuntu/aether-market-performance.md`)

<!-- LEDGER-BLOCK-START -->
Flipped [x] cumulatively: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1–R3.4, R4.1,
R4.2, R5.1–R5.3, G6, G7 — **20 of 25 boxes**. Remaining [ ]: **G1, G2, G3, G4, G5** — each named
in §1a with the exact reason (G1–G3 pending the in-flight full battery; G4 paired with G3; G5
blocked on the owner-gated Critical INV-C-001). Per the standing zero-failures/zero-warnings
directive, unproven boxes stay unflipped rather than being claimed.
<!-- LEDGER-BLOCK-END -->
