# TESTING OUTCOME REPORT — /dashboard/settings (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 3)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T18:14–18:20Z. Account: AETHER_CRON_EMAIL (non-admin). Playwright, Python, headless Chromium, 1440x1200.

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 01-initial-load-profile.png + results.json)

- 8 settings tabs (`settings-nav-*`): **profile, resume, portfolio, notifications, agents, integrations, privacy, billing** — every one clicked and screenshotted (02-tab-*.png).
- **Connected Accounts & API Keys** (integrations/profile tab): OpenRouter ("Configured via server environment (legacy)"), Abacus Subscription fallback ("standby — a higher-priority OpenRouter/Anthropic key is active"), and 2 Gmail accounts (melbvicduque@gmail.com — primary, sarkar.vikram@gmail.com). [VERIFIED-WITH-FRESH-EVIDENCE 03-integrations-accounts.png]
- **Agent Configuration** tab: Auto-apply toggle, Approval-gate toggle, Match-threshold slider (50–100%, step 5) — all three are honestly disclosed in-UI as **persisted but not yet enforced by any backend agent logic** ("Saved, but not yet enforced by the agents…"), matching the code's `INERT-CONFIG-001` comments verbatim. No dishonest "it works" framing found.
- **Notifications** tab: no per-category toggles (deliberately removed per code comment citing G-O "shipped placeholder" concern) — replaced with an honest info notice pointing to the real Notification Agent on `/dashboard/agents`.
- **Job Board Integrations**: "Sync All" button present (gated on target role/location being set in Profile).
- **Billing** tab: plan name/status/price/next-billing-date, quota (runs + spend), "Manage subscription" button.

## Targeted verifications

1. **Google Calendar connection control**: **ABSENT** — confirmed by full-page text scan on every one of the 8 tabs (`calendar_mentions_by_tab: None` — zero hits) plus a source-code grep of the entire `apps/web/src/` tree for "Google Calendar"/"Connect Calendar" (zero results). Matches §10.5 expectation. [VERIFIED-WITH-FRESH-EVIDENCE 01–07 tab screenshots, results.json]
2. **"Give Feedback" button / Google Forms link**: **ABSENT** — same full scan, zero hits on every tab and in source. Matches §18.3 expectation. [VERIFIED-WITH-FRESH-EVIDENCE same as above]
3. **"Report a bug" link (global nav/footer)**: **ABSENT** — scanned the sidebar/footer text visible on every settings tab load; no such link/button anywhere. [VERIFIED-WITH-FRESH-EVIDENCE 01-initial-load-profile.png]
4. **Model/provider picker on Settings, listing live models**: **ABSENT.** Grepped `settings-client.tsx` (1261 lines) for `ModelPicker`, `fetchProviderCatalog`, `fetchProviderModels`, `agents/providers`, `agents/user/providers` — zero matches; no `<select>` model control exists anywhere on this screen. The live OpenRouter model-catalog picker lives exclusively on `/dashboard/agents` (tested there). **This contradicts SCREEN-MATRIX.md**, which lists `GET /agents/providers`, `PUT /agents/user/providers/{provider}/credential`, `DELETE /agents/user/providers/{provider}/credential` as endpoints called from `/dashboard/settings` — no network call to any of those paths was observed from this screen in the full session capture (network-log.json), and the source has no reference to them. Filed as a documentation-accuracy finding (ML-SETTINGS-002).
5. **Setting persistence end-to-end**: Match-threshold slider moved 50% → 75%, clicked "Save" → `PUT /api/workspaces/settings` → 200 → hard reload → slider still reads 75% (real persistence, not optimistic-only) → restored to 50% and re-saved, confirmed restored on a THIRD independent fresh session (`fresh_session_threshold_value: "50"`). [VERIFIED-WITH-FRESH-EVIDENCE 04/05/06/09 screenshots, results.json → `threshold_persistence`]

## Interaction / forms / persistence

- All 8 tabs clicked and rendered without error.
- Adversarial input test: entered `<script>alert(1)</script>` into the GitHub-URL field (portfolio tab) — rendered as inert plain text in the input (no script execution, no console error), then cleared without saving (no destructive persist attempted). [VERIFIED-WITH-FRESH-EVIDENCE 10-adversarial-input.png]
- `PUT /workspaces/settings` is the real, single save endpoint for this whole page (confirmed via network capture) — matches ROUTER-MATRIX.

## Error / edge states

- Unauthenticated access → redirected to `/login?next=%2Fdashboard%2Fsettings`. [VERIFIED-WITH-FRESH-EVIDENCE 08-unauthenticated-access.png]
- Verified twice: independent fresh session reproduced identical absence-of-Calendar/Feedback/bug-link findings and the persisted threshold value. [VERIFIED-WITH-FRESH-EVIDENCE 09-freshsession2-verify.png]

## Console / network / server-log summary

- console-log.json / pageerrors.json / requestfailed.json captured for the full session — no console errors, no failed requests, no XSS execution from the adversarial input test.

## Findings

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-SETTINGS-001 | /dashboard/settings | INFO | confirmation | Google Calendar / Give Feedback / Report-a-bug all absent as expected | Scan all 8 tabs | §10.5 / §18.3: expected ABSENT | Confirmed absent, zero hits | 01–07 tab screenshots, results.json | OPEN (confirmatory, not a defect) |
| ML-SETTINGS-002 | /dashboard/settings | LOW | doc-accuracy | SCREEN-MATRIX.md lists provider-credential endpoints for this route that the client never calls | Grep settings-client.tsx + inspect network-log.json | SCREEN-MATRIX claims GET/PUT/DELETE `/agents/(user/)providers...` are called from `/dashboard/settings` | Zero references in source, zero calls observed; that picker lives only on `/dashboard/agents` | network-log.json, results.json | OPEN |

No BLOCKER or HIGH findings. No placeholder/fixture content found. No model/provider picker exists on this screen at all (not merely non-live-list — fully absent), which directly answers the task's targeted question.

## Not-tested (out of scope / HUMAN-GATED)

- Resume upload / GitHub-portfolio-sync / LinkedIn-sync buttons — not exercised with real file uploads or real external OAuth to avoid mutating real connected-account state.
- Billing "Manage subscription" button — not clicked (would leave the Stripe customer portal / could imply a billing-state change); explicitly out of SAFETY scope ("do not change billing/subscription state").
- Full empty-form and invalid-value submission sweep across all 8 tabs — time-boxed; only the Agent Configuration threshold field and one adversarial portfolio input were exercised as representative samples.

## Data left behind

- Match-threshold slider: moved 50→75→50 (save → reload-verify → restore → save). Confirmed restored to the original 50% in a third fresh session.
- Portfolio GitHub-URL field: adversarial XSS string entered then cleared before any save — never persisted.

## Sign-off

Screen tested per §3.2 protocol: load+screenshot every tab, absence-checks for Calendar/Feedback/bug-link across the whole screen, provider/model-picker absence confirmed against both source and live network capture, one real setting persisted end-to-end with reload verification and restore, adversarial input probed safely, unauthenticated + fresh-session-twice. Verdict: **Settings screen honestly discloses its own inert config (auto-apply/approval-gate/threshold not yet enforced), all three §10.5/§18.3 absence requirements confirmed, and one screen-matrix documentation inaccuracy found (ML-SETTINGS-002).**
