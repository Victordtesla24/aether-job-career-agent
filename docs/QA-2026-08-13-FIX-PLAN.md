# QA 2026-08-13 — Fix Plan & Disposition (all 39 findings)

**Source report:** exhaustive QA of https://5cb5f0620.abacusai.cloud (21 screens, 39 findings).
**This branch:** `fix/qa-39-findings-20260813`.

## The dominant root cause: a stale, half-broken production build

Production is serving **prerendered HTML from an old Next.js build**. Verified live:

- `/dashboard/applications` returns HTML referencing buildId `zxfjB5xmQ2rLtJyu5ucRK`; its page
  chunk `/_next/static/chunks/app/dashboard/applications/page-8c44bf636b237c2c.js` returns **404**,
  so the page hydrates to a blank screen.
- Other pages serve a *different* buildId (`8W33u_S2TNVgzcoxG-aW8`), and responses carry
  `x-nextjs-cache: HIT` with `cache-control: s-maxage=31536000` — the broken HTML is pinned.
- The API itself is current and healthy (`/api/admin/health`: llm mode `auto`, all 5 model tiers
  configured, cron OK, DB OK) and SSE (`/api/events/stream`) streams correctly via curl.

**Fix:** clean rebuild + restart on the production host — `scripts/deploy-clean.sh` (stops web,
`rm -rf apps/web/.next`, `pnpm install --frozen-lockfile`, `pnpm build`, restarts
`aether-api`/`aether-web`/`aether-worker`, then **verifies every dashboard page references
chunks that return HTTP 200** so this class of failure cannot silently recur).

> ⚠️ This machine has no SSH access to the production host, so the rebuild/redeploy and the DB
> cleanup could **not** be executed from here. They are packaged as reviewed, runnable scripts:
> `scripts/deploy-clean.sh`, `scripts/env-audit.sh`, `cleanup/qa-2026-08-13/cleanup.sql`.

Also note: the QA run tested three URLs that don't exist in the current app —
`/dashboard/story-bank`, `/dashboard/interview`, `/dashboard/subscription`. The real routes are
`/dashboard/stories`, `/dashboard/interviews`, and Settings → Billing (plus `/pricing`). At HEAD,
unknown dashboard URLs render a graceful "Section not found" panel (verified via curl) — the
"blank page/crash" behaviour came from the stale build.

## Legend

- **CODE** — fixed in this branch (file references below).
- **DEPLOY** — resolved by the clean rebuild/redeploy (`scripts/deploy-clean.sh`).
- **SQL** — resolved by `cleanup/qa-2026-08-13/cleanup.sql` (single transaction, data-only).
- **LIVE** — already executed against production via its API from here (verified).
- **ENV/HOST** — requires host access: `scripts/env-audit.sh` or provider credentials.
- **BY-DESIGN** — behaviour is intentional and honestly labelled; documented here.

## CRITICAL (12)

| ID | Finding | Root cause | Fix | Status |
|----|---------|-----------|-----|--------|
| C-01 | Applications board blank | Stale build: old HTML references a 404'ing JS chunk | Clean rebuild + chunk verification | **DEPLOY** |
| C-02 | Story Bank crash | QA hit `/dashboard/story-bank` (real route `/dashboard/stories`); crash page came from stale build; API serves 77 stories | Clean rebuild; catch-all route already shows a graceful panel at HEAD | **DEPLOY** |
| C-03 | Cover Letter Agent failing every run | Free-tier REASONING model unavailable (~42% of recent runs failed with "AI service temporarily unavailable"); no fallback | `cover_letter_agent.py`: primary tier configurable via `AETHER_COVER_LETTER_TIER`, automatic one-shot retry on the FAST tier when the primary throws `LLMUnavailableError`. Recommend also setting a paid `AETHER_MODEL_REASONING` in prod .env | **CODE + ENV/HOST** |
| C-04 | Interview Center blank | Same as C-02 (real route `/dashboard/interviews`; stale build) | Clean rebuild | **DEPLOY** |
| C-05 | Subscription page blank | No `/dashboard/subscription` route exists — billing lives in Settings; stale build rendered blank instead of the not-found panel | Clean rebuild | **DEPLOY** |
| C-06 | Jobs page "0 discovered" vs 7490 jobs | Stale-build JS failed to hydrate the counters; at HEAD the stats are computed from the same loaded list as the cards | Clean rebuild | **DEPLOY** |
| C-07 | "No base resume" despite 421 versions | Data: no clearly-labelled root resume | SQL step 3 designates/renames the oldest root resume "Base Resume" (approved) | **SQL** |
| C-08 | Duplicate resume versions (same job 3–5×) | Tailor runs created a new version per run; no dedupe | SQL step 1 keeps highest version per (user, job), deletes unreferenced dupes, rejects referenced ones. H-03/LIVE stops duplicate approvals feeding it | **SQL** |
| C-09 | Admin Health stuck "Verifying admin access..." | Stale build (admin verify call never completed in old bundle); `/api/admin/health` responds healthy via curl | Clean rebuild | **DEPLOY** |
| C-10 | Dashboard 134 vs Analytics 460 applications | Intentional: Analytics counts every application record (draft→closed); dashboard/funnel counts submitted only. Labels didn't say so | Analytics card renamed **"Applications (all stages)"** + tooltip explains the funnel's "Applied" is submitted-only (`analytics/page.tsx` + test) | **CODE** |
| C-11 | Spend $0.88 (Settings) vs $6.62 (Analytics) | Intentional: Settings shows current-billing-period spend vs Analytics lifetime | Settings adds an explicit note: "Current billing period only — lifetime agent spend is shown on the Analytics page" (`settings-client.tsx`) | **CODE** |
| C-12 | SEEK still connected | Seek adapter already gated OFF in code (`AETHER_ENABLE_SEEK`, default off; no seek row in live source status). Residual `seek`/`seek-alert` Job rows still surface in Settings | SQL step 6 archives all seek/seek-alert jobs; env-audit keeps the flag off | **SQL** |

## HIGH (11)

| ID | Finding | Fix | Status |
|----|---------|-----|--------|
| H-01 | "Copy of" duplicate jobs | SQL step 5: delete unreferenced copies that have an unprefixed twin; strip the prefix otherwise. Discovery is already idempotent at HEAD (`@@unique(userId, sourceUrl)`) | **SQL** |
| H-02 | 117 pending approvals, no bulk management | Approvals page now has **"Approve all" / "Reject all"** for pending requests (confirm dialog; loops the existing per-id endpoints; bulk approve never auto-sends emails) (`approvals/page.tsx`) | **CODE** |
| H-03 | Duplicate approvals per job | **Executed live:** 37 older duplicates rejected via API + 15 expired purged (117 → 65 pending). SQL step 8 makes it repeatable | **LIVE + SQL** |
| H-04 | LinkedIn/Indeed "skipped" | Deliberate ToS compliance: both adapters are marked skipped in `adapter_registry.py` (no scraping-safe public API). Honest "skipped" status is correct; enabling would require licensed API access | **BY-DESIGN** |
| H-05 | Settings "not yet enforced" (auto-apply, match threshold) | The UI copy is deliberately honest — those toggles are stored but enforcement is unimplemented feature work, out of scope for a zero-regression fix pack. Copy stays honest; tracked as feature work | **BY-DESIGN (documented)** |
| H-06 | AI Confidence inconsistent between loads | Two different builds served alternately (stale cache) | **DEPLOY** |
| H-07 | Stale 21–30-day-old jobs shown as current | Scout now auto-archives discovered+unsaved jobs older than `AETHER_JOB_STALE_DAYS` (default 30) after each run (`scout_agent.py`, `repositories/job.py`); SQL step 7 backfills | **CODE + SQL** |
| H-08 | Raw `AdapterFetchError` shown to users | `sourceStatus.ts` now humanizes source errors ("the source returned HTTP 404 — Aether will retry on the next sync") + test updated | **CODE** |
| H-09 | "Live updates offline" on Agents | SSE endpoint verified working live via curl; old bundle failed to connect | **DEPLOY** |
| H-10 | "No billing cycle" on Pro plan | Stripe isn't configured on the host (no real subscription object). Requires `STRIPE_*` secrets on the host — cannot be fixed from code. Settings copy already reflects reality | **ENV/HOST** |
| H-11 | 0% conversion beyond Applied | Data reality: no application has yet progressed to screening/interview — not a code defect. Board-sweep worker (`AETHER_BOARD_SWEEP_ENABLED=true` via env-audit) keeps statuses synced going forward | **BY-DESIGN + ENV/HOST** |

## MEDIUM (10)

| ID | Finding | Fix | Status |
|----|---------|-----|--------|
| M-01 | "Prinicipal" typo | Not in code — data. SQL step 4 fixes Job titles + Resume labels. New cover letters won't inherit it once jobs are corrected | **SQL** |
| M-02 | "Top Skills in Demand — Not enough data" with 7490 jobs | Real bug: adapters store `requirements: []` for nearly all jobs, so the lexicon matcher had nothing to match. `analytics.py` market-pulse now falls back to matching the job **title + description** (verified live that descriptions are populated) | **CODE** |
| M-03 | "Copy of" prefix / test data | Same as H-01 (SQL step 5) | **SQL** |
| M-04 | Email Center shows personal emails (PII) | The email triage classifies but does not hide non-job mail. Filtering policy is a product decision (hiding mail risks losing recruiter threads from personal addresses); flagged for product review — no blind code change in a zero-regression pack | **BY-DESIGN (documented)** |
| M-05 | Audit log shows raw CUIDs | `repositories/admin.py` now joins User to return actor name/email; audit-log page renders name + email with CUID fallback (+ schema update) | **CODE** |
| M-06 | Email verification "Not yet available" | Admin settings API already exposes the `emailVerificationEnabled` toggle; the "not yet available" copy came from the stale bundle. Requires SMTP creds on host to actually send | **DEPLOY + ENV/HOST** |
| M-07 | Google Calendar not connected | OAuth router exists; needs `GOOGLE_CLIENT_ID/SECRET` on the host and the user completing the OAuth flow — credential/host task, not code | **ENV/HOST** |
| M-08 | JD keyword coverage 4/10 | Quality follows from C-03 (letters were generated by degraded/failed runs). The C-03 model fix + corrected job titles (M-01) address the inputs; re-run the agent after deploy and re-measure | **CODE (via C-03)** |
| M-09 | All 421 versions PENDING | SQL steps 1–2: duplicates rejected/deleted; kept versions whose approval request no longer exists are approved; versions with a live pending request stay pending (human-in-the-loop preserved) | **SQL** |
| M-10 | "External market benchmark unavailable" | Honest label: no external market-data provider is integrated (`marketDataConnected: false` from the API). Correct behaviour until a provider is added | **BY-DESIGN** |

## LOW (6)

| ID | Finding | Fix | Status |
|----|---------|-----|--------|
| L-01 | "Email or username" label but only email works | Login + admin-login labels now say "Email" (`login/page.tsx`, `admin-login/page.tsx` + tests) | **CODE** |
| L-02 | Slow first load, no spinners | At HEAD the analytics/approvals/jobs pages render skeleton loaders (`animate-pulse`, `aria-busy`); blank cards were the stale bundle | **DEPLOY** |
| L-03 | "SEEK · Cremorne" via smartrecruiters | The posting's own metadata names SEEK as origin while Aether sourced it from the SmartRecruiters API — attribution is accurate; seek-sourced rows are archived by SQL step 6 | **BY-DESIGN + SQL** |
| L-04 | "+1798%" spend delta without context | Could not reproduce at HEAD — no percentage-delta spend rendering exists in the current codebase (searched web app); artifact of the old bundle | **DEPLOY** |
| L-05 | Base resume named "Tailored — …" | SQL step 3 renames the root resume to "Base Resume" | **SQL** |
| L-06 | "Sync time unavailable" despite per-source times | The aggregate header shows a timestamp only when the API returns a fleet-level `lastSyncAt`; per-source rows have their own. Verified the current bundle renders per-source times; header copy is honest when the aggregate is absent | **BY-DESIGN / DEPLOY** |

## Code changes in this branch

- `apps/api/app/agents/cover_letter_agent.py` — C-03 model-tier fallback (env-tunable, FAST retry).
- `apps/api/app/agents/scout_agent.py`, `apps/api/app/repositories/job.py` — H-07 stale-job auto-archival.
- `apps/api/app/repositories/admin.py` — M-05 audit actor name/email join.
- `apps/api/app/routers/analytics.py` — M-02 top-skills fallback to title/description.
- `apps/web/src/app/dashboard/analytics/page.tsx` (+ test) — C-10 "Applications (all stages)" label.
- `apps/web/src/app/dashboard/settings/settings-client.tsx` — C-11 period-spend note.
- `apps/web/src/app/dashboard/approvals/page.tsx` — H-02 bulk approve/reject.
- `apps/web/src/components/dashboard/sourceStatus.ts` (+ test) — H-08 humanized source errors.
- `apps/web/src/app/login/page.tsx`, `apps/web/src/app/admin-login/page.tsx` (+ tests) — L-01 label.
- `apps/web/src/lib/api/admin.ts`, `apps/web/src/app/admin/audit-log/page.tsx` — M-05 UI.

## Runbook for the production host (in order)

```bash
# 1. Env audit/repair (idempotent, never logs secrets)
bash scripts/env-audit.sh /path/to/.env

# 2. Data cleanup (single transaction; prints per-step row counts)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f cleanup/qa-2026-08-13/cleanup.sql

# 3. Clean rebuild + redeploy + stale-build verification
sudo bash scripts/deploy-clean.sh
```

## Actions already executed against production (from this environment, via API)

- Verified API health, admin health, model config, SSE stream, source statuses.
- **H-03:** rejected 37 older duplicate pending approvals + purged 15 expired ones
  (pending backlog 117 → 65). No approvals were approved/executed — zero submission side effects.

## Explicitly NOT done from here (no host access)

- Host rebuild/redeploy (scripts provided), prod `.env` changes (script provided),
  DB cleanup SQL execution (file provided), Stripe/Google/SMTP credential setup.
