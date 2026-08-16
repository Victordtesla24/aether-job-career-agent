# Native Sales AI Agent — Delivery Document

**Delivered:** 2026-08-14 (UTC)
**Status at delivery:** deployed in **shadow mode** (`AETHER_SALES_AGENT_ENABLED=true`, `AETHER_SALES_AGENT_DRY_RUN=true`) — the agent runs the full pipeline and logs everything it *would* send, but sends no email.
**Replaces (eventually):** the external Perplexity-Computer growth engine (`docs/growth/`, cron id `6592806d`, 6×/day + weekly review cron `3473b50d`) reviewed adversarially in `docs/growth/ADVERSARIAL-REVIEW-2026-08-10.md`.

---

## 1. What was built

A native, admin-only sales/growth agent living inside this repo and this VM, with the same evidence standards as the rest of Aether.

| Layer | File(s) | Summary |
|---|---|---|
| Repository / schema | `apps/api/app/repositories/sales.py` | 4 new tables (`SalesLead`, `SalesCampaign`, `SalesOutreachLog`, `SalesSuppression`) created via lazy DDL under advisory lock `7420240725`; additive `GmailAccount.usedForSalesAgent` flag. Consent is enforced at the repository layer (`ConsentViolationError`), duplicates at the database layer (`DuplicateSendError` on partial unique indexes over `gmailThreadId`/`gmailMessageId`). |
| Agent | `apps/api/app/agents/sales_agent.py` | Inbound Gmail polling (watermark-based), unsubscribe handling, interest → lead → campaign reply pipeline, lifecycle nudges (free-plan cap approach, re-engagement), LinkedIn **draft-only** queue, once-daily admin digest, honest AgentRun bookkeeping. |
| API | `apps/api/app/routers/sales_agent.py`, mounted in `app/main.py` at `/admin/sales-agent` | 12 admin-only routes (overview, leads, campaigns CRUD, outreach log, suppressions, run-now, health, config/model override, sending-accounts toggle). Every route requires `AdminUser`. |
| Scheduler | `deploy/aether-sales-agent.service` + `.timer`, `scripts/sales_agent_cron.py` | systemd oneshot every 30 min (`*-*-* *:15/30`, offset from discovery's :00/:30), `Persistent=true`, in-repo units symlinked into `/etc/systemd/system/` per repo convention. |
| Admin UI | `apps/web/src/app/admin/sales-agent/page.tsx`, `apps/web/src/lib/api/salesAgent.ts` | Full console: health strip + red stale alarm, shadow-mode/LIVE badge, Run-now, sending-account toggles, overview stats, campaign template editing, leads / outreach-log tables, LinkedIn drafts with copy-only buttons. |
| Gmail service | `apps/api/app/services/gmail_service.py` | Additive only: `threadId` now included in `list_message_headers` / `get_message_bodies` dicts. |
| Tests | `apps/api/tests/test_sales_agent.py` | 28 tests: consent gates, DB idempotency, suppression (case-insensitive), footer idempotency, disabled honest no-op, dry-run pipeline, unsubscribe → suppress, live-mode sends-exactly-once, lifecycle rate limit, 401/403/200 route matrix, campaign CRUD. |

## 2. Decisions taken (the [DECISION NEEDED] items)

1. **`SalesLead.userId` backfill — YES.** When a lead's email matches an existing user, the lead is linked automatically at creation. Additive; nothing existing reads the column.
2. **Sending-account selection — additive `GmailAccount.usedForSalesAgent` flag** (default false), toggled per-account from the admin console. No account is used for sales until an admin explicitly opts it in.
3. **§8.2 growth targets — documentation-only.** No code asserts or fabricates growth numbers. Overview metrics are computed from real DB rows (see §4-H below).
4. **Lowest-risk additive options everywhere:** lazy DDL instead of migrations, new router instead of edits to existing ones, new columns with defaults, no changes to existing approval gates.

**Deviation — admin-only visibility:** the agent is *not* added to the shared user-facing dashboard `AGENT_CATALOG` (that catalog drives end-user surfaces; adding an internal sales agent there risked exposing it to non-admins and touching heavily-shared code). Instead it is visible via the dedicated `/admin/sales-agent` console and an `AgentConfig` row (`agentKey='salesAgent'`) created idempotently for model override/enable state. This satisfies "admin-only visibility" with less blast radius than the brief's literal suggestion.

## 3. Compliance model (Spam Act / ACMA)

- **Consent ledger:** every `SalesLead` row records `consentType` ∈ {`inbound_signal`, `existing_relationship`, `existing_user_lifecycle`} + free-text `consentEvidence` (e.g. the real Gmail message id of the inbound email, or "existing Aether account &lt;id&gt;"). `create_lead` **raises** on missing/unknown consent — an unconsented lead cannot exist.
- **No invented addresses:** leads are created only from (a) a verified inbound Gmail message, or (b) an existing user row. The LLM never chooses a `to` address; it only personalizes body text for an already-consented lead.
- **Compliance footer:** a concrete footer (sender identity + "Reply 'unsubscribe'") is appended **server-side at send time** (`append_compliance_footer`, idempotent). Templates never contain a `{compliance_footer}` placeholder; the admin UI states the footer is appended by the server.
- **Suppression:** unsubscribe replies permanently suppress the address (case-insensitive), flip the lead to `unsubscribed`, and are honoured *synchronously in the same run* — well inside ACMA's five-business-day SLA. Suppression is checked before every send path (inbound reply, lifecycle, digest excluded — digest goes only to the admin).
- **Protected recipients:** admin/login/cron emails and the sales sending accounts themselves can never become lifecycle targets.

## 4. Adversarial review items A–J vs this implementation

| Item (review grade) | This implementation |
|---|---|
| **A. Auditable task definition (PARTIAL)** | Fixed. Everything is versioned in this repo: agent code, router, systemd units (`deploy/aether-sales-agent.*`), cron entrypoint. `git log` is the audit trail; `systemctl list-timers` shows the schedule; `GET /admin/sales-agent/health` exposes last-run state. No opaque external scheduler. |
| **B. Spam Act compliance (FAIL)** | Fixed by construction — see §3. Consent ledger, immutable suppression table, concrete footer enforced at send time, synchronous unsubscribe handling. |
| **C. Invented/harvested addresses (FAIL)** | Fixed by construction. `create_lead` requires consent type + evidence; sources restricted to `{inbound_email, existing_user, referral, manual_approved}`; the LLM is never given the ability to pick recipients. |
| **D. LinkedIn draft-only (PARTIAL)** | Enforced in code: the LinkedIn path can only write `draft_queued` outreach rows, at most `AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK` per rolling 7 days; the slot is claimed in the database (advisory-locked `reserved` row) BEFORE the model is called and given back if the draft fails, so two overlapping runs cannot both spend the same slot. There is no LinkedIn credential, connector, or posting code anywhere in the repo. UI offers copy-to-clipboard only. |
| **E. Self-learning loop (FAIL)** | Honest scope reduction: no fake "learning" layer was built. Every run is an `AgentRun` row (`agentName='salesAgent'`) with structured output (counts, model, errors) — a real run log first; experimentation can be layered on measured outcomes later. |
| **F. Daily executive summary (FAIL)** | Implemented: once-daily digest (UTC-gated via `AdminSetting salesAgent.lastDigestDate`) with real overview numbers, sent to the admin email in live mode, logged as `dry_run` in shadow mode. |
| **G. Idempotency / duplicate sends (FAIL)** | Fixed at the **database** layer: partial unique indexes on `gmailThreadId` (WHERE outcome='sent') and `gmailMessageId`; `record_outreach` converts `UniqueViolation` into `DuplicateSendError`; processed inbound message ids are checked before handling; per-account watermarks prevent rescans. Covered by tests. |
| **H. Data honesty (PARTIAL)** | All overview numbers trace to real queries (MRR joins `Plan` and divides annual billing by 12; statuses restricted to active/trialing/past_due on non-free plans). Reply rate reports **`null` / "not observable"** when there is no basis to compute it — never a guess. |
| **I. Cron mechanics (PARTIAL)** | Native systemd timer: 30-min cadence, `Persistent=true`, `RandomizedDelaySec=60`, offset from the discovery timer. Health endpoint marks the scheduler `stale` after 60 min without a run; the admin UI shows a red alarm banner. |
| **J. Real-world efficacy (FAIL)** | Honestly out of this agent's scope: the review's blocker is the **product funnel** (no public prices/checkout). This agent does not claim daily paid subscribers; it reports observable counts only. Funnel fixes remain a separate product task. |

## 5. Rollout state and go-live switch

Current `.env` flags (values, not secrets):

```
AETHER_SALES_AGENT_ENABLED=true
AETHER_SALES_AGENT_DRY_RUN=true    # shadow mode
```

Optional tuning (defaults shown — unset is fine):

```
AETHER_SALES_BACKLOG_DAYS=90                 # how far back a NEVER-SEEN mailbox is scanned
AETHER_SALES_TIE_MAX_RESULTS=500             # messages drained from ONE tied whole second per run
AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK=2      # LinkedIn DRAFT budget per rolling 7 days (0 = off)
AETHER_OPERATOR_TZ=Australia/Sydney          # timezone used in the run's plain-English explanation
```

- **Backlog:** an account with no stored watermark is scanned `AETHER_SALES_BACKLOG_DAYS`
  back, 50 messages per run, walking older across successive runs until caught up. The
  watermark only ever moves past mail that was really scanned, and each run reports
  `accounts[].backlogRemaining` so "caught up" is a fact, not an assumption. Previously a
  reconnected mailbox looked back only 24 hours and then jumped its watermark to *now*,
  so every pre-connection message was invisible permanently.
- **Same-second ties:** Gmail timestamps have whole-second resolution while the result cap
  is per request, so one second can hold more messages than a page returns. The walk moves
  below a second only after fetching that second in full (`AETHER_SALES_TIE_MAX_RESULTS`,
  default 500 = Gmail's own list cap), which is what stops it from either stepping over
  unscanned mail or wedging on a tie it cannot get past. More than the cap in a single
  second is reported on the run (`accounts[].tieOverflow` plus an error line naming the
  timestamp) — never silently dropped.
- **Gmail boundary semantics are never assumed.** Google documents `after:`/`before:` by
  example and never states whether either bound is inclusive, so every window query the
  walk sends is widened by one second at each end (`after:{lo-1} before:{hi+1}` — a
  superset of `[lo, hi]` under all four readings, and never the empty range that
  `after:X before:X` is under three of them) and the exact window is enforced in Python.
  The boundary drain additionally *verifies* itself: the page already proves at least one
  message sits at that second, so a drain that does not return those known messages has
  demonstrably not reached it. That case holds the window and is disclosed as
  `accounts[].tieDrainUnverified` plus an error line — it is never read as "nothing more
  is there", which is how a wrong boundary assumption would otherwise turn into silent
  mail loss that looks like clean coverage in the run result.
- **Classification:** the curated phrase lists are a fast path and remain authoritative —
  an inbound *unsubscribe* is decided by phrases alone and never consults a model. Only a
  message the phrases do not classify costs one structured LLM call (so a busy backlog run
  can make up to 50 classification calls per account); an unavailable model degrades to the
  phrase verdict and is counted as `classifierDegraded`, never guessed.

- The agent code reads the flags from the process environment at **run time** — but the two entrypoints load `.env` differently:
  - **Timer job** (`scripts/sales_agent_cron.py`): reloads `.env` on every tick → picks up a flag flip on the next 30-min run with **no restart**.
  - **API run-now path**: `aether-api` exports `.env` once at process start (`start-api.sh`), so after flipping a flag, run `sudo systemctl restart aether-api` for the *Run now* button to reflect it.
- **Go-live is one line:** set `AETHER_SALES_AGENT_DRY_RUN=false` in `/home/ubuntu/github_repos/aether-job-career-agent/.env` (then restart `aether-api` if you want run-now to go live too; the timer goes live on its own).
- Even live, the agent sends nothing until an admin flags at least one Gmail account for sales in the console (currently **zero** accounts are flagged → runs are honest no-ops with `noSendingAccount=true`).

## 6. Remaining human steps

1. Flag a sending Gmail account via `/admin/sales-agent` → Sending accounts toggle.
2. Review the shadow-mode outreach log for ~48 h (everything the agent *would* send is logged with full body, outcome `dry_run`).
3. Flip `AETHER_SALES_AGENT_DRY_RUN=false` when satisfied.
4. Post LinkedIn drafts manually (copy from the console; the agent will never post).
5. **Retire the external Perplexity crons** `6592806d` (6×/day engine) and `3473b50d` (weekly review) — they live in the Perplexity Computer account and cannot be disabled from this VM. Until retired, both engines coexist; the external one should be stopped before going live here to avoid duplicate outreach.
6. Google Sheet CRM migration: **skipped** — no Google Sheets service-account credentials exist on this VM (checked `.env` and `~/.config`); the native DB tables are the system of record going forward. Historic Sheet rows can be imported later if credentials are provided.

## 7. Honest limitations

- Reply detection is heuristic (phrase lists) — ambiguous inbound mail is left alone rather than guessed at.
- Reply rate is reported as "not observable" until real sends produce measurable threads.
- LLM personalization falls back to the raw template on any LLM failure (logged), so copy quality can vary; failures are never hidden.
- The digest is best-effort once per day; if the timer is down, health goes `stale` and the UI alarms, but no out-of-band alert is sent.
- No A/B testing / learning loop yet (deliberate — see §4-E).


## 8. Increment — 2026-08-15: Aether Career DS rebrand, live deploy, first real-LLM generation

**Commits:** `95bae7de` (rebrand: emails, documents and `/admin/sales-agent` console retokened to the
Aether Career Design System — near-black `#08080A` surfaces, parchment ink `#F5F1E8`, 96° gilt gradient,
AB Sans/AB Marquee fonts, logo `/brand/aether-mark.png`; `ab-logo.png` removed) and `dd65d889`
(tests: pipeline tests now inject an always-unavailable LLM stub so the template-fallback assertions no
longer depend on "no fixtures on disk" — an untracked captured `sales_reply.json` fixture had broken that
premise). Both pushed to `origin/main` and deployed.

**Test gate:** `tests/test_sales_agent.py` — **45/45 passed** (48.4 s) under `scripts/run-tests.sh`
against the real `aether_test` schema, after one genuine fix (the stub above). No compliance gate was
weakened: consent provenance, suppression, idempotency, server-side footer, admin auth (401/403) all
still asserted.

**Deploy:** manual per runbook §5 (auto-deploy declines to pull while concurrent agents' foreign WIP sits
in the shared tree — tree was already at `origin/main` HEAD so no pull was needed). `pnpm build`
(BUILD_ID `KWhD279cIWHyBGqhflAQK`), `verify-web-build.sh` **PASS**, api/web/worker restarted back-to-back
per §0.3. Verified live: api health 200, `/` 200, `/brand/aether-mark.png` 200,
`/fonts/ab/AB-Sans-Regular.ttf` 200, served CSS bundle contains `.aether-ds-scope` + AB Sans
`@font-face`, zero "Application error" in rendered HTML.

**First real-LLM generation (production, authed `POST /generate`):** model **`claude-opus-4-8`**
(source `anthropic_flagship`), no fallback needed, zero errors, audited as AgentRun
`c39e532958693c61367bad515`. Created **inactive, awaiting human activation**:
- `Free→Starter Nudge v2 (agent-generated)` (`c075d4e8b988ec3268de7d3da`)
- `Welcome Reply v2 (agent-generated)` (`c207cbbe9c60d12812c81b21b`)
- 3 LinkedIn drafts (`LinkedIn draft (agent-generated) — marketing refresh 1–3`, outcome `draft_queued`)

**Verification (authed API, numbers from live responses):** campaigns 7 (5 prior active + 2 new
inactive); branded preview of the new nudge renders Aether HTML (`#08080A`, `aether-mark.png`, `A$19`,
unsubscribe footer, no legacy branding); LinkedIn drafts 20 total (17 prior + 3 new); suppressions 12;
leads 5 (both grew since import — the live timer has been processing real inbound mail: 16 `unsubscribed`
outcomes honored); health `ok`, fresh `lastRunAt`, timer active (30-min cadence); anonymous request →
401 (non-admin 403 covered by the test suite).

**Live-mode safety (state as found, per user order):** `AETHER_SALES_AGENT_DRY_RUN=false` (user-ordered;
not reverted). **Two** Gmail accounts are flagged `usedForSalesAgent` (`sarkar.vikram@gmail.com`,
`melbvicduque@gmail.com`) — flagged before this increment, not by it — so live sends are now *possible*
on timer ticks. As of this verification **zero** `sent` outcomes exist in `SalesOutreachLog` (41
`dry_run`, 20 `draft_queued`, 16 `unsubscribed`). Because sending is armed, the manual `run-now` was
deliberately **skipped** this increment; the timer already provides fresh runs.

**Honest gaps:** LinkedIn drafts total is 20 vs the "16 imported" figure in the task brief (actual prior
count was 17); suppressions/leads (12/5) exceed the imported 2/2 because the live agent kept working
between increments; non-admin 403 verified only via the test suite (no non-admin credential exercised
against prod).
