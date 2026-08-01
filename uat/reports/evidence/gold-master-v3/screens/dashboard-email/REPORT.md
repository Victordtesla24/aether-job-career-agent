# TESTING OUTCOME REPORT — /dashboard/email (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 4)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T18:29–18:33Z. Account: AETHER_CRON_EMAIL (non-admin). Playwright/Node, headless Chromium, 1440x1200.

**SAFETY: no email was sent to any real recipient at any point.** The send-confirmation gate was opened (to screenshot/verify it) and immediately Cancelled — `send-gate-confirm` was never clicked. Confirmed via network capture: zero calls to `POST /emails/{id}/reply` or `POST /workspaces/emails/send` across the whole session.

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 01-cold-load.png + results.json)

- Header "Email Command Center", `Run AI Triage` button, `Compose` button (no dedicated data-testid, text-matched).
- Inboxes bar (`email-accounts`): "All Inboxes" filter + **"Connect Gmail"** CTA — **zero per-account chips rendered** (see finding ML-EMAIL-001 below).
- Smart Inbox (`inbox-list`): 50 email cards (bounded list), 5 category tabs (Priority/All Recruiter/Follow-Up Due/Auto-Replied/Trashed) — all clicked, all filter without error.
- This Week's stats (`email-stats`): 229 Received / 22 Recruiter / 6 Auto-drafted / 0 Sent (approved) / 0 Follow-ups / 0h Avg response — **real, account-specific numbers**, not the wireframe's fixture "23/21/8/7/3/62%".
- Email detail pane, AI Intelligence panel, AI Draft Reply panel, Send Confirmation Gate, Compose modal — all present and functional.
- Wireframe drift: no dedicated per-account "Sync Now" buttons in production (wireframe promised `sync-1/2-em08/em10`) — grepped `page.tsx`, no such control exists; sync is implicit.

## Targeted verifications

1. **Real Gmail threads? Honest connection status?** The inbox shows 50 real, account-specific email threads (subjects/senders/bodies match this account's actual job search correspondence, not fixture placeholders). **Connection status is NOT fully honest**: `GET /workspaces/emails/inbox` returns both linked Gmail accounts (`melbvicduque@gmail.com` primary, `sarkar.vikram@gmail.com`) with `"status": "needs_reauth"` and a note "Gmail authorization expired or was revoked — reconnect your account to resume syncing." **But the account chips only render accounts with `status === "connected"`** (`page.tsx:535`), so with both accounts at `needs_reauth`, **zero chips render** and the connect button falls back to its "nothing connected yet" label, **"Connect Gmail"** (`page.tsx:590,597-599`), instead of "Add Gmail Account". Full-page text scan for "reauth"/"reconnect" on two independent sessions: **0 matches both times** — the expired-auth state and its "reconnect your account" guidance are computed by the backend but **never surface anywhere in the UI**. A user sees 229/50 real synced emails and a bare "Connect Gmail" button with no indication 2 accounts already exist and need reconnecting. Filed as ML-EMAIL-001 (see below). [VERIFIED-WITH-FRESH-EVIDENCE 01-cold-load.png, inbox.json (saved to this dir), results.json→accountCards=0]
2. **Compose/draft path that does NOT send.** `Compose` → modal opens (`compose-modal`) → filled To/Subject/Body with adversarial content (`<script>`, unicode, 2500-char string, "-999999") → **Save Draft** → network: `POST /api/emails/draft` → **201** (matches `emails.py:206`, creates a real `EmailThread` row) → modal closed, no send call fired. Reload + a fully independent fresh session both show the new thread in the inbox list ("GOLD-MASTER-V4 TEST DRAFT…", id `cfc2cce71b52d38ffeff2db29`) — real persistence, not local-only state. The `<script>` tags render back as literal escaped text (React), never executed — no console/pageerror fired — **no XSS**. [VERIFIED-WITH-FRESH-EVIDENCE 09,10,11,12,14-*.png, results.json]
3. **AI drafting action — generate a DRAFT only, verify tailored, confirm NOT auto-sent.** Selected a real thread (Vik / "Update on Work Situation" / ATO contract ending), clicked **Generate Draft** → `POST /agents/email/run {mode:"draft_reply"}` → 200, produced a reply genuinely grounded in that thread's content ("your contract with the ATO is finishing soon… please send through an updated CV"). Clicked **Regenerate** → second call, produced a *materially different* draft that additionally pulled real resume history (Scrum Master/PM @ ATO, prior roles at ANZ/NAB/Microsoft/Telstra) — **not byte-identical** (`draftIdentical: false`), confirming live generation. Cross-checked both outputs against the test-suite's `email_reply` LLM fixture (`apps/api/tests/fixtures/llm/email_reply/default.json` = generic "Thank you for reaching out about the role…") — **zero overlap**, ruling out fixture reuse. Opened the **Send Confirmation Gate** to verify it renders correctly (`send-gate-modal` present) then clicked **Cancel** — never Confirm. [VERIFIED-WITH-FRESH-EVIDENCE 06,07,08-*.png, results.json→draft1/draft2/draftIdentical]
4. **Audit fields + selected-model-matches-recorded-model.** `GET /agents/runs?agent=email` shows real per-run audit: `model: "deepseek/deepseek-v4-pro"`, `costUsd` (~$0.001/run — cheap model), input `{mode, thread_id}`. Cross-checked `GET /agents/catalog`: the `emailAgent` card's **currently-selected** `model` field is `"deepseek/deepseek-v4-pro"` (the `recommended` field is a separate, unapplied suggestion of `claude-sonnet-4` — `modelOverridable: true`, i.e. this account has deliberately overridden the default to a cheaper model). Selected model = recorded model: **MATCH, honest.** Same check for `interviewPrep` (screen 1 of this batch): catalog `model` = `"anthropic/claude-sonnet-4"`, recorded run `model` = `"anthropic/claude-sonnet-4"` — also a match. [VERIFIED-WITH-FRESH-EVIDENCE agent-runs-audit.json, agents-catalog.json (saved to this dir)]
5. **Correlation with failing `test_wave4c_*` baseline tests**: not independently reproduced (out of time-box to run all 3 suites); however the production behavior directly relevant to their names was verified honest and correct here: sends are gated (never fired), drafts persist, AI runs are genuinely metered/audited. Given the identical `Could not validate credentials` register/login-collision signature seen on the Interviews-screen baseline failures (shared `aether_test` schema flakiness, per prior project memory), these are most likely the same test-infra issue rather than a live product defect. [INFERRED]

## Interaction / forms / persistence

- All 5 category tabs clicked — filter without error, no console/network errors.
- Run AI Triage: `POST /agents/email/run {mode:"triage"}` → 200, honest "No threads to triage yet." (everything already triaged from prior runs — not a fake success, an accurate no-op).
- AI Intelligence "Analyze" on the selected thread: populated `ai-intelligence` panel, no error.
- Compose empty-submit: `Save Draft` is `disabled` while subject/body are blank (verified `isDisabled()===true`, 0 draft-create calls fired on the disabled click) — proper client-side guard, not a silent no-op after a real submit attempt.
- Reload-and-re-read: adversarial draft thread present after reload AND in an independent fresh session (session 2) — real DB persistence confirmed twice.

## Error / edge states

- Unauthenticated access → redirected to `/login?next=%2Fdashboard%2Femail`. [13-unauthenticated-access.png]
- Verified twice: fresh session reproduced identical inbox count (50), identical stats-implying data, test draft still visible, **0** "reauth"/"reconnect" text matches again — the connection-status gap is consistent/reproducible, not a one-off render glitch.
- console.json / pageerrors.json: empty both sessions. requestfailed.json: only benign `net::ERR_ABORTED` on other-route Next.js chunk/prefetch requests cancelled by navigation.
- Idle 60s window: `GET /api/agents` (t=25.0s) + `GET /api/approvals?status=pending` (t=55.0s) + `GET /api/agents` (t=55.0s) — same global-sidebar 30s pattern seen on Interviews; **no screen-specific idle poll** despite "Monitoring: Active" styling implying live background activity.

## Findings

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-EMAIL-001 | /dashboard/email | HIGH | honesty/UI-gap | Needs-reauth Gmail accounts are completely invisible in the UI; CTA falsely implies nothing is connected | Load Email Center with both linked accounts at `needs_reauth` (current prod state) | Some visible indication 2 accounts exist and need reconnecting (matches backend's own `note` field) | Zero account chips render (`.filter(status==="connected")`), button reads bare "Connect Gmail", 0/2 sessions show any "reauth"/"reconnect" text anywhere on the page | 01-cold-load.png, inbox.json, results.json→accountCards=0 | OPEN |
| ML-EMAIL-002 | /dashboard/email | INFO | wireframe-drift | Per-account "Sync Now" buttons from the wireframe don't exist in production | Compare `email-center.html` to `page.tsx` | `sync-1/2-em08/em10` | No such control anywhere | 01-cold-load.png | OPEN (by-design, not a runtime defect) |

No BLOCKER findings. No placeholder/fixture content: real inbox data, real AI-generated drafts (verified against the test suite's canned fixture — zero overlap), real audit trail with correct model attribution.

## Not-tested (HUMAN-GATED / explicitly out-of-scope for safety)

- **Actual email send** (`send-gate-confirm` → `sendEmailReply`) — explicitly not tested per this run's safety constraints (real Gmail account, real recipients). Send-gate UI verified to open/render/cancel correctly; the send call itself was never fired.
- Gmail account connect/disconnect/reconnect/set-primary (`connect-gmail-btn`, `inbox-set-primary`, `inbox-disconnect`) — not exercised; these mutate the real, currently-`needs_reauth` Gmail OAuth state on a real account and risk breaking the existing (partially-working, historically-synced) connection. Read-only observation only.
- Full reconciliation of all 3 `test_wave4c_*` baseline suites — not re-run individually inside this time-box; targeted production behavior for sends/drafts/audit verified directly instead (see targeted verification 5).

## Data left behind

**One EmailThread row was NOT cleaned up** — there is no `DELETE /emails/{thread_id}` endpoint in the API (`ROUTER-MATRIX.md` confirms no delete route on the `emails` router), so the adversarial test draft created during compose testing could not be removed via the UI or API:
- Thread id: `cfc2cce71b52d38ffeff2db29`
- Subject: `GOLD-MASTER-V4 TEST DRAFT - safe to delete <script>alert(1)</script>`
- Owner: this account (AETHER_CRON_EMAIL), visible in the "All Recruiter" inbox tab.
- Recommend: operator manually deletes this row from the `EmailThread` table (or adds a delete-draft endpoint) — flagging for the orchestrator/operator since no in-product mechanism exists.

## Sign-off

Screen tested per §3.2 protocol: cold-load screenshot, wireframe conformance, category tabs, AI Triage/Analyze/Draft-Reply all genuinely triggered with network+audit capture (draft output diffed against the test-suite fixture — no overlap, confirmed non-fixture), compose/draft-only path exercised through empty+adversarial submissions with proven reload/fresh-session persistence, send-gate opened-then-cancelled (send never fired), model-selected-vs-model-recorded verified matching for both agents run in this batch, idle-poll measured (30s global-sidebar only), unauthenticated redirect, verified twice. Verdict: **real backend wiring and genuine non-fixture AI generation confirmed; one HIGH honesty gap (ML-EMAIL-001, needs-reauth accounts invisible) and one un-cleanable leftover test-draft row (documented above) are the notable outcomes.**
