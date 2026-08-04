# ADR-F02 — User-scoped job discovery

**Status:** Implemented (frontend), with one backend residual escalated for an orchestrator ruling
**Date:** 2026-08-04
**Finding:** F-02 (MAJOR) — `docs/delivery/PROD-UAT-2026-08-03.md`
**Scope:** `/dashboard/jobs` "Sync Now", `/dashboard/agents` Scout "Run", results labelling

---

## 1. The defect

`apps/web/src/app/dashboard/jobs/page.tsx:616` posted a literal body for **every** user:

```ts
body: { query: "delivery lead, product owner, program manager, business analyst",
        location: "Australia" }
```

It never read the signed-in user's target role, location, or résumé. A NEW-FREE persona with a
Senior *Data Scientist* résumé and `targetRole: ""` received 1,621 project-management postings —
none scored, none filtered — under a heading that called them "matches".

Two independent failures, both of the same kind:

1. **A search that is not the customer's.** The headline feature of a job-search product ran
   somebody else's query.
2. **A label the system could not justify.** `stats.matches = all.length` counted every discovered
   row as a "match" regardless of whether anything had been scored against the user's résumé. The
   product's core promise is that it does not fabricate; asserting relevance it never measured is
   that failure in miniature.

## 2. What the query is derived from

Enumerated **before** designing (nothing new was invented; every source below already existed):

| Source | Where | Verdict |
|---|---|---|
| `targetRole`, `location` | `GET /auth/me` → `apps/api/app/routers/auth.py:176-199` | **Used.** The user's own profile columns, the same ones Settings > Profile writes and the topbar chip renders. |
| Résumé text | `ScoutAgent.run` → `require_user_resume_text` + `ATSEngine` (`apps/api/app/agents/scout_agent.py:98-119`) | **Already consumed server-side.** Every discovered posting is qualified against the user's real résumé there. Re-deriving a role from résumé prose in the browser would be a second, weaker guess at something the server already knows — so the frontend deliberately does not parse résumés. |
| Role-family broadening | `app/services/discovery/query_builder.build_scout_query` | **Left server-side.** A recognised role is broadened to its family by the same module that owns the matching regex, so the query and the filter can never disagree. The frontend sends the user's own wording, unwidened. |
| `_user_search_defaults` | `apps/api/app/routers/agents.py:1676-1705` | **Already existed and was unreachable from the UI** — `ScoutRunRequest` requires `query`/`location` (`min_length=1`), so a frontend-supplied value always won. This is why the hardcode existed at all. |

Derivation now lives in one place: **`apps/web/src/lib/discovery/search-target.ts`**.

Its defining property is that **it owns no query of its own**. There is no constant in the module to
fall back to, so "the user told us nothing" can only resolve to `needs-input` — a question — never to
a search. Reintroducing a default requires adding the literal to that file, where
`search-target.test.ts` asserts against exactly that.

`fetchMe` (`apps/web/src/lib/api/admin.ts`) — already the app's canonical `/auth/me` client, used by
the topbar and the AdminGuard — now also parses `targetRole` and `location`. Additive and
backward-compatible (`.optional().default("")`); the API has always returned both fields, the client
simply discarded them.

## 3. The empty-profile decision

**Decision: ask the user. Never substitute, never run.**

When the profile carries no target role and/or no location, "Sync Now" opens an inline prompt
(`data-testid="discovery-target-prompt"`) that states plainly that nothing is configured, asks for a
role and a location, and links to Settings for a permanent answer. No request is issued until the
user supplies both. A half-filled prompt is refused with a message naming the missing half, not
completed with a guess.

A failed `/auth/me` lookup resolves to the **same** path — `deriveSearchTarget(null)` is
`needs-input`. Not knowing what the customer wants and guessing wrong are the same outcome for them,
so an infrastructure failure must not silently become a fabricated search.

Rejected alternatives:

- *Fall back to the role family (`ROLE_FAMILY_QUERY`).* This is precisely the defect — it is how a
  data scientist got project-management postings. It is also what the backend still does; see §6.
- *Fall back to a résumé-derived guess.* Better than a constant, but still an assertion the user
  never made, and it would duplicate server-side logic in a weaker form.
- *Disable "Sync Now" until Settings is filled in.* Honest but hostile: a new user's first click
  would do nothing with no route forward. The prompt keeps them moving while keeping the search
  theirs. (Settings' own "Sync All" already uses the disable-with-tooltip variant —
  `settings-client.tsx:405` — which is why that call site was never defective.)

Additionally, whenever the target *is* known the screen states it outright
(`data-testid="discovery-search-target"`): *"Sync Now searches for **X** in **Y** — from your
profile."* So the second option in the finding's remit ("state plainly what is being searched and
why") is satisfied in the normal case too, not only the empty one.

## 4. The labelling change

`stats.matches = all.length` → three separately-counted populations:

```
{total} discovered · {scored} scored against your résumé · {unscored} not yet scored
  · {newToday} new today · {sources} sources connected
```

A "match" claim requires a fit score behind it. The scored/unscored split uses `fitScore != null` —
the same test `apps/web/src/app/dashboard/page.tsx:194` already treats as "scored" — so the Jobs
screen now agrees with the dashboard, the "not measured" vocabulary in Resume Studio and the Cover
Letter quality panel, and the withheld-score handling already present on this page.

## 5. Other instances of the same hardcode

Item 4 of the remit. Findings, in order of severity:

| # | Site | Literal | Status |
|---|---|---|---|
| 1 | `apps/web/src/app/dashboard/jobs/page.tsx:616` | `"delivery lead, product owner, program manager, business analyst"` / `"Australia"` | **Fixed.** |
| 2 | `apps/web/src/app/dashboard/agents/page.tsx:83` (`RUN_PARAMS.scout`) | `"software engineer"` / `"Australia"` | **Fixed.** A *second, different* persona sent for every customer pressing Run on the Scout card. Fixing only the line the UAT happened to click would have left the product still searching for the wrong job. |
| 3 | `apps/api/app/routers/agents.py:2703-2704` (`PipelineRunRequest`) | `_DEFAULT_QUERY` (= `ROLE_FAMILY_QUERY`) / `"Melbourne, Australia"` | **NOT fixed — escalated, see §6.** |
| 4 | `apps/api/app/routers/agents.py:89-90` + `query_builder.ROLE_FAMILY_QUERY` | the 10-term PM/BA family / `"Melbourne, Australia"` | **NOT fixed — escalated, see §6.** |
| 5 | `scripts/discovery_cron.sh:105-106` | `"Senior Technical Program Manager"` / `"Melbourne, AU"` | **NOT fixed.** Reads `/auth/me` first and only falls back if the operator's own account has no target role. Single-account operator tooling, lower blast radius, but it is the same pattern. |
| — | `apps/web/src/app/dashboard/settings/settings-client.tsx:426` | none | **Already correct.** Sends `profile.targetRole` / `profile.location` and gates the button on both being non-empty with an honest tooltip (`:405`). Precedent for the design above. |

## 6. Residual escalated for an orchestrator ruling

**The Agents console's "Run All" (pipeline) is still a live route to the original defect.**

`runPipeline()` posts `body: {}` (`apps/web/src/lib/api/agents.ts:128-135`). `PipelineRunRequest`
materialises its pydantic defaults, so `_pipeline_core` calls
`_dispatch(user_id, "scout", {"query": ROLE_FAMILY_QUERY, "location": "Melbourne, Australia"})`.
Because `params.get("query")` is then truthy, `_user_search_defaults` — the profile-derived helper
that already exists — is **never consulted**. Every user's "Run All" therefore scouts the hardcoded
PM/BA family in Melbourne, exactly as "Sync Now" used to.

Not fixed unilaterally, for two stated reasons:

- The hardcode is a **backend default**, not a frontend body. Patching only the frontend would paper
  over a default that the async worker enqueue path and any other API consumer still hit.
- `apps/api/app/routers/agents.py` carries another session's uncommitted work, and `_DEFAULT_QUERY` /
  `_user_search_defaults` also feed the discovery cron. Changing shared dispatch-default semantics is
  orchestrator territory under this run's standing rules.

Two defensible readings, both recorded:

- **(a) Same defect, fix it.** "Run All" is user-facing and pollutes the same `Job` table with the
  same junk rows. Recommended shape: make `PipelineRunRequest.query`/`.location` `None`-defaulted so
  `_user_search_defaults` runs, **and** decide what an empty profile should do there (today it would
  reach `ROLE_FAMILY_QUERY` and re-fabricate — the honest answer is a 422 naming the missing profile
  field, mirroring the frontend prompt).
- **(b) Out of scope for F-02.** The finding named the "Sync Now" call site; "Run All" is a separate
  feature whose refusal behaviour is a product decision.

Consequence of leaving it: the junk-row source is narrowed, not closed. A user pressing "Run All"
still gets unfiltered PM postings written to their account.

**Related, same ruling:** `_user_search_defaults` falls back to `ROLE_FAMILY_QUERY` for any user with
an empty `targetRole`. The frontend can no longer reach that path, but nothing else stops it. The
frontend and backend now disagree about what "no target role" means — the frontend asks, the backend
substitutes.

## 7. Tests

Fail-before / pass-after evidence: `uat/reports/evidence/models-live/F-02/`.

| Test | Proves |
|---|---|
| `apps/web/src/lib/discovery/__tests__/search-target.test.ts` (10) | Derivation is the user's own; two users differ; **every** empty-profile shape resolves to `needs-input` — the exhaustive case is the guard against a "sensible default" returning. |
| `apps/web/src/app/dashboard/jobs/__tests__/f02-user-scoped-discovery.test.tsx` (11) | Body derived from *this* user; the delivery-lead persona is never sent; two users produce two searches; empty profile issues **no** request and asks instead; a half-filled prompt does not run; a failed profile lookup asks rather than guesses; scored/unscored counted separately and never called "matches". |
| `apps/web/src/app/dashboard/agents/__tests__/f02-scout-run-params.test.tsx` (2) | Scout's Run uses the profile, not `"software engineer"`; an empty profile is refused honestly with a Settings CTA and `runAgent` is never called. |

23 targeted tests: **13 failed before / 23 pass after** (the 10 derivation tests could not collect
before — the module did not exist). Full web suite after: **117 files, 813 tests, 0 failures**.
`pnpm --dir apps/web lint` and `type-check` both clean. No backend files were changed, so no `ruff`
or `pytest` run was required.
