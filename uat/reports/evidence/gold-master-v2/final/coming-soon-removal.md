# GOLD-MASTER-V2 §4 / G-B + G-O — Remove the last shipped "Coming Soon" stub

Agent: fixer-medium. Repo: `/home/ubuntu/github_repos/aether-job-career-agent`. Frontend-only fix (no backend
code touched). Date: 2026-07-31.

## Adjudication

**Choice: (b) REMOVE the three unimplemented toggles** (kept the "Notifications" tab itself — see why below —
but removed all three fake/disabled controls and the "Coming soon" copy), **replaced with an honest pointer to
a real, already-shipped delivery path.**

### Justification

1. **Checked for a real backend delivery path first**, per instructions. Found one:
   `apps/api/app/agents/notification_agent.py` — `NotificationAgent` — is a complete, tested, already-deployed
   agent: it composes a deterministic digest (application status changes + newly scored job matches) from the
   user's own rows, and queues an approval-gated send to the user's connected Gmail
   (`apps/api/app/routers/agents.py:1743-1748` dispatches `"notification"` → `NotificationAgent().run()`; it is
   in `_RUNNABLE_BACKENDS` and rendered today on `/dashboard/agents` via `AgentConfigGrid`/`AGENT_CATALOG`
   entry `{"key": "notification", ..., "backend": "notification", ...}`). This is real, not a stub.

2. **But the three Settings toggles do NOT map onto that agent.** They promise three things the backend
   genuinely does not have, and building them would be new infrastructure, not "wiring up an existing path":
   - *"Approval requests — Notify me when an agent needs my approval"* — implies a push/real-time notification
     fired the instant an `ApprovalRequest` is created. No such trigger exists anywhere in `apps/api` (grepped
     `apps/api/app/repositories/approval.py`, `apps/api/app/workers/board_sweep.py` — nothing sends a
     notification on approval creation).
   - *"Weekly digest — Summary of agent activity every Monday morning"* — implies an automatic weekly
     schedule. `NotificationAgent` is purely on-demand (invoked like any other agent via `POST /agents/run`);
     there is no scheduler in the repo that would fire it weekly (checked `apps/api/app/workers/board_sweep.py`
     — it only drives sourcing/tailoring/cover-letter/submission sweep steps, never `notification`; grepped the
     whole `apps/api` tree for `APScheduler`/`croniter`/`celery beat`/`.timer` — none call the notification
     agent).
   - *"Application updates"* — partially overlaps the digest's status-update section, but only when the user
     manually runs the agent, not as a preference-gated automatic push.

   Per the prompt's own instruction — *"Do NOT build a notification subsystem from scratch this late in the
   campaign; that is disproportionate and would ship undertested"* and *"If no such delivery path exists here,
   (b) is correct"* — building real-time approval pushes and weekly cron scheduling now would be exactly that
   disproportionate new subsystem. So (a) "genuinely implement the three toggles" is not available; (b) applies.

3. **Why the "Notifications" tab itself was NOT removed** (only its 3 toggles): `apps/web/src/app/dashboard/
   settings/sections.ts` pins the tab as a deliberate, tested wireframe-fidelity requirement — GAP-P4-062 —
   with its own regression guard, `apps/web/src/__tests__/settings/settings-subnav.test.ts`, asserting
   `"Notifications"` must exist at index 3 of `SECTIONS`, matching `design/screens/settings.html`'s
   `settings-subnav-st06` order exactly. Deleting the tab would re-break that already-fixed defect (production
   once had Notifications in the wrong nav position; this suite exists specifically so that never regresses)
   and would be scope creep beyond what this finding requires. The prompt explicitly sanctions removing "the
   Notifications tab (or the three unimplemented toggles)" — the parenthetical alternative is what was taken.

4. **Net result**: the tab now contains zero fake controls and zero "Coming soon" text. It honestly states
   there are no per-category preferences to save, and links to the real, already-working on-demand digest agent
   at `/dashboard/agents` instead of promising unbuilt push/schedule behavior. Nothing was fabricated; nothing
   new was built server-side; no scope creep beyond the settings-client.tsx section and its test.

`backend_path_exists: true` (a real delivery path exists) but it could not be "simply wired" to the specific
three-toggle preference contract as written, hence (b) rather than (a).

## What changed

- `apps/web/src/app/dashboard/settings/settings-client.tsx` (Notifications section, ~lines 918-940): removed
  the three `disabled` `Toggle` controls (`toggle-notif-approvals`, `toggle-notif-apps`, `toggle-notif-digest`)
  and the `notifications-unavailable-notice` "Coming soon" paragraph. Replaced with a single `role="status"`
  paragraph (`data-testid="notifications-info-notice"`) stating honestly that there are no preferences to save
  yet, plus a real `<Link href="/dashboard/agents">` to the Notification Agent that actually runs today.
- `apps/web/src/app/dashboard/settings/__tests__/notifications-jobboard.test.tsx`: replaced the obsolete
  MV-settings-001 describe block (which asserted the *presence* of the three disabled toggles and the old
  "Coming soon" disclosure — i.e. it encoded the very defect this fix removes) with a new describe block
  (`"SettingsPage — Notifications tab has no stub toggles or 'Coming soon' copy (GOLD-MASTER-V2 G-B/G-O)"`)
  asserting: the three toggle testids no longer render; no "coming soon"/"in planning"/"planned" text remains
  anywhere in the section; and the honest notice renders with a real link to `/dashboard/agents`. The unrelated
  MV-settings-002 (Job Board Sync) describe block was untouched. Updated the file's header doc-comment to
  record the supersession.

No backend files were touched. No new DB objects, no new endpoints, no new dependencies.

## Tests — fail before, pass after [VERIFIED-WITH-FRESH-EVIDENCE]

Command: `npx vitest run src/app/dashboard/settings/__tests__/notifications-jobboard.test.tsx` (run from
`apps/web`).

**Before the fix** (new assertions added to the file, `settings-client.tsx` still unchanged) — 2026-07-31T15:49:21Z:

```
 Test Files  1 failed (1)
      Tests  3 failed | 4 passed (7)
```//
The 3 failures were exactly the 3 new assertions: `toggle-notif-approvals` still present (should be null),
"coming soon" text still present, `notifications-info-notice` testid did not exist yet. The 4 unrelated
Job Board Sync tests in the same file passed throughout (proves the failures were isolated to this defect, not
environmental).

**After the fix** — 2026-07-31T15:52:56Z:

```
 RUN  v2.1.9 /home/ubuntu/github_repos/aether-job-career-agent/apps/web

 ✓ src/app/dashboard/settings/__tests__/notifications-jobboard.test.tsx (7 tests) 252ms

 Test Files  1 passed (1)
      Tests  7 passed (7)
```

## Full frontend suite [VERIFIED-WITH-FRESH-EVIDENCE]

Command: `pnpm --dir apps/web test` — 2026-07-31T15:49:52Z to 15:51:49Z (Duration 116.56s):

```
 Test Files  96 passed (96)
      Tests  650 passed (650)
```

**650/650, 0 failures — exact match to the 650/650 baseline, zero regressions.** (Net test count unchanged: 3
obsolete tests were replaced with 3 new tests in the same file — no tests were deleted without replacement.)

## Lint [VERIFIED-WITH-FRESH-EVIDENCE]

Command: `pnpm --dir apps/web lint` — 2026-07-31T15:52:56Z:

```
$ next lint --dir src --dir __tests__
✔ No ESLint warnings or errors
```

## Typecheck [VERIFIED-WITH-FRESH-EVIDENCE]

Command: `npx tsc --noEmit` (from `apps/web`) — 2026-07-31T15:52:56Z: **no output — clean** (zero errors).

## Grep sweep — every "Coming soon" / "In Planning" / "Planned" / "Coming Soon"-class hit in `apps/web/src`

Command: `grep -rniE "coming soon|in planning|\bplanned\b" apps/web/src --include="*.tsx" --include="*.ts"`
— 2026-07-31T15:52:56Z. Every hit and its disposition:

| File:line | String | Disposition |
|---|---|---|
| `settings-client.tsx:926` | `"Coming soon"` (inside a `/* ... */` code comment explaining the fix) | Not user-reachable — a source comment, not rendered UI. No action. |
| `settings-client.tsx:1233` | `Coming soon` (inside the generic `Toggle` component's `disabled`-badge JSX) | This is the reusable `Toggle` component's optional badge, rendered **only when a caller passes `disabled`**. Verified by grep (`<Toggle` usages) that after this fix **zero** callers of this `Toggle` (the two remaining calls, `autoApply` and `approvalGate` in the same file, are both non-disabled, real, saved preferences) pass `disabled` — the badge is unreachable on every live route today. Not itself a shipped stub; flagged as a residual risk below rather than deleted, to avoid touching a shared component beyond this finding's scope. |
| `notifications-jobboard.test.tsx` (multiple) | Test names/comments/assertions about "Coming soon" | Expected — these are the test file documenting and asserting the *absence* of the string post-fix. Not a hit. |
| `page.test.tsx:252,262,296` | `.not.toContain("coming soon")` assertions | Pre-existing test for the unrelated Agent Configuration tab (INERT-CONFIG-001) — already asserts absence there. Not a hit, no action needed. |
| `logic.ts:60,62` | `"planned"` / `"Planned"` in `STATUS_LABEL`-style status-label mapping | Live-data-driven: only renders if a real agent's `status` from `GET /agents/catalog` is `"planned"`. Verified server-side (`apps/api/app/routers/agents.py:2781`) that `state = "planned"` is only assigned when an `AGENT_CATALOG` entry has `"backend": None` — grepped the full 22-entry `AGENT_CATALOG` and **every entry has a real, non-null backend** (`scout`, `tailor`, `coverLetter`, `fitScorer`, `compliance`, `submission`, `matcher`, `salaryIntelligence`, `interviewPrep`, `companyResearch`, `recruiterOutreach`, `emailAgent`, `marketTrends`, `scheduling`, `sentimentAnalysis`, `reference`, `storyExtractor`, `learningFeedback`, `supervisor`, `notification`). No agent renders as "Planned" on any live route today — this is honest defensive handling of a hypothetical future state, not a shipped placeholder. No action. |
| `AgentConfigGrid.tsx:42,49,56,63,143,191,212,242,283` | `"planned"` styling/label/count logic | Same as above — all conditioned on real `agent.status === "planned"` / `counts.planned`, which is always `0`/absent today per the live catalog. Line 283's `"0 Planned"` legend pill is an honest live stat (parallel to "0 Error"), not an advertised capability. No action. |
| `AgentModelPicker.tsx:5` | `"non-planned agent card"` (code comment) | Not user-reachable. No action. |
| `api.ts:21,40,165` | `z.enum([...,"planned"])`, type field, comment | Schema/type plumbing for the same live-data-driven status above. Not user-reachable text. No action. |
| `feed.ts:202` | `"planned the discovery → tailoring pipeline"` | Ordinary past-tense English verb ("the agent planned X"), unrelated to feature-availability status. Not a hit. |
| `agents-screen.test.ts:261`, `ml-catalog-fix1.test.tsx` (multiple), `ml-agents-refix.test.tsx:163` | Test names/fixtures using `"planned"` | Test fixtures exercising the UI's handling of a *hypothetical* planned-agent card (defensive coverage) — confirmed these are mock data only, not read from any live endpoint. No action. |

**Zero live, user-reachable "Coming Soon"/"In Planning"/unbuilt-stub text remains on any route.**

## Residual risks

1. `Toggle`'s `disabled`-badge markup (`settings-client.tsx:1233`, the literal string `"Coming soon"`) is now
   dead code — unreachable because no caller passes `disabled` anymore. It was left in place rather than
   deleted from the shared component, to keep this diff scoped to the actual finding (the Notifications tab).
   Risk: if a future change adds a new `disabled` `Toggle` elsewhere in Settings, it will silently render
   "Coming soon" again with no test catching it (the regression test added here only covers the Notifications
   section). Recommendation for a future pass: either delete the badge feature from `Toggle` entirely, or add a
   codebase-wide grep-based lint/test asserting no `<Toggle ... disabled` call sites exist outside an explicit
   allowlist.
2. The new notice's wording ("no per-category notification preferences to save yet") is accurate today but
   will go stale the moment real push/schedule preferences are ever built — whoever builds that feature should
   also remove/rewrite this notice; no test pins it to be temporary, so nothing will force that follow-up.
3. The `Link` to `/dashboard/agents` is a plain navigation, not a deep link to the Notification Agent's card
   specifically — the user still has to locate/click "Run" on that card themselves once there. Low risk (the
   card is visible on that screen and its own honest run/approve flow is independently tested), but noted for
   completeness.

## Verbatim command log

```
$ cd apps/web && npx vitest run src/app/dashboard/settings/__tests__/notifications-jobboard.test.tsx
# BEFORE (2026-07-31T15:49:21Z): Test Files 1 failed (1) / Tests 3 failed | 4 passed (7)
# AFTER  (2026-07-31T15:52:56Z): Test Files 1 passed (1) / Tests 7 passed (7)

$ pnpm --dir apps/web test
# 2026-07-31T15:49:52Z – 15:51:49Z: Test Files 96 passed (96) / Tests 650 passed (650)

$ pnpm --dir apps/web lint
# 2026-07-31T15:52:56Z: ✔ No ESLint warnings or errors

$ npx tsc --noEmit   (from apps/web)
# 2026-07-31T15:52:56Z: (no output — clean)

$ grep -rniE "coming soon" apps/web/src --include="*.tsx" --include="*.ts" | grep -v "__tests__\|\.test\."
apps/web/src/app/dashboard/settings/settings-client.tsx:926:  (code comment)
apps/web/src/app/dashboard/settings/settings-client.tsx:1233: (dead Toggle-component badge, unreachable)
```
