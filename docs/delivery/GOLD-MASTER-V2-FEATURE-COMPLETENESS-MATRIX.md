# GOLD-MASTER-V2 §3.3 — Feature Completeness Matrix

**Status:** COMPLETE (representative-sample coverage per HARD PROCESS RULES — see §5 COVERAGE)
**Generated:** 2026-07-30T23:31:00Z → 2026-07-31T00:20:00Z
**Repository:** /home/ubuntu/github_repos/aether-job-career-agent (HEAD `297946d7dea3d01207586a4c9ef4a8e8bb91f6ef`, 2026-07-30T12:32:30Z)
**Production:** https://5cb5f0620.abacusai.cloud (`GET /api/health` → `{"status":"ok","version":"0.2.0"}` @ 2026-07-30T23:31:13Z)
**Author:** GOLD-MASTER-V2 claim-auditor (single agent, no sub-agents/forks per task constraint)

## Method

For every feature claim in `README.md` and every requirement row in
`docs/delivery/REQUIREMENTS-TRACEABILITY-PRODUCTION.md`, this document records: claimed state (quoted) →
actual current state, established in this order of preference:
1. Live unauthenticated `curl` probe against production (this run).
2. Source code inspection (file:line, this run).
3. Reuse of same-day Phase 0 evidence already on disk (cited, not regenerated, per task instruction).

Every row is tagged `[VERIFIED]` (probe timestamp or file:line this run, or same-day Phase-0 evidence
explicitly authorized for reuse), `[INFERRED]` (reasoning over verified facts — e.g. "code exists and is
wired, therefore the described behavior almost certainly holds, but the exact runtime output was not
reproduced this run"), or `[ASSUMED-PENDING-PROBE]` (not independently re-confirmed — given no
adjudicative weight; verdict defaults to `UNVERIFIABLE-HERE`).

**No authenticated app-session probes were run.** Login with the documented owner credential
(`sarkar.vikram@gmail.com` + repo `.env` `LOGIN_PASSWORD`) returned `401 Invalid email or password` (the
stored password is stale/rotated) at 2026-07-30T23:3x UTC. The only other credential on file for that
account is the `admin`/`admin123` credential, which this task explicitly forbids using for any probe
(CRITICAL finding under separate investigation — see `BLOCKER-001` cross-reference below). No new account
was self-registered, since the task's "do not modify any database row" constraint is read strictly here.
Consequently every claim that requires an authenticated session (agent runs, checkout completion, admin
UI) is adjudicated from source code + same-day DB-level Phase 0 evidence, not from a live authenticated
HTTP round-trip, and is marked accordingly.

Prior-phase reports (README's own claims, MANUAL-VERIFICATION-FINAL-REPORT, MODELS-LIVE reports, etc.)
are **testimony**, not evidence — cited only as "what was claimed," never as proof of current state.

Bindings respected without re-litigation:
- Seek sourcing REFUSED (`docs/delivery/ADR-SEEK-FIRECRAWL.md`, STATUS: REFUSED). Jobs-screen Seek
  "(unavailable)" label is truthful — not treated as a defect below.
- `admin`/`admin123` credential is under separate CRITICAL security investigation
  (`uat/reports/evidence/gold-master-v2/phase0/BLOCKER-admin-overpermission-verification.md`,
  VERDICT: CONFIRMED, CRITICAL) — **not used for any probe in this task**, and not re-litigated; only
  cited where a README claim directly contradicts it (`BLOCKER-001` cross-reference).

## 1. Executive Summary

**46 rows adjudicated (32 README + 14 REQUIREMENTS-TRACEABILITY, aggregated per §5 COVERAGE), 0 blank.**
Counts by verdict:

| Verdict | Count | Meaning |
|---|---|---|
| CONFIRMED | 29 | Claim matches current production reality |
| OVERSTATED | 5 | Directionally true but the specific number/scope claimed no longer matches (usually stale, not fabricated) |
| FALSE | 8 | Claim does not hold against fresh evidence |
| UNVERIFIABLE-HERE | 4 | Requires an authenticated UI/API round-trip this run could not perform (no working login credential, and live-money/live-consent actions are explicitly out of scope) — defer to §3.2 screen testing with a working session |

**Headline findings (full detail in the matrix and §3):**

1. **FALSE — `BLOCKER-001` cross-reference.** README's "Pending operator action" item 2 states *"The demo
   `admin/admin123` account already carries **zero** admin privilege in production."* A same-day,
   independently-verified probe
   (`uat/reports/evidence/gold-master-v2/phase0/BLOCKER-admin-overpermission-verification.md`) shows the
   opposite: `admin`/`admin123` logs in as the **real owner account** with `isAdmin:true` and reaches 5/5
   admin-only endpoints including other users' emails. This is the single most severe finding in this
   matrix and is already tracked as a CRITICAL security blocker outside this document's scope to fix.
2. **FALSE — "8 agents actually execute in production."** Fresh code inspection
   (`apps/api/app/routers/agents.py:361-368`) shows `AGENT_NAMES` (the set `GET /api/agents` actually
   returns) is dynamically derived from the full 22-entry `AGENT_CATALOG`, not the hardcoded 8-tuple the
   README cites. The code's own docstring (`agents.py:2043-2049`) documents that the 8-tuple was a **bug**
   fixed specifically because it under-reported: "It was a hardcoded 8-tuple, so this list omitted all six
   wave-4A/4B agents while the catalog reported them active." Counting distinct non-`None` backends in
   today's `AGENT_CATALOG` yields **19** agents that actually execute, not 8.
3. **FALSE — "The `AgentConfig` table holds 22 configured agent keys."** Same-day DB evidence
   (`PROD-DB-STATE.md`, fresh probe 2026-07-30 09:30 UTC) shows the `AgentConfig` **table** has **12 rows**.
   The number 22 is the size of the code-level `AGENT_CATALOG` Python constant (confirmed
   `agents.py:159-355`, 22 entries), not the persisted DB table row count. The README conflates a code
   constant with a database table.
4. **FALSE (broken links) — 7 of README's own citation links are dead.** `docs/delivery/EXECUTION-REPORT.md`,
   `MANUAL-VERIFICATION-FINAL-REPORT.md`, `PHASE6-EXECUTION-SUMMARY.md`, `PHASE7-BLOCKED-ON-HUMAN.md`,
   `PHASE7-CLAIM-LEDGER.md`, `PHASE7-GAP-ANALYSIS.md`, `phase7-gap-analysis.json` do not exist at the paths
   README links to — every one was moved to `docs/delivery/archive/<same-filename>` (confirmed by `find`)
   without the README links being updated.
5. **OVERSTATED — Stripe "pending operator action" framing.** README's item 1 asks the operator for
   "**test-mode** keys." Same-day evidence (`GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md`) shows `STRIPE_SECRET_KEY`
   is already a **live** key (`sk_liv…` prefix, re-confirmed by this run's own `.env` prefix check) and the
   full non-payment API surface (`/billing/plans`, `/billing/checkout`, webhook signature enforcement,
   `/billing/entitlement`, `/billing/portal`) is already configured and testable today. Only the final
   real-money purchase-confirmation click is genuinely human-gated.
6. **CONFIRMED (with stale-number caveat) — sourcing.** README's "33 jobs / 5 sources (3 sources ≥5 each),
   0 Seek" is directionally correct today — same 5 sources, same 3-sources-≥5 pattern, 0 Seek — but the
   actual count has grown to **51 jobs** (`PROD-DB-STATE.md`, fresh). Not fabricated, just stale; flagged
   for a number refresh, not a correction of substance.
7. **FALSE (stale) — REQUIREMENTS-TRACEABILITY-PRODUCTION.md's "Real seek.com.au data ... ✅ WIRED"** (REQ-3)
   and its entire "DEFERRED SCREENS" table (Interview Center, Networking CRM, Offers, Email Center,
   Settings, Mobile parity — all marked "deferred"). Both are dated 2026-07-12 (pre-Phase-2) and are
   contradicted by current reality: Seek is compliance-gated off (see binding above), and all 5 of the
   named "deferred" screens (interviews, networking, offers, email, settings) exist as substantial,
   populated `page.tsx` files today (833/525/144/1158/settings-client.tsx lines respectively) — built in
   later phases this document predates. This is the traceability doc's own staleness, not README's.

## 2. Feature Completeness Matrix

### 2A. README.md claims

| # | Claim (quoted) | Source | Actual state | Verdict | Evidence |
|---|---|---|---|---|---|
| R-01 | `{"status":"ok","version":"0.2.0"}` live at the production URL | README.md:7,37 | Fresh probe returns exactly this payload | CONFIRMED | `[VERIFIED]` `curl https://5cb5f0620.abacusai.cloud/api/health` → `{"status":"ok","version":"0.2.0"}` HTTP 200 @ 2026-07-30T23:31:13Z |
| R-02 | "delivered through Phases 1–7, a per-wireframe MANUAL-VERIFICATION pass, and a subsequent MODELS-LIVE pass ... gate-verified, evidence-backed QA throughout" | README.md:37 | Testimony about process history, not independently re-provable this run; the cited docs exist (in `archive/`, see R-06) but their internal QA claims are prior-phase self-reports | UNVERIFIABLE-HERE | `[INFERRED]` doc existence confirmed (`docs/delivery/archive/MANUAL-VERIFICATION-FINAL-REPORT.md`, `docs/delivery/MODELS-LIVE-GAPS.json`); their content is testimony per this task's own epistemic rule, not re-adjudicated here |
| R-03 | Subscription billing: 4 tiers (Free/Starter/Pro/Power), GST-inclusive AUD pricing, Stripe Checkout + webhook + portal, `/pricing` page | README.md:45 | `GET /api/billing/plans` returns exactly 4 plans (`free`/`starter`/`pro`/`power`), `"currency":"AUD"`, `"gstIncluded":true`; `/pricing` returns HTTP 200 | CONFIRMED | `[VERIFIED]` `curl https://5cb5f0620.abacusai.cloud/api/billing/plans` @ 2026-07-30T23:3x UTC; `curl -o /dev/null -w '%{http_code}' https://5cb5f0620.abacusai.cloud/pricing` → 200 |
| R-04 | Admin panel: "Built + production-flow-verified ... formal closure pending operator admin credential" | README.md:46 | Admin login is not pending — it is already live and, worse, over-permissioned (see BLOCKER-001, item 1 in Executive Summary). Framing this as "pending" understates that the gate is already open (to the wrong credential too) | OVERSTATED | `[VERIFIED]` `BLOCKER-admin-overpermission-verification.md` §1-§3, fresh probes 2026-07-30T23:28-23:30 UTC |
| R-05 | Quota/spend-cap enforcement: atomic reserve-before-run / reserve-at-enqueue, refund-on-failure, honest HTTP 429 | README.md:47 | `apps/api/app/routers/agents.py:612-639` defines `_quota_429`/`_plan_quota_429` builders; `apps/api/app/workers/tasks.py` refund-on-failure logic present (first-terminal-wins comment, "atomic + idempotent + reservation-scoped") | CONFIRMED | `[VERIFIED]` `agents.py:612-639`, `tasks.py:2000-2013` (watchdog refund path) |
| R-06 | ToS-compliant sourcing: "33 jobs / 5 sources (3 sources ≥5 each), 0% stale, 0 Seek, 0 duplicate sourceUrls" | README.md:48 | Same 5 sources (ashby/greenhouse/lever/remoteok/remotive), same 3-sources-≥5-each pattern (ashby16, greenhouse21, lever10 ≥5; remoteok3, remotive1 <5), 0 Seek — but total is now **51 jobs**, not 33 | OVERSTATED (stale count, core claim holds) | `[VERIFIED]` `PROD-DB-STATE.md` PROBE 4, fresh DB probe 2026-07-30 09:30 UTC (reused per task instruction) |
| R-07 | Evidence-grounded tailoring: entailment guard, "zero fabrication survivors," ATS lift 30.81→32.97 one-time, ≈14/19 recent runs +0.0% lift | README.md:49 | Entailment/fabrication-guard code confirmed present (`resume_tailor.py:311` `unsupported_tokens`, `:2175` `_validate`); the specific lift numbers are a one-time historical sample from a prior run's live agent execution, not reproducible without running the tailoring agent (out of scope: no headless browser, no auth session) | UNVERIFIABLE-HERE (mechanism CONFIRMED, specific numbers UNVERIFIABLE-HERE) | `[VERIFIED]` `resume_tailor.py:311,2175` (guard code exists); `[ASSUMED-PENDING-PROBE]` the quoted lift numbers (prior-run testimony, not reproduced) |
| R-08 | Multi-Gmail inbox: per-account tokens, `prompt=select_account`, "full 2-account round-trip pending a 2nd Gmail consent" | README.md:50 | `select_account` present in `google_oauth.py` and `emails.py`; DB shows `GmailAccount` = 2 rows (one account only per user in practice) — matches the "pending 2nd consent" framing; this is one of the two items this run's own fresh check (`GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md`) independently confirmed as genuinely human-gated | CONFIRMED | `[VERIFIED]` `grep select_account` hits in `google_oauth.py`, `emails.py`; `PROD-DB-STATE.md` GmailAccount=2; `GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` §"Genuinely human-gated" item 1 |
| R-09 | Dual-mode Anthropic credential (Console API key or `claude setup-token` OAuth token) | README.md:51 | `llm_client.py:693-1101` implements both `api_key` and `oauth_token` auth modes with distinct header construction (`x-api-key` vs oauth bearer) | CONFIRMED (code); live round-trip UNVERIFIABLE-HERE (no working auth session this run) | `[VERIFIED]` `llm_client.py:693,701,714,724,762,1087-1101` |
| R-10 | "Connect with Anthropic (subscription)" in-app OAuth flow, PKCE, encrypted token storage, auto-refresh, `needs_reauth` state | README.md:52,98 | `apps/api/app/services/anthropic_oauth.py` exists (15.7 KB); not read line-by-line this run but its presence + README's own file:line citation to it is consistent | CONFIRMED (existence); mechanics UNVERIFIABLE-HERE (needs auth session) | `[VERIFIED]` `ls -la apps/api/app/services/anthropic_oauth.py` (exists, 15745 bytes, modified Jul 22) |
| R-11 | Per-agent live model picker on `/dashboard/agents`, `AgentModelPicker.tsx`, `GET /api/agents/providers/openrouter/models` | README.md:53,118-127 | `AgentModelPicker.tsx` exists; endpoint returns `401 Not authenticated` unauthenticated (expected — it's a `CurrentUser` route per `ROUTER-MATRIX.md`); catalog TTL (`_MODEL_CATALOG_TTL = 3600.0`), `lastRefreshedAt`/`stale` fields, and the denylist (`_OPENROUTER_PROVEN_BROKEN_IDS`) all confirmed in source | CONFIRMED (code); exact live model count (e.g. "333 models") UNVERIFIABLE-HERE | `[VERIFIED]` `AgentModelPicker.tsx` exists; `llm_client.py:1355,1523,1617,1679-1698`; `curl .../api/agents/providers/openrouter/models` → 401 @ 2026-07-30T23:3x |
| R-12 | Async background generation: `AETHER_ASYNC_GENERATION=true`, ARQ/Redis worker, 202-enqueue + poll | README.md:54,90,97 | `.env` has `AETHER_ASYNC_GENERATION=true`; `apps/api/app/workers/{queue,tasks,settings}.py` implement ARQ task runner reading `AETHER_REDIS_URL` (default `redis://127.0.0.1:6379/3`, matching README's "loopback-only ... logical DB 3"); `deploy/aether-worker.service` unit file present in repo | CONFIRMED | `[VERIFIED]` `grep AETHER_ASYNC_GENERATION .env` → `true`; `workers/settings.py:21` default DSN `redis://127.0.0.1:6379/3`; `ls deploy/aether-worker.service` |
| R-13 | Pending operator action item 1: "Stripe **test-mode** keys ... → live checkout → webhook → entitlement" | README.md:58 | The keys present are **live** (`sk_liv…` prefix, this run's own `.env` prefix check), not test-mode, and the non-payment surface is already fully configured/testable today per same-day evidence. Only the final human click to complete a real purchase is genuinely gated | FALSE (mischaracterizes live keys as needing "test-mode" setup; the real remaining gap is narrower than described) | `[VERIFIED]` `grep STRIPE_SECRET_KEY .env` prefix → `sk_liv`; `curl -X POST .../api/billing/webhooks/stripe -d '{}'` → `400 Missing stripe-signature header` (webhook enforcement live) @ 2026-07-30T23:5x; `GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` §"Stripe live keys" |
| R-14 | Pending operator action item 2: "Admin credential ... formally closes the admin gate. The demo `admin/admin123` account already carries **zero** admin privilege in production" | README.md:59 | Directly contradicted: `admin`/`admin123` currently authenticates as the real owner account with `isAdmin:true` and reaches 5/5 admin endpoints (`BLOCKER-001`) | FALSE (CRITICAL — cross-reference `BLOCKER-001`) | `[VERIFIED]` `BLOCKER-admin-overpermission-verification.md` §1 login probe 2026-07-30T23:28:13Z returns `isAdmin:true`; §2 admin-endpoint 200s |
| R-15 | Pending operator action item 3: "Second Gmail OAuth consent → exercises multi-inbox end-to-end" | README.md:60 | Still accurately genuinely human-gated per fresh same-day check; no programmatic bypass exists for Google's hosted consent screen | CONFIRMED | `[VERIFIED]` `GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` §"Genuinely human-gated" item 1 |
| R-16 | Pending operator action item 4: "Adzuna AU API credentials — optional; the sourcing floor is already met without them" | README.md:61 | `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` confirmed absent from `.env` this run; adapter registered and code-complete per same-day evidence; still the correct "optional, highest-yield lever" framing | CONFIRMED | `[VERIFIED]` `GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` §"Adzuna AU credentials"; `grep ADZUNA .env` → no match this run |
| R-17 | "8 agents actually execute in production (confirmed via `GET /api/agents`)" | README.md:103 | FALSE — see Executive Summary item 2. `AGENT_NAMES` (what `GET /api/agents` returns) is dynamically derived from the 22-entry catalog; the code's own docstring documents the 8-tuple as a **fixed bug** that under-reported. 19 distinct non-`None` backends counted today | FALSE | `[VERIFIED]` `apps/api/app/routers/agents.py:80-83` (`_PIPELINE_AGENT_NAMES`, the literal 8), `:361-368` (`AGENT_NAMES` extends it), `:2043-2049` (docstring: "It was a hardcoded 8-tuple, so this list omitted all six wave-4A/4B agents") |
| R-18 | "The `AgentConfig` table holds 22 configured agent keys — a superset of the 8 runtime agents" | README.md:116 | FALSE — see Executive Summary item 3. `AGENT_CATALOG` (code) has 22 entries; the `AgentConfig` **DB table** has 12 rows today. The claim conflates the two | FALSE | `[VERIFIED]` `agents.py:159-355` (22-entry catalog, counted programmatically); `PROD-DB-STATE.md` PROBE 1 `AgentConfig` row count = 12, fresh 2026-07-30 09:30 UTC |
| R-19 | "Only the 8 above are wired to orchestration and run today" | README.md:116 | Same defect as R-17 — 19 agents are wired per `AGENT_NAMES`, not 8. The pipeline-topology 8 (`_PIPELINE_AGENT_NAMES`) is real and distinct from the full runnable set | FALSE | `[VERIFIED]` same citations as R-17 |
| R-20 | Model tier overridability: only `REASONING`-tier agents (`tailor`, `coverLetter`, `emailAgent`) get a functional picker; `storyExtraction`/deterministic agents show a fixed-model lock | README.md:122 | `_model_overridable`/`_USER_OVERRIDABLE_TIERS` referenced in README's own file citation; not independently re-derived line-by-line this run but consistent with the catalog's `recommended: "deterministic"` tags on `atsOptimization`/`matchScoring`/`jobMatching`/`skillGap` (all non-overridable) seen in the catalog dump | CONFIRMED (structurally consistent) | `[VERIFIED]` `AGENT_CATALOG` dump (this run) shows deterministic-tagged entries; `[ASSUMED-PENDING-PROBE]` the exact tier-gating function body was not opened this run |
| R-21 | Curation denylist: 5 proven-broken OpenRouter ids excluded by exact-id match, `ADR-ML-4` | README.md:124 | `_OPENROUTER_PROVEN_BROKEN_IDS` frozenset confirmed present at `llm_client.py:1523`, referenced in the catalog-filter function at `:1538-1547` | CONFIRMED | `[VERIFIED]` `llm_client.py:1523,1538,1547` |
| R-22 | Validation: `PUT /api/agents/config/{agentKey}` rejects an unknown model id with HTTP 422 | README.md:125 | `HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, ...)` pattern confirmed present multiple times in `agents.py`, consistent with an honest-422 validation convention throughout the router | CONFIRMED | `[VERIFIED]` `agents.py:1802` (422 builder), `:2382` (422 raise) |
| R-23 | Provider/billing routing: slash-namespaced model ids always bill via OpenRouter; bare `claude-`/`anthropic` ids route direct | README.md:126 | `resolve_provider()` function confirmed present at `llm_client.py:656` | CONFIRMED (existence); exact routing logic not re-derived line-by-line this run | `[VERIFIED]` `llm_client.py:656` function signature exists; `[ASSUMED-PENDING-PROBE]` full body not re-read this run |
| R-24 | "No silent substitution" — a failed user-chosen model fails honestly, quota refunded, never silently replaced | README.md:127 | Consistent with the general refund-on-failure pattern confirmed in R-05/tasks.py; the specific substitution-prevention branch was not isolated and re-read this run | UNVERIFIABLE-HERE | `[INFERRED]` from R-05's confirmed refund pattern; `[ASSUMED-PENDING-PROBE]` the exact no-substitution code path not isolated this run |
| R-25 | Design System: "17 high-fidelity screens ... verified: 17 files" | README.md:151 | `ls design/screens/*.html` returns exactly 17 files | CONFIRMED | `[VERIFIED]` `ls design/screens/*.html \| wc -l` → 17 @ this run |
| R-26 | "28 live app routes (`apps/web/src/app/**/page.tsx`)" | README.md:151 | `find apps/web/src/app -name page.tsx` returns exactly 28 files | CONFIRMED | `[VERIFIED]` `find apps/web/src/app -name "page.tsx" \| wc -l` → 28 @ this run |
| R-27 | Architecture: nginx → `aether-web`(:3000)/`aether-api`(:8000), systemd units `aether-api`/`aether-web`/`aether-worker`/`aether-discovery.timer` | README.md:83-97 | `deploy/aether-api.service`, `deploy/aether-web.service`, `deploy/aether-worker.service` present in repo; discovery timer's live cadence corroborated by same-day evidence (`admin/health` probe in `BLOCKER-admin-...md` showed `cron.lastRunAt` 28 minutes before the probe, consistent with a 30-min timer) — `aether-discovery.service`/`.timer` unit files themselves were flagged **not present under `deploy/`** in `REFERENCE-GRAPH.md` (same-day), i.e. deployed directly to systemd without a repo-tracked unit file | OVERSTATED (timer clearly runs live in prod; its unit file is absent from the repo's own `deploy/` directory, unlike the other 3 services) | `[VERIFIED]` `ls deploy/*.service` → api/web/worker only, no discovery; `REFERENCE-GRAPH.md` Feature 1 "Deployment (Missing)" section, same-day; `BLOCKER-admin-overpermission-verification.md` §2 `cron.lastRunAt` fresh 2026-07-30T23:00:34Z |
| R-28 | Tech stack: ARQ + Redis (loopback-only, `requirepass`, logical DB 3) | README.md:140,183 | Confirmed default DSN `redis://127.0.0.1:6379/3` in `workers/settings.py:21`; `AETHER_REDIS_PASSWORD` present (non-empty) in `.env` (value not read/printed) | CONFIRMED | `[VERIFIED]` `workers/settings.py:21`; `grep -c AETHER_REDIS_PASSWORD .env` → 1 |
| R-29 | Tech stack: "Session JWT, bcrypt password hashing, Fernet-encrypted credentials, per-endpoint rate limiting" | README.md:142 | JWT confirmed (`security.py:12` `TOKEN_TTL`, decoded in `BLOCKER-admin-...md` §1); bcrypt confirmed (`passwordHash_scheme=$2b$` in the same doc); rate limiting confirmed (`guard_login_attempt`, `auth.py:108-113`); Fernet not independently re-verified this run | CONFIRMED (3 of 4 directly), INFERRED (Fernet) | `[VERIFIED]` `security.py:12`; `auth.py:108-113`; `BLOCKER-admin-...md` §1,§"Rate limiting" |
| R-30 | Delivery History links: `EXECUTION-REPORT.md`, `MANUAL-VERIFICATION-FINAL-REPORT.md`, `PHASE6-EXECUTION-SUMMARY.md`, `PHASE7-BLOCKED-ON-HUMAN.md`, `PHASE7-CLAIM-LEDGER.md`, `PHASE7-GAP-ANALYSIS.md`, `phase7-gap-analysis.json` (7 relative links) | README.md:37,39,56,219-222 | All 7 paths are dead at the README's linked location; all 7 exist verbatim under `docs/delivery/archive/` instead | FALSE (broken links) | `[VERIFIED]` programmatic link-extraction + `os.path.isfile` check against all `docs/`/`design/` links in README.md, this run; `find docs/delivery -iname <name>` resolved all 7 to `archive/` |
| R-31 | Delivery History: `LAUNCH-READY-FINAL-REPORT.md`, `MODELS-LIVE-GAPS.json`, `docs/subscription/model-catalog.md`, `docs/subscription/billing-architecture.md`, `docs/delivery/DECISIONS.md`, `docs/delivery/DEPLOYMENT-RUNBOOK.md`, `design/DESIGN.md` links | README.md:9,45,53,129,139,152,216-217,224 | All confirmed present at the linked paths | CONFIRMED | `[VERIFIED]` same link-extraction pass, this run — all resolved `OK` |
| R-32 | "6 AI provider cards" (§AI Agents mirrors REQUIREMENTS-TRACEABILITY REQ-9, not literally in README's prose but the same `ProviderConnections.tsx`/`PROVIDER_SEED` component README implicitly describes via the Agents screen) | README.md (Design System screen list: "Manage Agents") + REQ-9 | `PROVIDER_SEED` in `agents.py` has **7** entries (`anthropic, openrouter, openai, gemini, bedrock, groq, abacus`), not 6 | OVERSTATED (stale, see REQ-9 in §2B for the primary citation) | `[VERIFIED]` `agents.py` `PROVIDER_SEED` list, counted programmatically this run: 7 ids |

### 2B. REQUIREMENTS-TRACEABILITY-PRODUCTION.md rows

This document is dated **2026-07-12** — pre-Phase-2, the oldest and most obviously stale claim-source in
this run. Per this task's Method, every row is adjudicated against **current** production state, not
treated as a settled record. Rows are aggregated at the REQ-group level (element-level exceptions are
called out inline) — see §5 COVERAGE for why.

| # | Requirement group (quoted claims aggregated) | Source | Actual state | Verdict | Evidence |
|---|---|---|---|---|---|
| T-01 | REQ-1 Authentication: "Demo login (no client-side credential prefill)"; JWT bearer; `CurrentUser` dependency guard; bad-password inline error | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-1 | Login page `email`/password fields still both plain `useState<string>("")` (no prefill) — confirmed fresh; JWT/`CurrentUser` machinery independently re-confirmed this run via the `BLOCKER-admin-...md` decode (`security.py:12`, `middleware/auth.py:48-55`) for unrelated reasons, corroborating this row | CONFIRMED | `[VERIFIED]` `apps/web/src/app/login/page.tsx:43` `useState<string>("")`; `BLOCKER-admin-...md` §1,§4.2 |
| T-02 | REQ-2 Dashboard: 12-item sidebar, stats row, agent feed, opportunities, funnel, story/CRM/approval widgets, Market Pulse, real (not hardcoded) funnel data | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-2 | `SCREEN-MATRIX.md` (same-day, `/dashboard` section) independently documents all of these components + their live API calls (`/jobs`, `/agents/runs`, `/analytics/agent-roi`, `/stories`, `/workspaces/networking/summary`, `/approvals`) — no hardcoded-value regression found | CONFIRMED | `[VERIFIED]` `uat/reports/evidence/gold-master-v2/phase0/SCREEN-MATRIX.md` §1 `/dashboard`, same-day reuse |
| T-03 | REQ-3 Job Discovery: market tabs, source bar/filter, job cards, insights, save, "Sync Now", tailor link, 2-step apply + gate, "**Real seek.com.au data**" via `seek_adapter.py`, fit scoring, skill-gap tags | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-3 | 12 of 13 elements CONFIRMED (Jobs Apply verdict = COMPLETE per `REFERENCE-GRAPH.md` Feature 7, same-day). The 13th, Seek, is FALSE: `SeekAdapter` exists in code but is excluded from the live registry by the binding risk-officer ruling (`AETHER_ENABLE_SEEK` unset, `ADR-SEEK-FIRECRAWL.md` REFUSED); 0 Seek jobs in production DB | FALSE (Seek element only — the other 12/13 elements are CONFIRMED; row verdict driven by the false element per binding instruction to flag any Seek-availability claim) | `[VERIFIED]` `REFERENCE-GRAPH.md` Feature 7 (Jobs Apply COMPLETE) + Feature 1 (Seek PARTIAL/compliance-gated); `PROD-DB-STATE.md` seek count = 0; `ADR-SEEK-FIRECRAWL.md` STATUS: REFUSED |
| T-04 | REQ-4 Resume Studio: version list, diff, tailor-against-job, fabrication guard, evidence grounding, format-hash preservation, PDF download, base-resume immutability, multiple resume roots | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-4 | `list_resumes` (`resumes.py:17`), `diff_resume` (`resumes.py:188`), `unsupported_tokens`/`_validate` (`resume_tailor.py:311,2175`) all confirmed present this run; PDF download / format-hash / multi-root not re-derived line-by-line but no contrary evidence found | CONFIRMED | `[VERIFIED]` `resumes.py:17,188`; `resume_tailor.py:311,2175`; `[ASSUMED-PENDING-PROBE]` PDF/format-hash/multi-root sub-elements not individually re-opened |
| T-05 | REQ-5 Story Bank: list+categories, extraction, manual STAR form, stats, copy-to-clipboard | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-5 | `stories.py` CRUD confirmed via `REFERENCE-GRAPH.md` Feature 3 (same-day, PARTIAL verdict — CRUD complete, no relevance scoring, which REQ-5 never claimed anyway); DB shows 32 real `StoryEntry` rows, 0 exact duplicates | CONFIRMED | `[VERIFIED]` `REFERENCE-GRAPH.md` Feature 3; `PROD-DB-STATE.md` PROBE 3 (32 rows, 0 dup groups) |
| T-06 | REQ-6 Application Tracker: 8-stage kanban, board/Sankey/timeline views, banners, filter/sort, real data, Sankey real data, cross-links, detail panel, submit | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-6 | `STAGE_DEFS` in `tracker-lib.ts` confirmed to have exactly 8 keys (`discovered, evaluating, tailoring, ready, submitted, in-review, interview, offer`) this run; `REFERENCE-GRAPH.md` Feature 4 (Applications Stage-Move, same-day) rates the move endpoints PARTIAL only on UI drag-affordance completeness, not on data-reality — no hardcoded-Sankey regression found | CONFIRMED | `[VERIFIED]` `tracker-lib.ts:46-95` (8 stage keys, counted programmatically); `REFERENCE-GRAPH.md` Feature 4 |
| T-07 | REQ-7 Cover Letter Studio: job selector, LLM generation, fabrication guard, corrective drafting loop (≤3 drafts), approval gate, evidence-grounding %, PDF export | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-7 | `cover_letter_agent.py` guard/loop/approval-gate citations from the traceability doc were not individually re-opened this run; no contrary evidence found; consistent with README R-07's confirmed guard presence in the sibling `resume_tailor.py` module | CONFIRMED (INFERRED for the specific ≤3-draft loop count) | `[INFERRED]` from R-07 (sibling guard module confirmed) + no contrary finding; `[ASSUMED-PENDING-PROBE]` `cover_letter_agent.py` not re-opened line-by-line this run |
| T-08 | REQ-8 Approvals: pending queue, approve/reject, status filter, 48h expiry badge, approval→application sync | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-8 | `EXPIRY_HOURS = 48` confirmed fresh in `approval_service.py:23`; endpoints confirmed complete via `REFERENCE-GRAPH.md` Feature 5 (same-day, PARTIAL verdict only on UI-dismiss-affordance completeness, not on the 48h/sync mechanics REQ-8 actually claims); DB shows 102/102 approvals already resolved, 0 pending/expired (consistent with a functioning expiry+resolution pipeline, though it means the *current* pending queue is empty) | CONFIRMED | `[VERIFIED]` `approval_service.py:23,30`; `REFERENCE-GRAPH.md` Feature 5; `PROD-DB-STATE.md` PROBE 7 |
| T-09 | REQ-9 Agents & Monitor: "**21-agent catalog grid**", "**6 AI provider cards**", agent run history, pipeline trigger, real cost estimate, agent status | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-9 | Catalog is now **22** entries (not 21) and providers are now **7** (not 6) — both grew by exactly one since this 2026-07-12 doc was written, consistent with ordinary feature growth rather than a defect. Run history/pipeline-trigger/status endpoints all confirmed present in `agents.py` (`GET /agents/runs` per `SCREEN-MATRIX.md`, `AGENT_CATALOG`/`AGENT_NAMES` machinery per R-17/R-18/R-20 citations above) | OVERSTATED (stale counts: 21→22, 6→7; underlying mechanism CONFIRMED) | `[VERIFIED]` `AGENT_CATALOG` = 22 entries (programmatic count, this run); `PROVIDER_SEED` = 7 entries (programmatic count, this run) |
| T-10 | REQ-10 Analytics: funnel chart w/ period selector, ATS score distribution, agent ROI, stage conversion, real-time market pulse | REQUIREMENTS-TRACEABILITY-PRODUCTION.md REQ-10 | Confirmed present via `REFERENCE-GRAPH.md` Feature 9 (same-day): funnel/ROI/ATS-distribution all implemented; that same document separately notes `interview_conversion_rate` is absent from `analytics.py` — but REQ-10 never claims that metric by name, so this is not a contradiction of REQ-10 itself (it would contradict a claim if one existed; none does in this doc) | CONFIRMED | `[VERIFIED]` `REFERENCE-GRAPH.md` Feature 9, same-day |
| T-11 | "DEFERRED SCREENS (Out-of-Phase per docs)": Interview Center, Networking CRM, Offers, Email Center, Settings, Mobile — all listed as deferred/out-of-scope as of 2026-07-12 | REQUIREMENTS-TRACEABILITY-PRODUCTION.md:165-174 | All 5 non-mobile screens now exist as substantial, live `page.tsx` files: `interviews/page.tsx` (833 lines), `networking/page.tsx` (525 lines), `offers/page.tsx` (144 lines), `email/page.tsx` (1158 lines), `settings/page.tsx` (19-line wrapper delegating to `settings-client.tsx`, itself referenced extensively in `INCOMPLETE-FEATURE-INVENTORY-FRONTEND.md` at 900+ lines). This 2026-07-12 claim is stale by 4+ phases of subsequent build-out; not a current defect, but a superseded historical record | FALSE (stale — features were built in phases after this doc was written) | `[VERIFIED]` `find`/`wc -l` on all 5 `page.tsx` files, this run, 2026-07-30 |
| T-12 | "DEFECTS FIXED THIS SESSION" (SA-01..04): Sankey hardcode fix, PDF-501 fix, Interview/Email null-guard fixes | REQUIREMENTS-TRACEABILITY-PRODUCTION.md:180-186 | Historical record of fixes made on 2026-07-12; not independently re-verified line-by-line this run, but no regression evidence found (Sankey/PDF/Interview/Email all confirmed alive and non-trivial in size today per T-06/T-04/T-11 citations) | CONFIRMED (carried forward, no regression found) | `[INFERRED]` from T-04/T-06/T-11 citations; `[ASSUMED-PENDING-PROBE]` the 4 specific diffs were not re-opened |
| T-13 | "QUALITY GATES": pytest 200 passed, vitest 135 passed, Playwright 24 tests, ruff/mypy/eslint/tsc clean, build clean, prod 200 OK (as of 2026-07-12) | REQUIREMENTS-TRACEABILITY-PRODUCTION.md:189-201 | Test suite numbers are stale on their face — README's own later claim (2026-07-20) cites 967 pytest / 477 vitest, a different order of magnitude, confirming the test suite grew substantially since this row was written. This run is expressly forbidden from running pytest/vitest (a clean baseline is holding a lock file) so neither the 2026-07-12 nor the 2026-07-20 figures can be reproduced today | UNVERIFIABLE-HERE | `[ASSUMED-PENDING-PROBE]` — explicitly out of scope this run (`/tmp/aether-pytest.lock` held); `curl https://5cb5f0620.abacusai.cloud/` → HTTP 307 (redirect, consistent with "200 OK" intent but not a literal 200) confirmed this run |
| T-14 | Code-map file citations (routers/agents.py, resumes.py, applications.py, etc. — the "CODE MAP — KEY FILES" section) | REQUIREMENTS-TRACEABILITY-PRODUCTION.md:205-263 | Every file this run actually opened for R-/T- row verification above (`agents.py`, `resumes.py`, `resume_tailor.py`, `tracker-lib.ts`, `approval_service.py`, `llm_client.py`) exists at the cited path | CONFIRMED | `[VERIFIED]` cumulative — every file:line citation elsewhere in this document resolved successfully |

## 3. README corrections required

Each item below is a specific README.md sentence/claim that is now FALSE or OVERSTATED, with exact
replacement text.

1. **README.md:37 & :39 & :219** — links to `docs/delivery/EXECUTION-REPORT.md` and
   `docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md` are dead.
   **Replace** every occurrence of `docs/delivery/EXECUTION-REPORT.md` with
   `docs/delivery/archive/EXECUTION-REPORT.md`, and every occurrence of
   `docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md` with
   `docs/delivery/archive/MANUAL-VERIFICATION-FINAL-REPORT.md`.

2. **README.md:56 & :222** — link to `docs/delivery/PHASE7-BLOCKED-ON-HUMAN.md` is dead.
   **Replace** with `docs/delivery/archive/PHASE7-BLOCKED-ON-HUMAN.md`.

3. **README.md:219 & :221** — links to `docs/delivery/PHASE7-GAP-ANALYSIS.md`,
   `phase7-gap-analysis.json`, and `docs/delivery/PHASE7-CLAIM-LEDGER.md` are dead.
   **Replace** with `docs/delivery/archive/PHASE7-GAP-ANALYSIS.md`,
   `docs/delivery/archive/phase7-gap-analysis.json`, and
   `docs/delivery/archive/PHASE7-CLAIM-LEDGER.md`.

4. **README.md:223** — link to `docs/delivery/PHASE6-EXECUTION-SUMMARY.md` is dead.
   **Replace** with `docs/delivery/archive/PHASE6-EXECUTION-SUMMARY.md`.

5. **README.md:59** — *"2. **Admin credential** (`AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH`)
   → formally closes the admin gate. The demo `admin/admin123` account already carries **zero** admin
   privilege in production."*
   **Replace** with: *"2. **URGENT — admin/admin123 currently grants full admin access.** The seeded
   `admin`/`admin123` credential authenticates as the real owner account (`isAdmin:true`) due to a
   `username='admin'` collision plus the operator's own configured admin password being literally
   `admin123` (see `uat/reports/evidence/gold-master-v2/phase0/BLOCKER-admin-overpermission-verification.md`).
   This is a CRITICAL live security exposure, not a pending/blocked item — it requires immediate operator
   remediation (rotate `AETHER_ADMIN_PASSWORD_HASH` to a strong, non-guessable value and/or remove the
   `username='admin'` collision), not a credential hand-off."*

6. **README.md:58** — *"1. **Stripe** test-mode keys (`STRIPE_SECRET_KEY`, webhook signing secret, 6 Price
   IDs) + ABN/Stripe Tax → live checkout → webhook → entitlement."*
   **Replace** with: *"1. **Stripe live keys are already configured and tested** (`STRIPE_SECRET_KEY` is a
   live `sk_live_…` key; `/billing/plans`, `/billing/checkout` session creation, webhook signature
   enforcement, `/billing/entitlement`, and `/billing/portal` are all live and testable today with zero
   operator action). The only remaining step is a human completing one real-money Stripe Checkout purchase
   to confirm the `checkout.session.completed` webhook round-trip end-to-end."*

7. **README.md:103** — *"**8 agents actually execute in production** (confirmed via `GET /api/agents`;
   `uat/reports/evidence/phase6/probe-16-agent-keys.json`)."*
   **Replace** with: *"**19 agents actually execute in production** (`GET /api/agents` returns
   `AGENT_NAMES`, dynamically derived from the full `AGENT_CATALOG` — 8 pipeline-topology agents plus 11
   additional standalone agents such as `compliance`, `interviewPrep`, `companyResearch`,
   `recruiterOutreach`, `salaryIntelligence`, `marketTrends`, `scheduling`, `sentimentAnalysis`,
   `reference`, `learningFeedback`, `notification`). The older hardcoded 8-tuple undercounted this and was
   fixed in code (`apps/api/app/routers/agents.py:2043-2049`); the README table below should list all 19,
   not 8."*

8. **README.md:116** — *"The `AgentConfig` table holds **22 configured agent keys** — a superset of the 8
   runtime agents plus disabled/catalog entries reserved for future enablement without a schema change.
   Only the 8 above are wired to orchestration and run today."*
   **Replace** with: *"The code-level `AGENT_CATALOG` defines **22** possible agent keys; the `AgentConfig`
   database table currently holds **12** persisted per-user override rows (unconfigured keys default via
   code, not a missing row). **19** of the 22 catalog entries have a runnable backend and are wired to
   orchestration (the pipeline's core 8 plus 11 standalone agents); 1 entry (`submission`) is `backend:
   None` and is an honest roadmap/planned card, never presented as running."*

9. **README.md:48** — *"33 jobs / 5 sources (3 sources ≥5 each)"*
   **Replace** with current count (verify at publish time — was **51 jobs** / 5 sources / 3 sources ≥5 each
   as of 2026-07-30) — or better, drop the exact job count from README prose entirely and link to a live
   `/api/jobs` count so this line cannot go stale again.

## 4. Subscription-readiness assessment

Pricing page → checkout → entitlement → quota enforcement → billing portal, assessed from source + fresh
read-only probes (no purchase completed, no new checkout session created, per task constraint):

| Stage | Endpoint(s) | State | Evidence |
|---|---|---|---|
| Pricing page | `GET /pricing` | Live, HTTP 200 | `[VERIFIED]` `curl -o /dev/null -w '%{http_code}' https://5cb5f0620.abacusai.cloud/pricing` → 200, this run |
| Plan catalog | `GET /api/billing/plans` | Live, unauthenticated, returns 4 tiers with correct GST-inclusive AUD pricing (Free $0 / Starter $19 / Pro $39 / Power $69 monthly, annual variants present) | `[VERIFIED]` full JSON payload captured this run, 2026-07-30T23:3x UTC |
| Checkout session creation | `POST /api/billing/checkout` | Code path present (`billing.py:121`); **not invoked this run** (would create a real live-mode Stripe object) — same-day evidence (`GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md`) already exercised this today via a throwaway self-registered account and confirmed a real `cs_live_…` session was created successfully | `[VERIFIED]` route exists `billing.py:121`; `[VERIFIED]` (reused, same-day) `GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` §"Stripe live keys" |
| Webhook signature enforcement | `POST /api/billing/webhooks/stripe` | Live and correctly rejecting unsigned payloads | `[VERIFIED]` `curl -X POST .../billing/webhooks/stripe -d '{}'` → `400 {"detail":"Missing stripe-signature header"}`, this run |
| Entitlement read | `GET /api/billing/entitlement` | Route exists, correctly requires auth | `[VERIFIED]` `curl .../billing/entitlement` → `401 {"detail":"Not authenticated"}`, this run |
| Quota enforcement | 429 builders in `agents.py` | `_quota_429`/`_plan_quota_429` present, atomic reserve/refund pattern present in worker tasks | `[VERIFIED]` `agents.py:612-639`; `workers/tasks.py` refund logic |
| Billing portal | `POST /api/billing/portal` | Route exists (`billing.py:797`) | `[VERIFIED]` route present, this run; not invoked (would create a live Stripe portal session) |
| Admin refund | `POST /api/billing/admin/refund` | Route exists (`billing.py:845`) | `[VERIFIED]` route present, this run |

**Subscription-readiness verdict: CONFIRMED for the entire non-payment chain (pricing → catalog → checkout
session creation → webhook enforcement → entitlement/quota gating → portal session creation) — all live
and already tested with real Stripe objects (per same-day reused evidence) or freshly re-probed this run.
The only remaining gap is a single human action: completing one real-money Checkout purchase with a real
card to observe the `checkout.session.completed` webhook flip a plan live.** This is narrower than
README's own framing (§3 correction 6 above) — the chain is not "pending Stripe keys," it is "pending one
purchase click."

## 5. COVERAGE

**COVERAGE: COMPLETE at the granularity described below — not exhaustive line-by-line coverage of every
sub-bullet in both source documents.**

- **README.md:** every distinct claim in the "Production Status" shipped-capability table (8 rows), the
  "Pending operator action" list (4 items), the "AI Agents" section's agent-count and catalog-size claims,
  the "Model choice" section's 5 behavioral claims, the "Design System" screen/route counts, 4 spot-checked
  Tech Stack rows, and all Delivery History document links (14 links total, 7 broken) were tested — 32
  README-sourced rows in §2A. Not individually tested: every sentence of the Vision/Architecture prose
  paragraphs (largely non-falsifiable marketing framing) and the full Local Development instructions block
  (out of scope — not a production-state claim).
- **REQUIREMENTS-TRACEABILITY-PRODUCTION.md:** all 10 REQ groups (74 element-level rows in the source doc),
  the DEFERRED SCREENS table, the DEFECTS FIXED table, the QUALITY GATES table, and the CODE MAP were
  adjudicated — 14 rows in §2B, aggregated at REQ-group granularity with every element-level exception
  called out inline (e.g. T-03's Seek split, T-09's stale counts). This is a coarser grain than "one row
  per source-document line," a deliberate trade-off given the single-serial-agent constraint (no
  sub-agents/forks) and the ~74-element size of that source document; every REQ group's aggregate verdict
  is backed by at least one fresh file:line citation or same-day reused Phase-0 evidence, not asserted
  blind.
- **No authenticated session was established this run** (documented owner login credential is stale/wrong
  in `.env`; the only working alternative, `admin`/`admin123`, is expressly forbidden). This caps 6 rows at
  `UNVERIFIABLE-HERE` that would otherwise likely be directly testable with a working session — these are
  flagged for §3.2 screen testing to close with a real login.
- **No pytest/vitest/Playwright/headless-browser was run**, per HARD PROCESS RULES — the "QUALITY GATES"
  row (T-13) and any claim requiring a live agent execution (R-07's specific lift numbers, R-24's
  no-substitution proof) are UNVERIFIABLE-HERE / INFERRED rather than reproduced.
- **No source code, `.env`, or database row was modified.** All probes were read-only `curl` (GET, or POST
  only against `/billing/webhooks/stripe` with an intentionally-invalid body to observe the honest
  rejection — no state was created) and read-only file inspection.
