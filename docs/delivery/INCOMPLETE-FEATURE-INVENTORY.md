# INCOMPLETE-FEATURE-INVENTORY — GOLD-MASTER-V2 §4.1 (Canonical, Merged)

**Status:** MERGE COMPLETE. Single canonical §4.1 deliverable, superseding the two triage halves as the
adjudication record (the halves remain on disk as source evidence, not duplicated deliverables).

**Author:** GOLD-MASTER-V2 claim-auditor (synthesis pass), single serial agent, no sub-agents/forks spawned,
no source code modified, no `pytest`/headless browser run — per this task's HARD RULES. Where this pass
needed to resolve a factual conflict between the two source documents, it re-read the cited source file
directly (permitted: static read, not a test run) and marks that resolution `[VERIFIED THIS RUN]`.

**Generated:** 2026-07-30T (this session) · **Repository:** `/home/ubuntu/github_repos/aether-job-career-agent`
· **Production:** `https://5cb5f0620.abacusai.cloud`

## Inputs merged (provenance)

| # | Document | Role | Trust level |
|---|---|---|---|
| 1 | `docs/delivery/INCOMPLETE-FEATURE-INVENTORY-BACKEND.md`(+`.json`) | Backend triage, 304 hits, A=0/B=183/C=119/D=2 | [VERIFIED] (source's own file:line citations) |
| 2 | `docs/delivery/INCOMPLETE-FEATURE-INVENTORY-FRONTEND.md`(+`.json`) | Frontend triage, 128 grep hits + 5 non-grep UI items, A=0/B=24/C=101/D=2+3/UNSURE=1 | [VERIFIED] (source's own file:line citations) |
| 3 | `.../phase0/INCOMPLETE-FEATURE-INVENTORY-FRONTEND-forkA.md` | Independent 2nd frontend reading, A=0/B=32/C=91/D=4/UNSURE=1 | **TESTIMONY** — self-declared "not [VERIFIED] evidence," used only for cross-checking, never to close a finding alone |
| 4 | `.../phase0/REFERENCE-GRAPH.md` | 9 feature-level verdicts (7 PARTIAL / 2 COMPLETE) | [VERIFIED]/[INFERRED] mixed per its own tags; feature-level, not line-level — referenced, not merged into the actionable table (different granularity, different owning workstreams) |
| 5 | `docs/delivery/GOLD-MASTER-V2-FEATURE-COMPLETENESS-MATRIX.md` | 46-row README/traceability claim audit, 29 CONFIRMED/5 OVERSTATED/8 FALSE/4 UNVERIFIABLE-HERE | [VERIFIED] per its own probe timestamps |
| 6 | `.../phase0/BLOCKER-admin-overpermission-verification.md` | CRITICAL confirmed security defect (`admin`/`admin123` = real owner + `isAdmin:true`) | [VERIFIED], CONFIRMED verdict by an independent qa-adversary |

This pass additionally performed 3 fresh first-party reads to resolve conflicts between inputs 1–3 (see §4 and
§5) — tagged `[VERIFIED THIS RUN]` below: `apps/web/src/app/admin/settings/page.tsx` (full file),
`apps/api/app/routers/admin.py` (settings section), `apps/api/app/routers/auth.py` (signup-gate lines), and a
`grep` of the production `.env` for `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `GROQ_API_KEY` / `APP_BASE_URL` (keys
checked for presence/absence only — no values printed or logged).

---

## 1. Executive Summary

**Total hits triaged: 432** (304 backend + 128 frontend grep hits, both halves independently reaching 100%
coverage) **+ 5 additional non-grep UI items** found by the frontend triage's targeted §4.1-item-2 sweep
(`FE-D-001`…`FE-D-005`, 2 of which coincide with grep hits and 3 of which do not).

**Headline result: repo-wide PROHIBITED-STUB (disposition-A) count = 0.** Zero hits — across every
"hardcoded"/"placeholder"/"mock"/"fixture"/"simulated"/"NotImplementedError" keyword match in both
`apps/api/app/**` and `apps/web/src/**` — resolved to genuine fabricated/mock/canned content served to a real
user as if it were real. Every hit resolved to one of: (b) an honest empty/unavailable/degraded state backed by
a real API signal (B, 207 hits, 47.9%), (c) a benign identifier — HTML `placeholder=` attribute, CSS class,
SQL bind param, docstring, test-only plumbing (C, 220 hits, 50.9%), or (d) a real, partially-built feature
described honestly rather than faked (D, 7 unique items after dedup, 1.6%). This is consistent with the
codebase's heavy, explicitly-commented investment in honest-degrade architecture (`LLMUnavailableError`/503,
`coverLetterUnavailable`, `source_availability()`, transient-failure classification) — architecture whose
own explanatory comments are exactly what the grep keyword scan surfaces so heavily.

**What A=0 does NOT mean.** It does not mean the product is complete, and it does not mean every "honest"
label is harmless. Three things stay explicitly in scope elsewhere in this document and are the real remaining
work:

1. **Incomplete FEATURES** — 7 unique, dedup'd, genuinely-unbuilt-or-half-wired capabilities (§2 below), none
   of which fabricate data, but several of which are silently inert in ways a paying user cannot detect from
   the UI alone (§3's "false affordance" analysis).
2. **False affordances** — settings a user actively configures and saves that are never enforced. §3 argues
   these are *more* dangerous than a visible "Coming Soon" placeholder, not less, precisely because the A=0
   scan (which only catches keyword-flagged *content*) cannot distinguish "this control does nothing" from
   "this control works" — a UI-behavior gap the keyword-based methodology is structurally blind to.
3. **8 FALSE and 5 OVERSTATED claims** already independently found in `GOLD-MASTER-V2-FEATURE-COMPLETENESS-
   MATRIX.md` (input #5) — e.g. README's "8 agents execute" (actually 19), "22 `AgentConfig` DB rows" (actually
   12 — the 22 is the code catalog size, not the table), and the single most severe finding in this entire
   run, **not** discovered by keyword-grepping: `admin`/`admin123` authenticates as the real owner account with
   `isAdmin:true` (BLOCKER-001, input #6, CONFIRMED CRITICAL). BLOCKER-001 is **not a W-B item** — it is
   already on its own dedicated remediation pipeline per `GOLD-MASTER-V2-STATE.json` §16 — but it is the
   highest-severity live defect in the run and is cross-referenced here so it is never lost sight of while W-B
   executes the lower-severity items below.

**In one sentence: the codebase does not lie to users with fake data (A=0, well-corroborated), but it does
contain a small number of features that quietly do nothing when a user believes they do something (§2–§3),
and separately carries a CRITICAL access-control defect that this keyword-driven triage was never designed to
catch (§6 cross-reference).**

---

## 2. Consolidated ACTIONABLE table (disposition-A + disposition-D + the 5 non-grep UI items, deduplicated)

**Scope note:** per the merge brief, this table is exactly disposition-A (0 rows — none found) + disposition-D
+ the five non-grep UI items (`FE-D-001..005`). `BLOCKER-001` (admin over-permission) is *not* in this table's
scope — it was not produced by the A/B/C/D grep triage and is not a W-B item; see the callout above and §6.

| id | file:line | description | severity (this doc's reasoned verdict — see §3) | owning screen(s) | owning workstream | proposed genuine fix |
|---|---|---|---|---|---|---|
| **FE-D-003** | `apps/web/src/app/dashboard/settings/settings-client.tsx:848-869` (INERT-CONFIG-001) | "Auto-apply" preference is fully interactive, savable via `PUT /workspaces/settings`, with only a small honest hint ("Saved, but not yet enforced by the agents") — but no backend agent code reads it; `board_sweep.py`'s autopilot stays behind the same structural approval gate regardless of this toggle's value. | **BLOCKER** (false affordance — see §3) | `/dashboard/settings` (Agent Configuration tab); behavior would surface on `/dashboard/jobs` autopilot | W-B | Wire `agentConfig.autoApply` into `board_sweep.py`'s gate logic once real unattended auto-apply ships, OR remove the toggle until it does something. Do not ship an interactive, savable control with no effect. |
| **FE-D-004** | `apps/web/src/app/dashboard/settings/settings-client.tsx:890-912` (INERT-CONFIG-001) | "Match threshold" slider is fully interactive, savable, with a small honest hint ("this value doesn't currently filter which jobs are surfaced") — but not read by any backend job-surfacing/matcher logic. `[VERIFIED THIS RUN]` re-read confirms: `data-testid="hint-matchthreshold"` at line 908 is a benign test-hook (not itself a defect) sitting directly below the real, uncoupled slider control. | **BLOCKER** (false affordance — see §3) | `/dashboard/settings` (Agent Configuration tab); behavior would surface on `/dashboard/jobs` | W-B | Wire `agentConfig.matchThreshold` into the scout/matcher fit-scoring filter (`apps/api/app/agents/*`), OR remove the slider until it does something. |
| **MERGED: INC-B-002 = FE-D-002** | Backend: `apps/api/app/routers/admin.py:172-222` (`SettingsRequest.emailVerificationEnabled`, `admin_repo.EMAIL_VERIFICATION_KEY`). Frontend: `apps/web/src/app/admin/settings/page.tsx:4-9,108-116`. | **Same defect observed from both ends — see §4 for the full merge reasoning, including a correction to how "reachable" the backend half originally claimed this was.** The DB-persisted `emailVerificationEnabled` flag is never read by `routers/auth.py`'s `register()`/`login()` flow — toggling it has zero effect on account verification. Its sibling `signupEnabled` toggle in the *same* settings object **is** enforced (`auth.py:85-87`, `[VERIFIED THIS RUN]`), which is direct evidence this is an oversight, not a deliberate design choice. `[VERIFIED THIS RUN]`: the shipped Admin Settings UI renders this toggle with a literal `disabled` attribute (not `disabled={busy}` like its sibling) and a no-op `onChange`, with the honest hint "Not yet available — no backend code reads or enforces this setting" — so a human operator using the shipped page cannot actually flip it. However, `[VERIFIED THIS RUN]` `POST /admin/settings` (`admin.py:203-222`) applies **zero server-side validation** against `emailVerificationEnabled` — it accepts and persists `true` from any raw API caller (curl/Postman/a future UI regression that drops the `disabled` prop) with no guard and no downstream effect. | **HIGH** (see §3 — honestly disclosed in the shipped UI, corrected down from the backend half's original framing, but the underlying control-plane gap is genuine, security-policy-adjacent, and completely unguarded at the API layer) | `/admin/settings` (Global Configuration) | W-B (cross-ref W-G, admin routes) | EITHER (a) wire real enforcement — `emailVerified` column (additive migration) + verification email on register + login/feature gate until verified, and only then remove `disabled` from the UI toggle — OR (b), if out of scope this launch, keep the UI honestly disabled (already correct) **and** add the same server-side rejection to `POST /admin/settings` that a not-yet-implemented setting deserves (422/400, not silent-accept-and-ignore) so a direct API caller cannot create a false persisted state either. |
| **FE-D-001** | `apps/web/src/app/dashboard/settings/settings-client.tsx:918-938` (grep hits at :928, :1222) | Notifications tab: 3 toggles (approvals / app-updates / weekly-digest) are honestly `disabled`, each with `role="status"` banner text: *"Notification delivery isn't built yet — these preferences aren't functional and aren't saved by 'Save Changes'. Coming soon."* `[VERIFIED THIS RUN]` re-read confirms every toggle passes a literal `disabled` prop and a no-op `onChange={() => undefined}`. | **HIGH** (see §3 — visible, honestly disclosed, non-interactive; elevated above LOW/MEDIUM only because §4's literal exit-criterion explicitly names "Coming Soon" states and every regular user on the platform passes through this exact screen) | `/dashboard/settings` (Notifications tab) — every user's Settings screen | W-B (no current W-letter owns notification delivery; recommend backlog if out of this run's scope) | Build real delivery (candidate: reuse the Notification Agent's existing Gmail-digest path, `agents.py:319-327`) and wire the 3 toggles to persist + actually gate delivery. Until then, leave `disabled` — do not silently enable without a backend. |
| **FE-D-005** | `apps/web/src/components/agents/Orchestration.tsx:136-162` (MV-agent-monitor-001) | "Pause All" and "Manual Override" buttons on the Agent Orchestration panel are permanently `disabled`, `title="Not yet available"` — no bulk-pause/manual-override backend endpoint exists (only per-agent enable/disable + per-agent run trigger do). | **LOW** (visibly disabled, honest tooltip, niche monitor-panel convenience — not a paid-feature promise) | `/dashboard/agents` (Agent Monitor & Control) | W-B (cross-ref W-I, agent/dashboard realtime) | Implement bulk-pause/manual-override backend endpoints, or remove the two dead buttons (zero function, sat disabled across multiple prior audit cycles per the comment's own citation). |
| **INC-B-001** | `apps/api/app/routers/billing.py:298` | `_dispatch_stripe_event()` has a real branch for every subscription/invoice/charge lifecycle event except `customer.subscription.trial_will_end`, a bare `pass` ("hook point for a reminder notification; no state change"). The platform genuinely supports live Stripe trials (`trialing` is an entitled status, `repositories/billing.py:409-427`), so trial users get no proactive "trial ending" reminder. Does **not** affect billing accuracy/entitlement — only the reminder is missing. Webhook still 200s idempotently. | **LOW** (no UI surface at all — nothing is *shown* as a placeholder to any user; a silent absence, not a rendered stub; does not misrepresent anything) | None (backend-only; would surface as a missing email) | UNMAPPED — no current W-A..W-L covers billing notifications; recommend operator backlog / new workstream | Implement `_handle_trial_will_end(cur, obj)`: look up user by `stripeCustomerId`, enqueue a real reminder (reuse `gmail_service` or a notification-digest agent) — or replace the bare `pass` with an explicit "intentionally deferred" comment so a future reader doesn't mistake it for an oversight, and confirm no UI anywhere promises this reminder. |

**Rows: 6** (7 source items → 6 after the INC-B-002/FE-D-002 merge). **0 disposition-A rows** (none found in
either half). Every row above requires a genuine fix per §7 — none are proposed for removal-as-"not a defect."

---

## 3. Severity adjudication — applying §4's BLOCKER rule, then reasoning about "false affordances"

**§4's literal rule, applied strictly first:** *"any feature that is incomplete, half-implemented, or showing
placeholder/stubbed output is a BLOCKER."* Read at face value, **all 6 rows in §2 qualify** — every one of them
is, in some sense, an incomplete feature reachable by a real user (including an admin user, for the merged
row). A strict, uncritical application would therefore label all 6 `BLOCKER` and stop there.

This document does not stop there, because a flat "everything is a BLOCKER" reading destroys the one thing a
severity label is for: telling the next agent what to fix first. Six items that are all technically
"incomplete" span a wide range of actual user harm — from a slider that silently ignores what a paying user
configured, to a backend `pass` statement that nobody outside the codebase will ever observe. Treating them
identically would mean the true worst item (an interactive control lying about its own effect) competes for
attention on equal footing with a genuinely cosmetic gap (two permanently-greyed buttons on an internal
monitor panel). §7's execution order needs real differentiation to be useful, so this section reasons about it
explicitly rather than assigning one label to all six and calling it done.

### The false-affordance question: MORE or LESS severe than a visible placeholder?

**Verdict: MORE severe. `FE-D-003` and `FE-D-004` are ranked `BLOCKER`; the honestly-disclosed items
(`FE-D-001`, the merged email-verification row, `FE-D-005`) are ranked `HIGH`/`HIGH`/`LOW` respectively —
strictly below the false affordances, never above.**

Reasoning:

1. **A visible placeholder cannot deceive.** `FE-D-001`'s "Coming Soon" banner and disabled toggles, and the
   merged row's disabled admin toggle, are both **non-interactive** — `[VERIFIED THIS RUN]` in both cases the
   control literally cannot be turned on by a user following the normal UI. The honest-disclosure text is not
   load-bearing for safety here; the DOM-level `disabled` attribute is what actually prevents the
   misunderstanding. A user attempting to interact with these controls gets immediate, unambiguous feedback
   (the control does not move) even if they never read the hint text at all.

2. **A false affordance actively defeats the same safety property the disabled controls get for free.**
   `FE-D-003`/`FE-D-004` are fully interactive: the toggle flips, the slider drags, `PUT /workspaces/settings`
   returns success, and "Settings saved" renders. A paying user who sets the match threshold to 90% and closes
   the tab has every reason to believe unmatched jobs are now filtered — nothing in the interaction contradicts
   that belief. The honest hint text (`"this value doesn't currently filter which jobs are surfaced"`) is small
   print (`text-[10px]`, `[VERIFIED THIS RUN]`) sitting below an otherwise fully-functional-looking control,
   and there is no requirement that the user ever read it, unlike a disabled control where the *absence of
   response* is unavoidable feedback.

3. **The downstream consequence is asymmetric.** A user who sees "Coming Soon" simply does not get the
   feature — mild disappointment, zero false belief about current behavior. A user who configures auto-apply
   or a match threshold and gets neither may make real downstream decisions on a false premise: believing
   applications are being submitted unattended when they are not (missed windows, wasted trust in the
   product's core value proposition), or believing low-fit jobs are filtered when they are not (noisier board,
   wasted review time, and for a paying subscriber, a materially different product than the one configured).
   This is a genuine trust breach on a paid platform, not merely an unfinished feature.

4. **The keyword-grep methodology itself is structurally blind to this class.** The A=0 headline result (§1)
   is built entirely from *content* keyword matches. A control that renders correctly, accepts input, and
   returns HTTP 200 on save produces **no grep hit at all** for "mock"/"placeholder"/"hardcoded" — `FE-D-003`
   and `FE-D-004` were caught only by the separate, manually-directed §4.1-item-2 sweep, not by the automated
   scan. That means the true population of "features that quietly do nothing" is the one class this whole
   triage is least equipped to have exhaustively found — an explicit caveat this document owes the reader (see
   §7, item 0, and the coverage caveat repeated there).

Given that reasoning, the ranking used in §2/§7 is: **false affordance (interactive + easy-to-miss disclosure)
> honestly-disclosed-but-high-reach or security-adjacent (disabled + labeled, but many users see it, or it
governs security policy) > honestly-disclosed-and-low-reach (disabled + labeled, niche screen) > invisible
backend-only gap (no UI surface at all).** This is the ordering §2's severity column and §7's execution order
both follow. It intentionally does not collapse to a single "everything incomplete = BLOCKER" reading of §4,
and the reasoning above is the record of why, so a later reviewer can agree or override with equal rigor
rather than inheriting an unexplained label.

---

## 4. Cross-reading disagreement analysis (main frontend triage vs. forkA TESTIMONY)

Both readings agree **A=0** and agree on the **single UNSURE item** (`next-auth-options.ts:19`). They diverge
on B/C (24/101 main vs. 32/91 forkA) and D (2 main / 4 forkA, both counted over the same 128 grep-hit
population — forkA never attempted the non-grep item-2 sweep that produced `FE-D-003/004/005`, so those three
are **not** a disagreement, just a coverage-scope difference: forkA's stated scope is "all 128 frontend grep
hits" only).

### Where they actually disagree, checked against source `[VERIFIED THIS RUN]`

| Line | Main doc disposition | forkA (TESTIMONY) disposition | This pass's resolution |
|---|---|---|---|
| `apps/web/src/app/admin/settings/page.tsx:9` | **C** — "doc comment; the actual INERT toggle is filed separately as a D item below" | **D** (`INV-fe-001`) — treats the whole file's email-verification defect as attached to this line | **Main doc's classification is correct.** `[VERIFIED THIS RUN]` re-read of the file: line 9 is literally inside the top-of-file `/** ... */` docstring block (lines 3–9). The real D-worthy content is the `<Toggle>` JSX at lines 108–116, which the main doc correctly files separately as `FE-D-002`. forkA's per-line grep-hit disposition at :9 is inaccurate; its underlying finding (the toggle is inert) is correct and is already captured in §2's merged row. |
| `apps/web/src/app/dashboard/settings/settings-client.tsx:923` | **C** — `data-testid="hint-matchthreshold"`, a benign test-hook identifier | Implicitly grouped into **D** territory (`INV-fe-012d` cites `:923,928,1222` together as one D-worthy cluster) | **Main doc's classification is correct.** `[VERIFIED THIS RUN]`: line 923 is a bare `data-testid` string attribute, benign per the stated C rubric. The genuinely D-worthy lines in that neighborhood are :928/:1222 (Notifications banner, correctly filed as `FE-D-001`) — main doc already tags those two, specifically, as D. forkA's grouped citation conflates an adjacent benign identifier with the real defect. |
| `apps/web/src/components/agents/AgentConfigGrid.tsx` (multiple lines) | **B** throughout — honest `"planned"` status labels/gating, backend-derived | `INV-fe-014` note: **D "(backend-owned)"** — argues the *unbuilt backend* (Submission Agent, `backend: None`) is the real D item | **Not a disagreement about the frontend code — a scope note both source triages independently excluded on purpose.** `[VERIFIED THIS RUN]` `agents.py:190` confirms exactly one catalog entry has `"backend": None` (Submission Agent / browser-automation form-filling). The **frontend** half correctly rates the rendering as B (honest gating of a `"planned"` card). The **backend** half (input #1) does not list this as a D item either — it is a large net-new capability (a whole unbuilt agent), not a partially-wired existing feature, and both independent triage halves consciously excluded it as out of *this* triage's scope for that reason. forkA's flag is a reasonable observation but does not identify a defect either half missed; it is **not added to §2's actionable table** (roadmap/backlog item, not an incomplete-feature defect), and is recorded here so it is not silently dropped. |

### What this implies about confidence in A=0

The 2 resolved disagreements above both concern **B-vs-C boundary calls**, not A-vs-anything calls — neither
reading, anywhere, in either half, ever proposed an A (PROHIBITED-STUB) disposition for any line. The B/C
numeric spread (24/101 vs 32/91, a ~8-item swing) is best explained by forkA's more coarsely-grouped citation
style (multiple raw grep-hit lines folded into one narrative "id," as seen directly in the two disagreements
above) rather than by forkA finding genuine fabricated content the main doc missed — forkA's own dismissal
notes (its "Dismissals claimed (B)" and "(C)" sections) list the *same* files and the *same* honest-degrade
patterns (`coverLetterDegraded`, source-unavailable labels, `sourceStatus.ts`) the main doc independently
verified line-by-line. **Confidence in A=0 for the frontend half is HIGH**: two independent readings, a
targeted third-party spot-check in this merge pass, and zero A-disposition proposals from either source.
Confidence in A=0 for the backend half rests on a single reading only (no independent backend fork exists in
this run's inputs) — this is noted as a residual gap, not a finding; if a second backend reading is ever
produced, it should be checked against this same table format.

**No further disagreements require adversarial re-adjudication beyond what is resolved above** — both flagged
disagreements are closed in this pass with fresh file reads, not left open.

---

## 5. UNSURE register

Three items carried forward, each verified fresh in this merge pass where the underlying fact could be
freshly checked from static files, with an explicit recommended disposition and reasoning (not left as a bare
list).

### 5.1 `apps/web/src/lib/auth/next-auth-options.ts:19`

Both source readings agree on the underlying fact and just order it differently: a NextAuth `CredentialsProvider`
is live-mounted at `/api/auth/[...nextauth]`; `lookupUser()`/`verifyPassword()` unconditionally return
null/false (permanent stub, not an occasional honest degrade); a repo-wide `grep` for `next-auth/react`/`signIn`
call sites found **zero** — the actual working login (`POST /auth/login`, FastAPI + `localStorage` JWT) is a
fully separate system.

**Recommended disposition: D (INCOMPLETE-FEATURE / dead-code cleanup), LOW severity, owning workstream W-K.**
Reasoning: "unreachable, so it's safe to leave" is exactly the assumption that failed in `BLOCKER-001` (§6) —
that finding proves this codebase *can* ship a live, credential-checking auth surface nobody thought was
reachable, discovered only by an adversarial probe rather than a code-reading pass. A permanently-failing
credentials provider mounted at a real Next.js API route is not equivalent risk to BLOCKER-001 (it always
*fails* rather than always *succeeds*, so the direct exploit shape is different), but "no UI calls it today"
is not a security boundary — it is silent until someone (a scanner, a future developer wiring up `signIn()`,
or a security review) calls it directly. Recommend **deletion** over "finish it": the route handler,
`next-auth-options.ts`, and the `next-auth` dependency, since (a) zero product surface references it, (b) the
working JWT-based login is already the system of record, and (c) deleting a permanently-broken stub is
unambiguous and cheap, whereas finishing the abandoned Phase-2 persistence layer (per `DECISIONS.md` D-0006,
cited by the frontend triage) would be net-new scope with no identified product need. If an architecture owner
confirms NextAuth is still on a real roadmap, this becomes a real D item requiring the Phase-2 wiring instead.

### 5.2 `apps/api/app/routers/agents.py:384-392` — `PROVIDER_SEED` hardcoded openai/gemini/groq model lists

`[VERIFIED THIS RUN]` — fresh `grep` of the production `.env` this pass: `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
and `GROQ_API_KEY` are **all ABSENT**. (`OPENROUTER_API_KEY` and `ABACUS_API_KEY` are present; values not
read or logged — presence/absence checked only.)

**Recommended disposition: C (BENIGN-IDENTIFIER / dormant, confirmed for the CURRENT deployment), with a LOW
hygiene follow-up.** Reasoning: this closes the backend triage's own "Reading 2 (C, most likely)" with actual
evidence rather than inference — these three provider credential env vars are confirmed unset in production
today, so the providers panel cannot currently present them as connected, and `resolve_provider()`'s
`anthropic`/`openrouter`-only routing (per the backend triage's own citation, `llm_client.py:612-678`) means
no live code path calls them regardless. This is genuinely inert *today*. It is not risk-free forever: if an
operator ever sets one of those three keys (plausible — they are named, documented-looking env vars sitting
in the same `PROVIDER_SEED` structure as the two that *are* live), the providers panel would honestly show
"credential present" while dishonestly implying the listed models are servable — the exact "silent misrouting
across billing providers" class of bug `ADR-PC-2`/`GAP-P7-MODEL-CHOICE-001` was written to prevent, per the
backend triage's own cross-reference. **Proposed fix (LOW priority, hygiene):** either delete the
`openai`/`gemini`/`groq`/`bedrock` `PROVIDER_SEED` entries entirely (they are unservable by `resolve_provider`
regardless of credential state), or gate the providers panel's "connected" determination through the same
live-catalog validation `openrouter` already gets, so setting one of these three keys in the future cannot
silently misrepresent servability. Owning workstream: W-B (hygiene) / W-K.

### 5.3 `apps/api/app/services/stripe_gateway.py:37-40` — hardcoded `APP_BASE_URL` fallback

`[VERIFIED THIS RUN]` — fresh `grep` of the production `.env`: `APP_BASE_URL` is **ABSENT**. This means the
hardcoded literal (`"https://5cb5f0620.abacusai.cloud"`, `[VERIFIED THIS RUN]` re-read of the exact source
line) is **not a hypothetical fallback** — it is the live code path building every Stripe Checkout
success/cancel redirect URL in production right now. It happens to be currently correct (it matches this
deployment's actual production hostname), so there is no live incident today.

**Recommended disposition: D (INCOMPLETE — missing required env-var enforcement), MEDIUM severity (upgraded
from the backend triage's original "Low-severity, environment-config item" now that this pass has confirmed
the fallback is actively load-bearing, not merely theoretical), owning workstream W-K (infra/deploy) with a
W-B cross-reference for the code-level guard.** Reasoning: this is a real-money payment flow with zero
fail-fast protection — if this deployment is ever repointed to a new hostname (a custom domain, a redeploy,
disaster recovery to a new VM) without an operator remembering to also set `APP_BASE_URL`, every Stripe
checkout redirect silently reverts to the old hostname with no error, no log line, and no test that would
catch it before a real customer hits a broken post-payment redirect. **Proposed fix:** set `APP_BASE_URL`
explicitly in the production `.env` now (cheap, immediate, removes today's implicit coincidence), and add a
fail-fast guard analogous to `_guard_production_replay_mode` (`main.py:93-118`, already established in this
codebase) that refuses to boot with `AETHER_ENV=production` and `APP_BASE_URL` unset, removing the hardcoded
literal fallback entirely rather than leaving it as a silent safety net.

---

## 6. Explicit NOT-DEFECTS section

So no downstream agent "fixes" correct behavior, the following are affirmatively **not** defects and must not
be touched by W-B:

1. **The Seek "(unavailable)" label** (`apps/web/src/app/dashboard/jobs/page.tsx:854` and its backend source,
   `GET /agents/scout/sources/availability`). Truthful, backend-served (`source_availability()`,
   `adapter_registry.py:101-146`), and covered by a **binding risk-officer ruling this run that REFUSED
   enabling Seek** (`ADR-SEEK-FIRECRAWL.md`, STATUS: REFUSED; `GOLD-MASTER-V2-STATE.json` GOV-008: *"Do NOT
   remove the Jobs '(unavailable)' Seek label — it is truthful and backend-served."*). Do not file, do not
   propose removal, do not re-litigate.
2. **`AETHER_LLM_MODE=auto` with `_guard_production_replay_mode`** (`apps/api/app/main.py:93-118`). `[VERIFIED]`
   (both source triages independently re-confirmed by file read): the guard raises `RuntimeError` if
   `AETHER_LLM_MODE=replay` AND `AETHER_ENV=production`; only warns otherwise. Honest, correctly guarded — the
   comments explaining this pattern are exactly why "mock"/"fixture" keywords fire so often in otherwise-clean
   code (§1).
3. **The ~220 honest empty-state (B) items generally** (183 backend + 24 frontend-grep + the "Approval gate"
   toggle and the "planned" Submission Agent card from the frontend's item-2 sweep — 207 total B-dispositions
   across both halves). Every one is a real API-backed or backend-derived truthful state: `coverLetterUnavailable`
   degrade badges, source-unavailable labels, "Plan unavailable"/"Agent status unavailable" fallbacks on
   fetch failure, `"planned"` status gating for the one `backend: None` catalog entry. These are the *correct*
   behavior under this codebase's anti-fabrication policy and are the reason A=0 is achievable at all — they
   must not be "fixed" into fabricated/optimistic defaults.
4. **The "Approval gate" toggle** (`settings-client.tsx:871-888`, INERT-CONFIG-001 cluster, sibling of
   `FE-D-003`/`FE-D-004`). Explicitly **not** filed as a defect: its hint text states the real approval gate is
   *stricter* than the toggle ("Always enforced today ... regardless of this preference") — toggling it OFF
   cannot loosen the real safety gate. This is a fail-safe/conservative design, the opposite failure mode from
   `FE-D-003`/`FE-D-004` (which fail toward silent inaction, not toward an over-cautious default) — correctly
   dispositioned B, no fix needed.
5. **The `"Submission Agent" / "Planned"` roadmap card** (`AgentConfigGrid.tsx`, backend `agents.py:190`,
   `"backend": None`). Honest, backend-driven roadmap indicator, dimmed border, no Run/Toggle/model-picker
   controls — not a stub masquerading as functional. Both source triages independently excluded it from their
   D tables as a large net-new capability rather than a partially-wired existing one (§4 disagreement-table
   row 3); this merge pass concurs and does not add it to §2.

---

## 7. W-B execution order — priority sequence

**Item 0 is not a W-B item and is listed only so it is never mistaken for a lower priority than the items
below it.**

| Order | Item | Severity | Why here |
|---|---|---|---|
| **0 (cross-ref, outside W-B)** | `BLOCKER-001` — `admin`/`admin123` authenticates as the real owner account, `isAdmin:true`, 5/5 admin endpoints return 200 including other users' emails | **CRITICAL** | Already CONFIRMED by an independent verifier (input #6), already has its own dedicated remediation pipeline (`GOLD-MASTER-V2-STATE.json` §16, "interrupts other priorities"). Listed first purely so a reader of *this* document's execution order does not conclude W-B's own top item is the run's top priority overall — it is not. |
| **1** | `FE-D-003` — auto-apply persisted, never enforced | **BLOCKER** | False affordance (§3): interactive, savable, easy-to-miss disclosure, direct paying-user trust harm. |
| **2** | `FE-D-004` — match-threshold persisted, never enforced | **BLOCKER** | Same false-affordance reasoning as #1; ties for top of the W-B queue with it — implement together (both live in the same "Agent Configuration" settings tab and the same underlying `agentConfig` object). |
| **3** | `MERGED INC-B-002/FE-D-002` — email-verification toggle inert, unguarded at the API layer | **HIGH** | Honestly disclosed in the shipped UI (ranked below the false affordances for that reason — §3), but security-policy-adjacent, sibling toggle proves oversight not design, and the backend API-layer gap (zero validation on `emailVerificationEnabled`) is a genuine, unguarded control-plane hole even though the UI path is safe. |
| **4** | `FE-D-001` — Notifications tab "Coming Soon" | **HIGH** | Honestly disclosed and fully non-interactive (ranked below the false affordances), but every regular user passes through this exact screen, and it is the one item that most literally matches §4's named "Coming Soon" exit criterion. |
| **5** | `FE-D-005` — Pause All / Manual Override permanently disabled | **LOW** | Honest, niche monitor-panel controls; low reach, no data or trust implication. |
| **6** | `INC-B-001` — Stripe `trial_will_end` webhook bare `pass` | **LOW** | No UI surface at all; silent absence of a reminder email, not a rendered placeholder; does not affect billing accuracy. |

**Not sequenced into W-B (separate ownership, listed for completeness):**
- §5.1 `next-auth-options.ts` dead-code cleanup → recommend W-K.
- §5.2 `PROVIDER_SEED` hygiene → recommend W-B (hygiene) or W-K, LOW.
- §5.3 `APP_BASE_URL` fail-fast guard → recommend W-K (set the env var — trivial, do first) then W-B (add the
  guard code), MEDIUM.

**Coverage caveat repeated from §3, item 4:** this execution order is built from a keyword-grep-plus-targeted-
sweep methodology that is structurally better at finding *rendered* problems than *behavioral* ones. The two
BLOCKER items (`FE-D-003`/`FE-D-004`) were both found only by the manual, non-grep item-2 sweep, not by the
automated scan — which means the sweep methodology, not the keyword list, is what actually surfaces this
severity class. Any future re-run of this triage should treat the item-2-style manual sweep (disabled
controls, "saved but not enforced" hints, persisted-but-unread settings) as first-class, not a supplementary
afterthought, precisely because it is the only method that found the two items this document ranks highest.
