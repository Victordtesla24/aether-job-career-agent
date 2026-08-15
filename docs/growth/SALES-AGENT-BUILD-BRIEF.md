# Build Prompt: Native Sales AI Agent — Aether Career Agent Admin Portal

**Target repo:** `Victordtesla24/aether-job-career-agent` (main branch, current HEAD as of 2026-08-15)
**Target agent:** Claude Opus/Sonnet-class coding agent ("Fable 5" / "Opus 5" / "Sonnet 5 1M" or equivalent) with full repo, shell, and browser-verification access
**Author of this brief:** Perplexity Computer, compiled from direct, verified inspection of the live repo and the live production deployment on 2026-08-10 through 2026-08-15 (see Evidence Log, §12)
**Status:** Ready to execute. This is a build brief, not a finished plan — the implementing agent still owns architecture-level judgment calls flagged `[DECISION NEEDED]` below.

---

## 0. Read This First — Non-Negotiable Ground Rules

1. **Do not fabricate.** No fake leads, no fake metrics, no invented email addresses, no "sample" data presented as real. Aether's own codebase has a zero-fabrication culture (entailment guard on résumé claims, honest 503/429s instead of fake success, `[VERIFIED-...]` vs `[ASSUMED-...]` evidence tags throughout `docs/`). The sales agent must be held to the exact same standard for its own outputs and its own reporting.
2. **No LinkedIn API/browser automation.** LinkedIn's User Agreement §8.2 bans automating connections, DMs, likes, and profile scraping; 2026 enforcement escalates to permanent bans. The agent may **draft** LinkedIn content for a human to post. It must never attempt to log into LinkedIn, call an unofficial API, or drive a browser against linkedin.com.
3. **Email compliance is mandatory, not optional.** Every commercial/marketing email sent to a real person must carry sender identification and a working unsubscribe mechanism, honored within 5 business days, per Australia's Spam Act 2003 (enforced by ACMA). This is a hard gate in code, not a prompt instruction the model might skip.
4. **Real recipients only.** The agent may only email: (a) someone who has a real inbound thread already in the connected mailbox (signup, demo request, reply, support question), or (b) an existing Aether user with a verifiable account row (re-engagement/upgrade nudges), or (c) a contact with genuine prior correspondence that a human operator has explicitly approved. It must never scrape, buy, or infer a new address from the open web.
5. **Full autonomy is authorized for send actions** on the categories in Rule 4 — the product owner (Vic) has explicitly accepted this and does not want a per-message approval gate for the sales agent specifically. This is a deliberate exception to Aether's own stated platform philosophy ("every outbound action passes an explicit approval item," README §"What Aether Does") — scope the exception narrowly to this agent's own outreach sends, and do not weaken the approval gate anywhere else in the product (job applications, résumé/cover-letter sends to employers stay human-approved as today).
6. **Revenue targets in §8 are goals to work toward and report against, not guarantees the code can enforce.** Real-world subscriber growth depends on market response, the founder's own distribution (posting the drafted content, word of mouth), and pricing/positioning decisions outside this agent's control. Build honest instrumentation and honest reporting; do not build logic that fabricates progress toward a number it cannot actually move alone.

---

## 1. Verified Product Context (do not re-derive — treat as ground truth)

| Fact | Evidence |
|---|---|
| Product | Aether Career Agent — AI job-search assistant: discovers jobs (licensed APIs, no scraping), scores fit (deterministic), tailors résumés/cover letters from the user's own evidence with an anti-fabrication entailment guard, triages email, all gated behind human approval today | `README.md` |
| Live URL | `https://5cb5f0620.abacusai.cloud` | Verified live, 2026-08-13 |
| Stack | Next.js 14 (App Router) frontend (`apps/web`), FastAPI/Python 3.11+ backend (`apps/api`), raw psycopg2 (no ORM) with additive lazy-idempotent DDL (`_ensure_*_tables()` + advisory locks), ARQ+Redis async worker, nginx + systemd on a single VM | `README.md` §Architecture |
| Pricing (AUD, GST-inclusive) | Free $0 (5 runs/mo), Starter $19/mo ($179/yr), Pro $39/mo ($359/yr), Power $69/mo ($649/yr) | `docs/subscription/billing-architecture.md`; confirmed live on `/pricing` 2026-08-13 |
| Checkout | **Confirmed live and functional** — a real signup + Subscribe click redirected to an actual `checkout.stripe.com` **live-mode** session (`cs_live_...`) showing the correct $19 AUD Starter price. No purchase was completed during verification, but the payment rail works end to end. | Live browser test, 2026-08-13 |
| Admin panel | `/admin/*`, gated by `AdminGuard` (frontend) + `AdminUser` dependency (backend, every route independently enforces it — 401 anonymous, 403 non-admin). Existing pages: `/admin` (overview), `/admin/health`, `/admin/users`, `/admin/subscriptions`, `/admin/spend`, `/admin/settings`, `/admin/audit-log`, and **`/admin/sales-agent`** (added 2026-08-13, see §2) | `apps/web/src/app/admin/*`, `apps/api/app/routers/admin.py` |
| Agents already in the product | 22 configured `AgentConfig` keys shown on `/dashboard/agents`; 9 have an editable OpenRouter model picker (Resume Tailoring, Cover Letter, Interview Prep, Company Research, **Recruiter Outreach**, **Email Agent**, Scheduling, Sentiment Analysis, Reference); the rest are deterministic (no LLM) or fixed | Live UI walkthrough, 2026-08-13 |
| AI provider wiring | Every LLM-backed agent bills through OpenRouter by default (`AETHER_LLM_MODE=auto`); a **separate, deployment-wide Anthropic credential** exists (`ProviderCredential('anthropic')`) supporting two modes — a Console API key (`sk-ant-api…`, bills Anthropic API credits) or a Claude Code OAuth token (`sk-ant-oat01-…`, bills against the operator's Claude Pro/Max subscription quota). **The operator's own Claude Code OAuth token is already configured and live in production** — no new credential needed for this build. Anthropic models never route through OpenRouter and vice versa. | `README.md` §AI Agents, §Production Status; `apps/api/app/services/anthropic_oauth.py`; live UI confirms per-agent "Configure Anthropic Claude" modal with API-key/OAuth-token toggle |
| Existing scheduled-job pattern | `aether-discovery.timer` (systemd timer, every 30 minutes) triggers `scout`/`fitScorer` via a scoped `X-Aether-System-Run` shared-secret header (`AETHER_SYSTEM_RUN_SECRET`), constant-time-compared, allowlisted to exactly those two agent keys (`_SYSTEM_RUN_EXEMPT_AGENTS`) | `apps/api/app/routers/agents.py` |
| Existing email integration | `/dashboard/email` already supports multi-Gmail-inbox connection (per-account OAuth tokens, `prompt=select_account`) feeding the existing `emailAgent` (Gmail triage + draft-and-approve) | `README.md` |
| Existing external growth engine (to be superseded) | A separate, non-codebase automation (Perplexity Computer scheduled task, cron id `6592806d`, 6x/day) currently does a coarser version of this job against Gmail + Google Sheets/Docs. It is documented at `docs/growth/README.md`. **This build should give the product a real in-app replacement; once verified, retire the external cron per §10 rather than running both against the same leads.** | `docs/growth/README.md`, this conversation |
| Admin credentials | Not currently working — a live login attempt with owner-provided admin credentials returned `401 Invalid email or password` in production on 2026-08-13. The implementing agent should not assume any specific admin credential is valid; resolve this via the product owner directly (`docs/subscription/admin-guide.md`) before relying on admin-authenticated E2E tests. | Live browser test, 2026-08-13 |

---

## 2. What Already Exists — Extend, Don't Duplicate

`apps/web/src/app/admin/sales-agent/page.tsx` (merged to `main`, commit `93af5d0`, **not yet deployed to production** — see §11) is a first pass: it re-projects existing `/api/admin/users` data into signup/paid-conversion/estimated-MRR cards and links out to the external Sheet/Docs. It has **zero backend logic of its own**.

This build brief supersedes that page with a real feature. Reuse its layout conventions (`AdminPageHeader`, `AdminShell` nav, Tailwind classes matching `/admin/subscriptions`) but replace its content with the real campaign/lead/outreach UI specified below. Add the nav entry once (it already exists in `apps/web/src/components/admin/admin-shell.tsx` — don't duplicate).

---

## 3. Mission Statement

Build a **Sales Agent** that runs inside Aether's own backend/admin portal — not as an external automation — whose sole objective is: **create marketing campaigns, identify and qualify real leads, follow up on them, convert free signups to paid subscribers, and grow signups + MRR month over month**, operating fully autonomously against the connected mailbox and existing Aether data, with every send passing through the compliance gates in §6.

---

## 4. Architecture Integration

### 4.1 Data model (new tables, additive lazy DDL — follow the existing `_ensure_billing_tables()` / `_ensure_admin_schema()` pattern exactly: `CREATE TABLE IF NOT EXISTS` behind an advisory lock, called lazily, never a destructive migration)

```
SalesLead
  id              text primary key (cuid via new_id(), matching User.id convention)
  email           text not null
  name            text nullable
  source          text            -- 'inbound_email' | 'existing_user' | 'referral' | 'manual_approved'
  sourceThreadId  text nullable   -- Gmail thread id, when source = inbound_email
  userId          text nullable references "User"(id)  -- set when the lead maps to an existing Aether account
  consentType     text not null   -- 'inbound_signal' | 'existing_relationship' | 'existing_user_lifecycle'
  consentEvidence text not null   -- thread id, or a one-line human-approved justification
  status          text not null default 'new'  -- new | contacted | replied | converted | unsubscribed | bounced
  createdAt       timestamp default now()
  updatedAt       timestamp default now()

SalesCampaign
  id              text primary key
  name            text not null
  type            text not null   -- 'welcome' | 'free_to_paid_nudge' | 'reengagement' | 'demo_response' | 'linkedin_draft'
  templateBody    text not null
  active          boolean default true
  createdAt       timestamp default now()

SalesOutreachLog
  id              text primary key
  leadId          text references "SalesLead"(id)
  campaignId      text references "SalesCampaign"(id)
  channel         text not null   -- 'email' | 'linkedin_draft'
  gmailMessageId  text nullable   -- idempotency key; unique constraint when not null
  gmailThreadId   text nullable
  subject         text nullable
  sentAt          timestamp nullable
  outcome         text nullable   -- 'sent' | 'replied' | 'bounced' | 'unsubscribed' | 'draft_queued'
  createdAt       timestamp default now()

SalesSuppressionList
  email           text primary key
  reason          text not null
  suppressedAt    timestamp default now()
  sourceThreadId  text nullable

-- Unique index on SalesOutreachLog(gmailThreadId) WHERE outcome = 'sent' AND channel = 'email'
-- is the idempotency enforcement point: a DB constraint, not just prompt discipline.
```

`[DECISION NEEDED]`: whether `SalesLead.userId` backfills automatically by email match against `User.email` on insert (recommended — lets the agent join lead activity to real plan/spend/subscription data already in `User`/`Subscription`).

### 4.2 Backend

- New module: `apps/api/app/agents/sales_agent.py` (mirrors the structure of the existing 8 runtime agents — `apps/api/app/routers/agents.py` for the orchestration pattern, `_record_run`/`AgentRun` for audit logging of every run this agent makes, same billing-audit-trail discipline).
- New agent key `salesAgent` added to the `AgentConfig` table (22 → 23 keys), wired as an **LLM-backed, REASONING-tier, user-overridable** agent — it should appear on `/dashboard/agents` (admin-only visibility, see §4.4) with the same per-agent model picker every other REASONING-tier agent has. Default model resolution: **the deployment's already-configured Anthropic credential** (Claude Opus/Sonnet, whichever the live Anthropic model list resolves to as the current best reasoning-tier model at deploy time — do not hardcode a specific version string like "Opus 4.8"; resolve dynamically the same way `resolve_provider`/the OpenRouter catalog picker already does, so a stale hardcoded id never causes an honest-422 failure down the line).
- New router: `apps/api/app/routers/sales_agent.py`, mounted at `/admin/sales-agent` (public contract `/api/admin/sales-agent/...`), **every route depends on `AdminUser`** exactly like `apps/api/app/routers/admin.py` — no separate auth mechanism, no static-token side door for the UI-facing routes.
  - `GET /api/admin/sales-agent/overview` — signups, paid conversions, MRR (real, computed from `User`/`Subscription`, not the floor-estimate the placeholder page uses today — join `Subscription.billingInterval` so annual plans are converted to a true monthly-equivalent instead of double-counted at full monthly price)
  - `GET /api/admin/sales-agent/leads` — paginated `SalesLead` list with filters (status, source, consentType)
  - `GET /api/admin/sales-agent/campaigns` — `SalesCampaign` CRUD
  - `POST /api/admin/sales-agent/campaigns` — create/edit a campaign template (admin can hand-edit copy without redeploying)
  - `GET /api/admin/sales-agent/outreach-log` — paginated `SalesOutreachLog`, filterable by date/outcome
  - `POST /api/admin/sales-agent/run-now` — manual trigger for the same job the scheduler runs (useful for admin-triggered demo/testing, still fully audited)
  - `GET /api/admin/sales-agent/health` — last run time, run count today, error state (feeds a health widget, mirrors `admin_repo.health_overview()`'s `_cron_status()` pattern for `aether-discovery.timer`)
- Scheduling: **do not build a new external scheduler.** Follow the exact `aether-discovery.timer` pattern already in `deploy/`: a new `aether-sales-agent.timer` + `.service` pair (systemd, `OnCalendar` — recommend every 30-60 minutes, matching the existing discovery cadence, which is far tighter than the external engine's current 6x/day and gets closer to the reply-latency SLA in §8) invoking a oneshot script that calls the sales-agent job function directly (in-process, not over HTTP with a shared-secret header — this job runs as the platform, not as a simulated user, so it doesn't need the `X-Aether-System-Run` exemption pattern at all; it should call the agent's Python entrypoint directly from a small CLI script, same shape as `scripts/discovery_cron.sh`).
- Gmail access: reuse the **existing** multi-Gmail-inbox OAuth infrastructure in `apps/api` (the same one powering `/dashboard/email`) rather than inventing a second Gmail integration. The admin connects the sending account (e.g., the founder's own address) through the existing "Connect Gmail" flow, scoped for sales-agent use via a flag on that stored credential (e.g., `GmailAccount.usedForSalesAgent boolean`) — `[DECISION NEEDED]`: confirm the existing Gmail credential schema supports a per-account role flag, or add one additively.

### 4.3 Frontend (`/admin/sales-agent`)

Replace the placeholder page's body with:
1. **Overview cards** (reuse the existing layout) — real signups, paid conversions, accurate MRR (from `/overview`), reply rate, active suppression count.
2. **Campaigns tab** — list/create/edit `SalesCampaign` templates in-app (textarea + preview, no redeploy needed to change copy).
3. **Leads tab** — table of `SalesLead` (status, source, consent type, last contact) — mirrors `/admin/subscriptions`' table conventions exactly.
4. **Outreach log tab** — every send/draft with outcome, for auditability (this is the in-app equivalent of the external engine's `Email_Log` sheet).
5. **LinkedIn drafts tab** — generated draft posts for the founder to copy/post manually; never a "Post" button that touches LinkedIn.
6. **Health widget** — last run, next scheduled run, error state (red banner if the timer hasn't fired in > 2x its interval — this is the in-app fix for the exact silent-failure mode that hit the external engine on 2026-08-10–13, where a credit/billing issue paused it for 3 days with nobody noticing).

### 4.4 Visibility

Per the product owner's explicit requirement, this entire feature (page + nav entry + API routes) must be visible **only** to admin accounts (`sarkar.vikram@gmail.com` and any account with `isAdmin=true`), enforced the same way every other `/admin/*` page already is — client-side `AdminGuard` for UX, `AdminUser` server dependency as the actual authority. Do not add a new admin-detection mechanism.

---

## 5. Explicit Feature List

1. **Inbound signal detection** — poll the connected Gmail account(s) for new messages matching signup/demo-request/product-question/reply/unsubscribe patterns since the last run (persist a watermark — last-processed message id/timestamp — instead of re-scanning the full mailbox every run).
2. **Lead creation** — insert a `SalesLead` row for every genuine new signal, with real `consentType`/`consentEvidence` (never fabricated).
3. **Automated reply/follow-up** — pick the closest matching `SalesCampaign` template, personalize genuinely from the actual inbound message content, append the compliance footer (§6), send via the connected Gmail account, log to `SalesOutreachLog` with the returned `gmailMessageId` as the idempotency key.
4. **Free-to-paid nudges** — join against `User`/`Subscription`/`AgentRun` to find Free-tier users near their 5-run monthly cap or with high engagement, and send an upgrade nudge (rate-limited — see §6 — and only ever once per user per billing cycle, enforced by a DB check, not a prompt instruction).
5. **Re-engagement** — Free/paid users with no `AgentRun` in N days get a check-in email (same rate-limit discipline).
6. **Demo-request handling** — detect an inbound demo ask, reply with a fast, concrete next step (free-signup link, or an offer to run their résumé through Aether live) within the reply-latency SLA in §8.
7. **Campaign/copy management** — admin can create, edit, and disable `SalesCampaign` templates from the UI without a deploy.
8. **LinkedIn content generation** — draft-only posts (founder-story, differentiator, feature explainer, objection-handling, pricing/CTA) queued for manual posting; never auto-posted.
9. **Suppression enforcement** — any inbound message containing "unsubscribe" (case-insensitive) immediately and permanently suppresses that address; a DB-level check (not just an LLM instruction) blocks any subsequent send attempt to a suppressed address.
10. **Idempotency enforcement** — a DB unique constraint (not just prompt discipline) prevents two runs from double-emailing the same thread.
11. **Reporting** — daily digest email to the founder (leads followed up, sends, replies, LinkedIn drafts queued, real metrics, honest "not observable" markers for anything not truly measurable) and the in-app overview/health widgets.
12. **Model routing** — LLM calls for copy generation/personalization run through the existing per-agent model config (`AgentConfig` for `salesAgent`), targeting the already-configured Anthropic credential by default, honoring the "no silent substitution on failure" rule (`ADR-ML-3`) the rest of the product already follows — an LLM call failure should log an honest error, not fall back to fabricated copy.

---

## 6. Compliance & Safety — Hard Gates (implement in code, not just in the system prompt)

| Gate | Enforcement point | Failure mode if skipped |
|---|---|---|
| Compliance footer on every commercial email | A server-side function that appends the footer to the email body before `send_email` is ever called — the LLM-generated body should never itself be responsible for including it | A model that "forgets" the footer breaches the Spam Act |
| Suppression check | `SalesSuppressionList` row existence check, DB query, before every send — not a prompt reminder | Emailing someone who opted out |
| Idempotency | DB unique constraint on `(gmailThreadId)` where `outcome='sent'` — a second send attempt on the same thread should hit a constraint violation, not rely on the model remembering it already replied | Double-emailing a real person from a retried/overlapping run |
| Recipient provenance | `SalesLead.consentType`/`consentEvidence` required, NOT NULL, populated only from a real Gmail message id or a human-approved manual entry — no code path should be able to construct a `SalesLead` from a free-text/guessed email string | Cold-emailing scraped/invented addresses |
| Rate limiting per recipient | A user gets at most one nudge/re-engagement email per billing cycle — DB check, not just "the agent decided not to" | Spamming an existing paying customer |
| No LinkedIn automation | Simply: never implement a LinkedIn API client or LinkedIn browser-automation call anywhere in this feature | Account ban risk under LinkedIn's ToS |
| Honest metrics | Every number shown in the UI/digest traces to a real query; anything not computable says so explicitly (e.g., "not observable" rather than 0 or a guess) | Fabricated growth numbers |

---

## 7. Model / Provider Routing

- Default: the existing deployment-wide Anthropic credential (already configured and live per §1) — resolve the current best available reasoning-tier Claude model (Opus- or Sonnet-class) from whatever the account's live model list actually offers at build/deploy time. **Do not hardcode "Opus 4.8" or "Sonnet 5 1M" as literal model id strings** — those may not match real, currently-existing Anthropic model identifiers, and the codebase's own `PUT /api/agents/config/{agentKey}` already honestly 422s an id that isn't in the live catalog rather than silently substituting. Wire the picker to whatever's real at build time; treat the user's model preference as "use our best available Anthropic reasoning model, on our existing subscription credential" rather than a literal, unverified string.
- Fallback: OpenRouter, same per-agent picker every other REASONING-tier agent already has, in case the Anthropic credential needs rotation/renewal.
- Billing: OAuth-token mode bills against the Claude Pro/Max subscription quota already in use (per README, this mode is live) — confirm with the product owner that this quota has headroom for a 30-60-minute-cadence agent generating outreach copy + LinkedIn drafts before assuming it's cost-free.

---

## 8. SLAs and Growth Targets

Split deliberately into two categories — conflating them is how you end up either overpromising or building perverse incentives into the code.

### 8.1 Operational SLAs (binary, enforceable, the agent must always meet these or surface why it didn't)

- Reply to a genuine inbound demo request or product question within one scheduler cycle (target: 30-60 minutes, bounded by the timer cadence in §4.2).
- 100% of commercial sends carry the compliance footer — zero tolerance, DB-enforced per §6.
- 0 sends to a suppressed address — zero tolerance, DB-enforced.
- 0 duplicate sends to the same thread — zero tolerance, DB-enforced.
- Daily digest sent every single day, even on a day with zero activity (silence is exactly what let the external engine's 3-day credit-exhaustion outage go unnoticed on 2026-08-10 — the health widget in §4.3 exists to prevent a repeat).
- 0 fabricated metrics — every number in the digest/UI is either real or explicitly marked not observable.

### 8.2 Growth targets (goals to work toward and report against — NOT something the code can force to happen, and the agent must never misreport progress to look like it's hitting them)

`[DECISION NEEDED — confirm with product owner before treating as committed numbers; these are directional starting points, not derived from any real baseline data since the product has ~0 external signups as of this writing]`:

- **Month 1** — instrument everything (UTM parameters on every campaign link, a way to attribute a signup/conversion back to a specific `SalesCampaign`), establish a true baseline, target ≥10 net-new free signups and ≥1 paid conversion attributable to agent activity.
- **Month 2-3** — 15-25% month-over-month growth in attributable signups; measurable lift in free→paid conversion rate vs. the Month-1 baseline.
- **Ongoing** — monthly report: actual vs. target, with honest root-cause commentary when a target is missed (e.g., "traffic was flat because the founder didn't post the queued LinkedIn drafts this month" is a valid, honest finding — the agent should say exactly that rather than obscure it).
- The agent's job is to **maximize its controllable inputs** (reply speed, personalization quality, campaign coverage, LinkedIn draft cadence) — it is explicitly not to fabricate or force a growth number it does not causally control alone.

---

## 9. Testing / Verification Gates (do not skip — mirrors this repo's own QA culture)

For every implementation unit:
- Unit tests for the DB layer (idempotency constraint actually rejects a duplicate; suppression check actually blocks a send; consent fields are actually required).
- Integration test: a simulated inbound Gmail message → lead created → reply drafted → footer present → sent → logged, end to end.
- A dry-run/shadow mode flag (`AETHER_SALES_AGENT_DRY_RUN=true`) that runs the full pipeline except the final `send_email` call, logging what *would* have been sent — use this for the first real-world verification pass before flipping to live sends.
- Before declaring this "production-ready," get an **independent adversarial review** (a second agent or a fresh pass by the same agent with an explicitly skeptical framing) to check compliance-gate coverage, exactly like the review already run against the external engine on 2026-08-10 (`docs/growth/ADVERSARIAL-REVIEW-2026-08-10.md`) — use that document's item list (A-J) as a checklist template, adapted to this implementation.
- Manual production verification after deploy: a real (or disposable) inbound test email → confirm a reply arrives with the footer intact within the SLA window; confirm the outreach log and overview numbers update; confirm the health widget shows a recent run.

---

## 10. Rollout Plan

1. Build behind `AETHER_SALES_AGENT_ENABLED` flag (default off), migrations additive-only.
2. Deploy with the flag off; run the systemd timer in **dry-run mode** for at least 48 hours; review the shadow log for quality and compliance-gate correctness.
3. Flip dry-run off for a **narrow scope first**: demo-request replies and inbound-signal replies only (the highest-consent, lowest-risk category). Verify a full day's real activity manually.
4. Expand to free-to-paid nudges and re-engagement once the narrow scope has run clean for a week.
5. Once this in-app agent is verified live and stable, **retire the external Perplexity-cron growth engine** (delete cron `6592806d` and its weekly health check `3473b50d`, and stop treating `docs/growth/*` as the system of record) — running both against the same Gmail inbox risks double-replying to the same lead from two independent systems. Migrate the `Suppression_List`/`Prospects` data from the external Google Sheet into `SalesSuppressionList`/`SalesLead` first so no existing opt-outs are lost.

---

## 11. Known Open Item — Deployment Access

As of 2026-08-15, code merged to `main` on GitHub is **not automatically live** on `5cb5f0620.abacusai.cloud` — this repo's deploy is manual (`git pull && pnpm build && sudo systemctl restart aether-api aether-web aether-worker`, per `docs/delivery/DEPLOYMENT-RUNBOOK.md`), and no CI/CD auto-deploy exists. Whoever executes this build (human or agent) needs either direct VM access (SSH to the Hostinger VPS or the Abacus.ai box) or a person with that access to run the deploy step — this is infrastructure the implementing agent should confirm access to before Phase 3 of the rollout plan, not assume.

---

## 12. Evidence Log (for traceability — everything in §1 was verified live, not assumed)

- Live pricing/checkout verification: real signup (`melbvicduque+aethertest@gmail.com`) → `/pricing` → "Subscribe to Starter" → real `checkout.stripe.com` session, `cs_live_...`, $13.93 USD (~$19 AUD) line item shown — 2026-08-13.
- Live admin-panel walkthrough (22 agents, 6 provider cards, per-agent OpenRouter picker, Anthropic dual-credential modal) — 2026-08-13.
- Live admin-login attempt with owner-provided credential → `401 Invalid email or password` — 2026-08-13.
- `/admin/sales-agent` placeholder page merged to `main` (`93af5d0`) → confirmed **404 on production** (not yet deployed) — 2026-08-13.
- External growth-engine adversarial review, full findings and fixes: `docs/growth/ADVERSARIAL-REVIEW-2026-08-10.md`.

---

## 13. Perplexity Computer's Opinions / Recommendations (explicitly requested by the product owner)

1. **The single highest-leverage fix is not this agent — it's traffic.** The external engine's own logs (15+ runs, 2026-08-10 through 08-15) show zero genuine inbound leads found in Gmail across every run. An extremely well-built in-app sales agent still has nothing to work on until real visitors reach the site. Ship this, but don't expect it alone to move MRR — pair it with the founder actually posting the queued LinkedIn drafts and fixing top-of-funnel distribution.
2. **Don't hardcode the growth numbers in §8.2 as commitments.** Treat them as a starting hypothesis to test and revise monthly once real data exists — the product currently has no baseline to derive them from.
3. **Reuse, don't rebuild, the existing Gmail/agent/model-picker infrastructure.** This product already has 90% of the plumbing (multi-Gmail OAuth, per-agent model config, `AgentConfig`/`AgentRun` audit pattern, `aether-discovery.timer` scheduling pattern) — the risk in this build is duplicating that infrastructure instead of extending it, which is exactly the kind of thing this repo's own delivery culture (see `docs/delivery/`) has flagged as technical debt before.
4. **Resolve deployment access before Phase 3 of rollout.** A feature that only exists on `main` and never reaches production doesn't help revenue — this was the exact gap hit building the placeholder page.
5. **Get the admin login working before relying on it for anything.** It 401s in production today; don't let this build silently assume a credential that doesn't work.
6. **Consider whether "full autonomy, no approval gate" for this one agent creates a governance inconsistency worth documenting explicitly** — the rest of Aether's philosophy is "human approves every outbound action." This build brief carries the product owner's explicit, informed exception for sales-agent sends only (§0.5) — keep that exception narrow and don't let it bleed into other agents' behavior as a side effect of shared code paths.
