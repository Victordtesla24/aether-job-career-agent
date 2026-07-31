# Frontend incomplete-feature triage — INDEPENDENT SOURCE A (orphaned fork)

**Provenance / trust caveat.** This table was produced by a sub-fork of the FIRST §4.1 triage agent, which
itself failed to write any artifact (GOV-009) and delivered this content only as a relayed peer message. It is
therefore **TESTIMONY, not [VERIFIED] evidence** under this run's epistemic rules. It is preserved here because
a second, independent frontend triage was dispatched separately; where the two agree on a file:line the
disposition is corroborated by two independent readings, and where they disagree the item goes to adversarial
re-adjudication. Nothing here closes a finding on its own.

Captured: 2026-07-30T23:5xZ · Scope: `apps/web/src/**` · Claimed coverage: all 128 frontend grep hits
Claimed counts: **A=0, B=32, C=91, D=4, UNSURE=1**

Dispositions: A = PROHIBITED-STUB (blocker) · B = HONEST-EMPTY-STATE (correct, do not "fix") ·
C = BENIGN-IDENTIFIER · D = INCOMPLETE-FEATURE

## Actionable items claimed (D + UNSURE) — these drive W-B

| id | file:line | disp | claim |
|---|---|---|---|
| INV-fe-001 | `apps/web/src/app/admin/settings/page.tsx:9` | D | Email-verification toggle is inert/read-only, handler is a no-op, no backend enforcement exists (ML-audit-emailverify-toggle-001) — feature unbuilt |
| INV-fe-012d | `apps/web/src/app/dashboard/settings/settings-client.tsx:923,928,1222` | D | Notifications tab: toggles disabled/no-op with explicit **"Coming soon"** copy — delivery unimplemented. §4 forbids any "Coming Soon" state at exit |
| INV-fe-014 (note) | `apps/web/src/components/agents/AgentConfigGrid.tsx` | D (backend-owned) | A single agent with `status="planned"` (Submission Agent, backend = None) is honestly disabled in the UI; the UNBUILT BACKEND is the real D item |
| INV-fe-034 | `apps/web/src/lib/auth/next-auth-options.ts:19` | **UNSURE** | `authOptions` IS mounted at the live `/api/auth/[...nextauth]` route, but `lookupUser()`/`verifyPassword()` always return null/false ("Phase 2" never landed), and no app code calls `next-auth/react` — real login goes directly to FastAPI `/auth/login`. Reading 1 → C (dead/orphaned, unreachable, fails safe). Reading 2 → D (a live mounted route shipping guaranteed-failing auth logic should be finished or removed) |

## Dismissals claimed (B — honest empty states, must NOT be "fixed")

`agents/page.tsx:515,517` (coverLetterDegraded → neutral "Unavailable", QA3-F-03) ·
`cover-letters/page.tsx:122,123,133` (honest missingResume / coverLetterUnavailable degrade) ·
`jobs/page.tsx:473,731,784,850,854` (source-unavailable label, backend-derived via `fetchSourceAvailability()`) ·
`settings-client.tsx:1049` (honest "Price unavailable") ·
`AgentConfigGrid.tsx:42,49,56,63,143,191,212,242,283` (honest disable/badge for `status="planned"` agents) ·
`Orchestration.tsx:63,115,313` (honest "N/A"/"unavailable (degraded)") ·
`MarketPulse.tsx:303` (honest "External market benchmark unavailable — Provider: none configured") ·
`dashboard/feed.ts:69,83,187` (coverLetterDegraded predicate + honest badge/feed text) ·
`sourceStatus.ts:36,45` (honest "unavailable (blocked by source)" pill, RT-008) ·
`sidebar.tsx:22,122,162` (honest "Plan unavailable"/"Agent status unavailable", loading vs null)

## Dismissals claimed (C — benign identifiers)

91 hits: HTML `placeholder=` input hint attributes (admin/users search, email compose, interviews forms, jobs
role/location filters, settings GitHub/portfolio/LinkedIn fields, AddOfferModal's 9 form fields, story-form,
topbar search, model-picker search boxes, ProviderConfigModal key-paste hints), Tailwind `placeholder:text-*`
class strings (login, signup), zod/TS enum members mirroring the real `"planned"` status, and comments that
DESCRIBE already-correct honest behaviour (several explicitly recording previously-fixed defects:
GAP-P4-068, MV-offer-comparison-001, MV-adv-resume-studio-006, MV-interview-center-001/2/3, SA-01).

One notable false-positive called out: `dashboard/feed.ts:202` — the word "planned" in ordinary past-tense
English prose ("planned the discovery → tailoring pipeline"), not a status marker.

## Orchestrator notes for the adversarial pass

1. **A=0 is a strong claim** and must not be accepted on one reading. The independent triage must confirm it.
2. The Seek `(unavailable)` label (INV-fe-008b) matches the binding risk-officer ruling (GOV-008): truthful and
   backend-served. **Do not remove it.**
3. INV-fe-012d ("Coming soon" in the Notifications tab) is the clearest §4 violation surfaced so far and is a
   BLOCKER regardless of which triage is correct.
4. INV-fe-034 must be resolved either way — a mounted auth route whose verification function always returns
   false is at best dead code (W-K) and at worst a half-wired auth surface (W-B).
