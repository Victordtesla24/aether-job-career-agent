# INCOMPLETE-FEATURE-INVENTORY-FRONTEND — GOLD-MASTER-V2 §4.1 (Frontend half)

Status: **TRIAGE COMPLETE** — all 128 frontend grep hits classified; item-2 sweep for disabled/"Coming
Soon"/planned UI also complete. See §6 Coverage.

Scope: `apps/web/src/**` only. Backend (`apps/api/**`, `packages/**`) is owned by another agent
(`docs/delivery/INCOMPLETE-FEATURE-INVENTORY-BACKEND.md`) and is out of scope for this document.

Method: no source code was modified, no pytest/vitest/Playwright was run, no headless browser was launched,
no sub-agents were spawned — static code reading only, per the HARD PROCESS RULES for this task.

Input: `uat/reports/evidence/gold-master-v2/phase0/INCOMPLETE-GREP.json` filtered to files under
`apps/web/src/`. That filter yields **36 files / 128 hits** (of the file's reported 432 total hits / 143
user-reachable hits across the whole repo, which include the backend). This document classifies all 128
frontend hits [VERIFIED] against the actual source, plus additional disabled/"Coming Soon"/planned UI found by
a targeted follow-up sweep (`grep -rniE "coming soon|not (yet )?available|disabled|in planning|roadmap"` plus
`Math.random`/`lorem ipsum`/`TODO`/`FIXME` sweeps) that the phase-0 grep's keyword list missed (§4.1 item 2).

Supporting context consulted: `SCREEN-MATRIX.md` (27 routes / 59 endpoints), `GOLD-MASTER-V2-STATE.json`
(workstream definitions W-A..W-L), `BEFORE-RECORD.md` (prod screenshots; its "Visual" column is a
known-broken heuristic and was ignored per instructions).

Pre-settled ruling (recorded as-is, not re-litigated): the Jobs screen's Seek "(unavailable)" label
(`apps/web/src/app/dashboard/jobs/page.tsx:854`) is truthful, backend-served via
`GET /agents/scout/sources/availability`; a binding risk-officer ruling this run REFUSED enabling Seek.
Disposition: **B (HONEST-EMPTY-STATE)**. Not a defect; do not propose removal. [VERIFIED, jobs/page.tsx:446-476]

## 1. Summary counts by disposition

| Disposition | Count |
|---|---|
| A. PROHIBITED-STUB | 0 |
| B. HONEST-EMPTY-STATE | 24 |
| C. BENIGN-IDENTIFIER | 101 |
| D. INCOMPLETE-FEATURE | 2 (grep hits) + 3 (item-2 sweep, not grep hits — see §2) |
| UNSURE | 1 |
| **Total classified (grep hits)** | **128 / 128** |

**Headline finding: zero PROHIBITED-STUB (A) hits in the frontend.** Every "placeholder"/"hardcoded"/
"unavailable" grep token that resolved to actual rendered user-facing content, on inspection, was either (a)
a genuine HTML `placeholder=` input attribute or CSS utility class (benign, C), or (b) an honest
empty/unavailable/degraded-state message backed by a real API flag or absent backend capability (B) — never
invented/canned/sample data presented as real. This is consistent with the codebase's pervasive
anti-fabrication commenting convention (`ADR-AG-1`, `MV-*`, `QA-RES-F`, `INERT-CONFIG-001` etc. — every
"honest" pattern found is explicitly cross-referenced to a named audit finding, suggesting these were already
adversarially reviewed in prior runs).

The 2 grep-sourced D items and the 3 additional item-2 items are all **honestly disclosed** incomplete
features (disabled controls / explicit "not yet built" copy) — none of them fabricate data or mislead a user
into thinking a broken feature works. Severity is capped at MEDIUM/LOW throughout for that reason; none rise
to BLOCKER.

## 2. BLOCKER/HIGH/MEDIUM table — A and D items (grep hits + item-2 sweep)

| id | file:line | description | severity | screen/route | workstream | proposed genuine fix |
|---|---|---|---|---|---|---|
| FE-D-001 | `app/dashboard/settings/settings-client.tsx:918-938` (hits at :928, :1222) | Notifications tab: 3 toggles (approvals/app-updates/weekly-digest) are honestly disabled with "Notification delivery isn't built yet ... Coming soon" banner; no backend delivery mechanism exists | MEDIUM | `/dashboard/settings` (Settings — SCREEN-MATRIX §1) | **NOT MAPPED** — no current W-A..W-L covers notification delivery; recommend a new workstream if in scope for this run, else backlog | Build real notification delivery (candidate: reuse the existing `Notification Agent`'s Gmail-digest path already shipped for job-match digests, per `apps/api/app/routers/agents.py:319-327`) and wire these 3 toggles to persist + actually gate delivery. Until then, leave disabled — do NOT silently enable without a backend. |
| FE-D-002 | `app/admin/settings/page.tsx:4-116` (hit at :9) | Email-verification toggle is a permanently disabled, honestly-labeled no-op ("Not yet available — no backend code reads or enforces this setting", ML-audit-emailverify-toggle-001) | MEDIUM | `/admin/settings` (Global Configuration — SCREEN-MATRIX §2) | W-G (admin routes) | Implement backend enforcement: gate signup/login on a verified-email check when `emailVerificationEnabled` is true (send verification email, block unverified login), then remove `disabled` from the toggle. |
| FE-D-003 (item-2, not a grep hit) | `app/dashboard/settings/settings-client.tsx:848-869` (INERT-CONFIG-001) | "Auto-apply" preference is persisted via `PUT /workspaces/settings` but no backend agent code reads it — `board_sweep.py`'s autopilot always stays behind the same structural approval gate regardless of this toggle's value. Honestly hinted ("Saved, but not yet enforced by the agents"). | MEDIUM | `/dashboard/settings` (Agent Configuration tab) — behavior would surface on `/dashboard/jobs` autopilot | **NOT MAPPED** — related to autopilot work referenced in memory (`aether-external-client-fix.md`) but no current W-letter owns "wire autoApply preference into board_sweep" specifically | Either wire `agentConfig.autoApply` into `board_sweep.py`'s gate logic once real unattended auto-apply ships, or remove the toggle until that ships (avoid a persisted-but-inert control sitting indefinitely). |
| FE-D-004 (item-2, not a grep hit) | `app/dashboard/settings/settings-client.tsx:890-912` (INERT-CONFIG-001) | "Match threshold — only surface jobs above X%" slider is persisted but not read by any backend job-surfacing logic. Honestly hinted ("this value doesn't currently filter which jobs are surfaced"). | MEDIUM | `/dashboard/settings` (Agent Configuration tab) — behavior would surface on `/dashboard/jobs` | **NOT MAPPED** | Wire `agentConfig.matchThreshold` into the scout/matcher job-surfacing filter (`apps/api/app/agents/*` fit-scoring path), or remove the slider until it does something. |
| FE-D-005 (item-2, not a grep hit) | `components/agents/Orchestration.tsx:136-162` | "Pause All" and "Manual Override" buttons on the Agent Orchestration panel are permanently `disabled`, `title="Not yet available"` — no bulk-pause or manual-override backend endpoint exists (only per-agent enable/disable and per-agent run trigger do), per the inline `MV-agent-monitor-001` comment | LOW | `/dashboard/agents` (Agent Monitor & Control — SCREEN-MATRIX §1) | **NOT MAPPED** — closest is W-I (agent/dashboard realtime work), not an exact fit | Either implement bulk-pause/manual-override backend endpoints, or remove the two dead buttons entirely (they add visual clutter with zero function and have sat disabled across multiple prior audit cycles per the comment's own citation). |

No A (PROHIBITED-STUB) items were found in the frontend scope.

## 3. Appendix — B/C dismissals (one-line justification each, all 128 grep hits)

Format: `file:line | disposition | justification`. B = honest empty/unavailable/degraded state backed by a
real API signal. C = benign identifier (HTML `placeholder=` attribute, CSS class, TS/zod type field,
data-testid, or a comment) with no runtime effect on what data is shown.

| file:line | disposition | justification |
|---|---|---|
| app/admin/settings/page.tsx:9 | C | doc comment; the actual INERT toggle is filed separately as a D item below |
| app/admin/users/page.tsx:71 | C | input placeholder attribute |
| app/admin/users/page.tsx:72 | C | CSS class |
| app/dashboard/agents/page.tsx:15 | C | doc comment |
| app/dashboard/agents/page.tsx:149 | C | comment |
| app/dashboard/agents/page.tsx:515 | C | comment |
| app/dashboard/agents/page.tsx:517 | B | honest 'Unavailable' treatment for a degraded coverLetter run in the runs table |
| app/dashboard/cover-letters/page.tsx:122 | C | comment |
| app/dashboard/cover-letters/page.tsx:123 | C | comment |
| app/dashboard/cover-letters/page.tsx:133 | B | honest check of missingResume/coverLetterUnavailable/cover_letter_id before treating a run as a real success |
| app/dashboard/email/page.tsx:40 | C | comment |
| app/dashboard/email/page.tsx:1090 | C | input placeholder attribute |
| app/dashboard/email/page.tsx:1092 | C | CSS class |
| app/dashboard/email/page.tsx:1104 | C | input placeholder attribute |
| app/dashboard/email/page.tsx:1106 | C | CSS class |
| app/dashboard/email/page.tsx:1118 | C | textarea placeholder attribute |
| app/dashboard/email/page.tsx:1120 | C | CSS class |
| app/dashboard/interviews/page.tsx:14 | C | doc comment describing historical MV-interview-center fix, real backend now wired |
| app/dashboard/interviews/page.tsx:585 | C | input placeholder attribute |
| app/dashboard/interviews/page.tsx:598 | C | input placeholder attribute |
| app/dashboard/interviews/page.tsx:636 | C | textarea placeholder attribute |
| app/dashboard/jobs/page.tsx:6 | C | doc comment, header |
| app/dashboard/jobs/page.tsx:448 | C | comment |
| app/dashboard/jobs/page.tsx:450 | C | comment |
| app/dashboard/jobs/page.tsx:473 | B | isSourceUnavailable() derives availability from backend GET /agents/scout/sources/availability (settled Seek ruling context) |
| app/dashboard/jobs/page.tsx:731 | B | honest 'Sync time unavailable' fallback text when lastSync is null |
| app/dashboard/jobs/page.tsx:784 | B | honest 'Sync status unavailable' fallback text when scoutSources empty |
| app/dashboard/jobs/page.tsx:834 | C | input placeholder attribute |
| app/dashboard/jobs/page.tsx:837 | C | CSS class (placeholder: text color utility) |
| app/dashboard/jobs/page.tsx:850 | B | disables option via backend-derived isSourceUnavailable (settled Seek ruling) |
| app/dashboard/jobs/page.tsx:854 | B | SETTLED: truthful Seek '(unavailable)' label, backend-served, risk-officer REFUSED enabling Seek |
| app/dashboard/jobs/page.tsx:862 | C | input placeholder attribute |
| app/dashboard/jobs/page.tsx:865 | C | CSS class (placeholder: text color utility) |
| app/dashboard/networking/lib.ts:8 | C | comment |
| app/dashboard/networking/lib.ts:43 | C | comment documenting honest empty-column behavior (never fabricated cards) |
| app/dashboard/page.tsx:9 | C | comment asserting no hardcoding (funnel is data-driven) |
| app/dashboard/resume/page.tsx:44 | C | comment (type doc: never a hardcoded third party) |
| app/dashboard/settings/settings-client.tsx:149 | C | comment |
| app/dashboard/settings/settings-client.tsx:384 | C | comment |
| app/dashboard/settings/settings-client.tsx:774 | C | input placeholder attribute |
| app/dashboard/settings/settings-client.tsx:797 | C | input placeholder attribute |
| app/dashboard/settings/settings-client.tsx:823 | C | input placeholder attribute |
| app/dashboard/settings/settings-client.tsx:923 | C | data-testid identifier |
| app/dashboard/settings/settings-client.tsx:928 | D | Notifications panel: honestly disclosed 'notification delivery isn't built yet ... Coming soon' - real feature not built |
| app/dashboard/settings/settings-client.tsx:1049 | B | honest 'Price unavailable' fallback when plan/price not found in catalog |
| app/dashboard/settings/settings-client.tsx:1222 | D | shared Toggle component's 'Coming soon' badge, rendered for the not-yet-built notification toggles |
| app/login/page.tsx:114 | C | CSS class |
| app/login/page.tsx:128 | C | CSS class |
| app/signup/page.tsx:126 | C | CSS class (placeholder: text color utility) |
| app/signup/page.tsx:141 | C | CSS class |
| app/signup/page.tsx:161 | C | CSS class |
| components/agents/AgentConfigGrid.tsx:42 | C | CSS class value in status->style map |
| components/agents/AgentConfigGrid.tsx:49 | C | CSS class value in status->style map |
| components/agents/AgentConfigGrid.tsx:56 | C | CSS class value in status->style map |
| components/agents/AgentConfigGrid.tsx:63 | B | honest 'Planned' status label, backend-derived (AGENT_CATALOG entries with backend=None) |
| components/agents/AgentConfigGrid.tsx:143 | B | hides run/toggle controls for planned (not-yet-backed) agent cards - honest gating |
| components/agents/AgentConfigGrid.tsx:191 | B | hides model picker for planned agent cards - honest gating |
| components/agents/AgentConfigGrid.tsx:212 | B | hides settings panel for planned agent cards - honest gating |
| components/agents/AgentConfigGrid.tsx:242 | C | TS optional type field |
| components/agents/AgentConfigGrid.tsx:283 | B | honest 'N Planned' count label, backend-derived |
| components/agents/AgentModelPicker.tsx:5 | C | doc comment |
| components/agents/AgentModelPicker.tsx:172 | C | input placeholder attribute |
| components/agents/AgentModelPicker.tsx:173 | C | CSS class |
| components/agents/AgentStats.tsx:5 | C | comment (real GET /agents/stats derivation, no hardcoded numbers) |
| components/agents/ModelPicker.tsx:12 | C | comment documenting real click-time catalog derivation, no hardcoded id |
| components/agents/ModelPicker.tsx:221 | C | input placeholder attribute |
| components/agents/ModelPicker.tsx:222 | C | CSS class |
| components/agents/Orchestration.tsx:63 | C | comment |
| components/agents/Orchestration.tsx:115 | B | honest 'unavailable' task label for a degraded coverLetter run |
| components/agents/Orchestration.tsx:313 | B | honest 'unavailable (degraded)' task label |
| components/agents/ProviderConfigModal.tsx:38 | C | type field 'placeholder' |
| components/agents/ProviderConfigModal.tsx:52 | C | input placeholder attribute value |
| components/agents/ProviderConfigModal.tsx:58 | C | input placeholder attribute value |
| components/agents/ProviderConfigModal.tsx:67 | C | input placeholder attribute value |
| components/agents/ProviderConfigModal.tsx:490 | C | input placeholder attribute value |
| components/agents/ProviderConfigModal.tsx:558 | C | input placeholder attribute (dynamic from options) |
| components/agents/api.ts:21 | C | zod enum type incl. 'planned' literal |
| components/agents/api.ts:40 | C | zod optional number field |
| components/agents/api.ts:97 | C | comment |
| components/agents/api.ts:165 | C | comment |
| components/agents/api.ts:235 | C | comment |
| components/agents/logic.ts:60 | C | TS union type incl. 'planned' literal |
| components/agents/logic.ts:62 | B | status->label lookup incl. honest 'Planned' label, backend-derived |
| components/agents/logic.ts:163 | C | comment documenting real click-time catalog derivation |
| components/analytics/MarketPulse.tsx:303 | B | honest 'External market benchmark unavailable' disclosure when no provider configured |
| components/cover-letters/ActionsPanel.tsx:122 | C | textarea placeholder attribute |
| components/cover-letters/ActionsPanel.tsx:123 | C | CSS class |
| components/dashboard/feed.ts:54 | C | comment |
| components/dashboard/feed.ts:57 | C | comment |
| components/dashboard/feed.ts:69 | B | coverLetterDegraded(): implements honest degrade detection from real backend flag |
| components/dashboard/feed.ts:83 | B | honest 'Unavailable' badge for a degraded coverLetter run (never shown as success) |
| components/dashboard/feed.ts:182 | C | comment |
| components/dashboard/feed.ts:187 | B | honest text for degraded cover-letter generation |
| components/dashboard/feed.ts:202 | C | unrelated use of word 'planned' - describes supervisor agent's pipeline-planning action, not an incomplete-feature status |
| components/dashboard/sourceStatus.ts:36 | C | comment |
| components/dashboard/sourceStatus.ts:45 | B | honest 'unavailable (blocked by source)' badge label for a permanently-blocked source |
| components/offers/AddOfferModal.tsx:142 | C | opts type field 'placeholder' |
| components/offers/AddOfferModal.tsx:163 | C | input placeholder attribute |
| components/offers/AddOfferModal.tsx:166 | C | CSS class (placeholder: text color utility) |
| components/offers/AddOfferModal.tsx:210 | C | input placeholder attribute value 'e.g. Figma' |
| components/offers/AddOfferModal.tsx:211 | C | input placeholder attribute value 'e.g. Senior TPM' |
| components/offers/AddOfferModal.tsx:213 | C | input placeholder attribute value '185000' |
| components/offers/AddOfferModal.tsx:214 | C | input placeholder attribute value '0' |
| components/offers/AddOfferModal.tsx:215 | C | input placeholder attribute value '0' |
| components/offers/AddOfferModal.tsx:218 | C | input placeholder attribute value 'e.g. Sydney - Hybrid' |
| components/sidebar.tsx:22 | C | comment |
| components/sidebar.tsx:122 | B | honest 'Plan unavailable' fallback when subscription plan fetch fails |
| components/sidebar.tsx:162 | B | honest 'Agent status unavailable' fallback |
| components/stories/story-form.tsx:24 | C | CSS class (placeholder: text color utility) |
| components/stories/story-form.tsx:73 | C | input placeholder attribute |
| components/stories/story-form.tsx:96 | C | input placeholder attribute (dynamic from label) |
| components/stories/story-form.tsx:112 | C | input placeholder attribute |
| components/topbar.tsx:255 | C | input placeholder attribute |
| components/topbar.tsx:270 | C | CSS class |
| lib/agents-feedback.ts:88 | B | honest handling of response.coverLetterUnavailable flag |
| lib/agents-feedback.ts:215 | C | comment |
| lib/agents-feedback.ts:239 | C | comment (documents a real regression fix NF-final-closure-002) |
| lib/agents-feedback.ts:297 | C | comment (documents the same regression fix) |
| lib/api/client.ts:9 | C | comment documenting removal of unused hardcoded DEMO_CREDENTIALS (GAP-P4-068) |
| lib/api/coverLetters.ts:40 | C | comment |
| lib/api/coverLetters.ts:43 | C | TS optional boolean type field |
| lib/api/workspaces.ts:14 | C | comment (fixture-compat note on a type field) |
| lib/api/workspaces.ts:374 | C | comment noting a mock was already replaced by a real backend write |
| lib/auth/next-auth-options.ts:19 | UNSURE | NextAuth credentials provider is live-mounted at /api/auth/[...nextauth] but lookupUser/verifyPassword are permanent stubs (always null/false) since Phase 2 persistence was never wired; however no UI anywhere calls next-auth/react signIn() or posts to /api/auth/* - the real login flow uses POST /auth/login (FastAPI) + localStorage JWT. Reading 1 (D): dead/incomplete parallel auth path deployed to prod, should be finished or removed. Reading 2 (C): not reachable via any UI path a real user would take, so practically inert. |
| lib/config/legal.ts:13 | C | comment documenting anti-fabrication policy for business name default |
| lib/config/legal.ts:17 | C | comment documenting anti-fabrication policy for ABN |
| lib/config/legal.ts:40 | C | comment documenting ABN format-validation fallback |
| lib/navigation.ts:49 | C | comment referencing an unused helper (findNavItemByHref is exported but never called anywhere in app code); dead code, zero runtime effect |

## 4. UNSURE section

**`apps/web/src/lib/auth/next-auth-options.ts:19`** (comment: "Placeholder dependencies until the
persistence layer is wired in Phase 2")

[VERIFIED] The NextAuth `CredentialsProvider` is live-mounted at `app/api/auth/[...nextauth]/route.ts` (which
calls `NextAuth(authOptions)` and exports it as the Next.js route handler for `GET`/`POST /api/auth/*`).
Inside `authOptions`, `lookupUser()` unconditionally `return null` and `verifyPassword()` unconditionally
`return false` — this credentials path can **never** succeed; it is a permanent stub, not a genuine feature
that occasionally degrades honestly.

However, [VERIFIED] a repo-wide search (`grep -rln "next-auth/react"` and `grep -rn "signIn"` across
`apps/web/src`) found **zero** call sites: no page, component, or form anywhere in the app calls
`next-auth/react`'s `signIn()` or posts to `/api/auth/*`. The actual, working login flow
(`app/login/page.tsx`, per `SCREEN-MATRIX.md` §3) calls `POST /auth/login` on the FastAPI backend directly and
stores the JWT in `localStorage` (`lib/api/client.ts:14`) — a completely separate, functional auth system.

Two readings:
- **Reading 1 (lean D — INCOMPLETE-FEATURE):** this is real, deployed, permanently-broken production code (an
  API route that will always reject every credential) representing an abandoned Phase-2 NextAuth migration
  (`DECISIONS.md` D-0006) that was superseded by the custom JWT flow but never removed. It should either be
  finished (if NextAuth is still the intended long-term auth layer) or deleted (route handler +
  `next-auth-options.ts` + the `next-auth` dependency) as dead weight — a W-K (stale code cleanup) candidate.
- **Reading 2 (lean C — not practically reachable):** since no UI path links to it, a real paying user
  navigating the app normally can never trigger this code; it only matters to someone who discovers and
  directly calls the endpoint, which is not the "user-reachable" bar most other items in this inventory are
  held to. It costs nothing at runtime for ordinary users (no page renders through it).

Flagging as UNSURE rather than forcing a disposition, per the run's instruction to mark genuinely torn cases
with both readings. Recommend an architecture-owner decision: confirm whether NextAuth is still on the
roadmap; if not, delete it (cheap, unambiguous cleanup); if so, this becomes a real D item requiring the
Phase-2 persistence wiring.

## 5. Additionally observed disabled / "Coming Soon" / "Planned" / non-functional UI (§4.1 item 2)

Full sweep performed: `grep -rniE "coming soon|not (yet )?available|disabled|in planning|roadmap"` plus
separate `Math.random`, `lorem ipsum|sample data|dummy data|fake data`, and `TODO|FIXME|XXX:` sweeps across
`apps/web/src/**/*.{ts,tsx}` (excluding `__tests__`/`.test.` files). Results:

1. **Notifications tab, 3 disabled toggles + "Coming soon" badges** — `app/dashboard/settings/settings-client.tsx:918-938`.
   Already filed as **FE-D-001** above (was also a grep hit).
2. **Email-verification admin toggle, permanently disabled** — `app/admin/settings/page.tsx:108-116`.
   Already filed as **FE-D-002** above (was also a grep hit).
3. **"Auto-apply" preference, persisted-but-inert (not disabled, just has no effect)** — `settings-client.tsx:852-869`.
   Filed as **FE-D-003** above. Not a grep hit — found via manual read of surrounding code while
   investigating the Notifications section.
4. **"Match threshold" slider, persisted-but-inert** — `settings-client.tsx:890-912`. Filed as **FE-D-004**
   above. Not a grep hit, same discovery path as #3.
5. **"Pause All" / "Manual Override" buttons, permanently disabled** — `components/agents/Orchestration.tsx:144-162`.
   Filed as **FE-D-005** above. Not a grep hit — found via the targeted `disabled` sweep.
6. **"Approval gate" toggle** — `settings-client.tsx:871-888` (INERT-CONFIG-001, third instance in the same
   cluster as #3/#4). NOT filed as a defect: the hint honestly states the real approval gate is *stricter*
   than the toggle ("Always enforced today ... regardless of this preference") — i.e. toggling it OFF cannot
   loosen the real safety gate. This is a fail-safe/conservative design, not a gap. Disposition: **B**, no fix
   needed.
7. **"Submission Agent" — "Planned" roadmap card** — `components/agents/AgentConfigGrid.tsx` (rendering
   `AGENT_CATALOG` entries from `apps/api/app/routers/agents.py:189-191`, the only catalog entry with
   `"backend": None`). Renders with a dimmed border, a "Planned" status label, and no Run/Toggle/model-picker
   controls — an honest, backend-driven roadmap indicator, not a stub masquerading as functional. This is the
   one AGENT_NAMES entry the `AGENTS-IMPLEMENTATION-MATRIX-2026-07-29.md` wave-4 build did not cover
   (browser-automation form-filling). Disposition: **B**, not filed as a table defect — genuinely out of this
   triage's scope (a large net-new capability, not a partially-wired existing one). Noted here per the
   §4.1 item-2 instruction to flag "Planned" UI regardless of grep match.
8. `Math.random` sweep: only one match repo-wide, and it is a comment stating Math.random is NOT used
   (`components/sidebar.tsx:115`) — confirms absence, not presence, of the prohibited pattern.
9. `lorem ipsum` / `sample data` / `dummy data` / `fake data` sweep: zero matches.
10. `TODO` / `FIXME` / `XXX:` sweep: zero matches in `apps/web/src` (excluding tests).
11. `components/offers/NegotiationCoach.tsx:88` — the "Draft counter email" template uses `[Hiring Manager]`
    and `[Your Name]` bracket placeholders around a real, server-computed counter-offer dollar figure. Not a
    grep hit (found via the same sweep). This is a deliberate, documented (MV-offer-comparison-002) design —
    clearly-marked fill-in-the-blank fields, not fabricated identity — the dollar amount is always real, never
    invented. Disposition: **C** (benign — standard mail-merge-style template convention, not a data
    fabrication concern).

## 6. Coverage

**COVERAGE: COMPLETE.** All 36 frontend files / 128 grep hits from `INCOMPLETE-GREP.json` under
`apps/web/src/**` were read in their surrounding context and classified (§3 appendix). The item-2 sweep for
disabled/"Coming Soon"/planned UI not captured by the original grep keyword list was run separately (§5) and
its 3 additional finds folded into the §2 table (FE-D-003, FE-D-004, FE-D-005). One item was genuinely torn
and filed as UNSURE (§4) rather than forced into a disposition.

Files covered (36/36): `app/admin/settings/page.tsx`, `app/admin/users/page.tsx`,
`app/dashboard/agents/page.tsx`, `app/dashboard/cover-letters/page.tsx`, `app/dashboard/email/page.tsx`,
`app/dashboard/interviews/page.tsx`, `app/dashboard/jobs/page.tsx`, `app/dashboard/networking/lib.ts`,
`app/dashboard/page.tsx`, `app/dashboard/resume/page.tsx`, `app/dashboard/settings/settings-client.tsx`,
`app/login/page.tsx`, `app/signup/page.tsx`, `components/agents/AgentConfigGrid.tsx`,
`components/agents/AgentModelPicker.tsx`, `components/agents/AgentStats.tsx`,
`components/agents/ModelPicker.tsx`, `components/agents/Orchestration.tsx`,
`components/agents/ProviderConfigModal.tsx`, `components/agents/api.ts`, `components/agents/logic.ts`,
`components/analytics/MarketPulse.tsx`, `components/cover-letters/ActionsPanel.tsx`,
`components/dashboard/feed.ts`, `components/dashboard/sourceStatus.ts`, `components/offers/AddOfferModal.tsx`,
`components/sidebar.tsx`, `components/stories/story-form.tsx`, `components/topbar.tsx`,
`lib/agents-feedback.ts`, `lib/api/client.ts`, `lib/api/coverLetters.ts`, `lib/api/workspaces.ts`,
`lib/auth/next-auth-options.ts`, `lib/config/legal.ts`, `lib/navigation.ts` (all under `apps/web/src/`).

Not run / explicitly out of scope per HARD PROCESS RULES: pytest, vitest, Playwright/headless browser, any
source-code modification, any sub-agent/fork delegation. `apps/api/**` and `packages/**` are excluded (owned
by the backend triage, `INCOMPLETE-FEATURE-INVENTORY-BACKEND.md`).
