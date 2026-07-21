# INCIDENT — Production-wide client-side exception from an unrestarted `pnpm build` in the live-serving `apps/web` tree (2026-07-21)

**Severity:** SEV-1 (production frontend fully down — every screen). **Status:** RESOLVED. Root cause confirmed, fix applied and verified live, permanent process guardrail added (`docs/delivery/DEPLOYMENT-RUNBOOK.md` §0.3).

## What happened

The user reported: *"all UI screens are throwing `Application error: a
client-side exception has occurred (see the browser console for more
information)`."* This was not one broken screen — every route in the app
(public and dashboard) was affected simultaneously.

## Root cause

`aether-web.service`'s `next-server` process (production Next.js server,
`pnpm start`) had been running since 04:43 UTC that day. A fixer agent
working a billing-UX task was instructed to work "DIRECTLY in the main
working tree… NO worktree" (there is no isolated staging copy of `apps/web`
on this VM — §2 of the runbook) and, as its own verification step, ran
`pnpm build` twice (~07:36 and ~07:49 UTC) inside that same
`apps/web` directory. `next build` **deletes and regenerates**
`.next/static/` with new content-hashed chunk/CSS filenames on every
invocation. The already-running `next-server` process still had the OLD
build's route manifests/HTML templates loaded in memory and kept telling
every browser to fetch the OLD (now on-disk-deleted) chunk filenames —
guaranteeing a client-side chunk-load/hydration failure on literally every
route, since the JS bootstrap chunks are shared across all pages.

The fixer's own task instructions explicitly said "do not restart
services — orchestrator handles that," which is exactly why the mismatch
was left live: the build succeeded, `pnpm exec vitest run` and `pnpm build`
both reported green, and the task ended there with the server never
restarted to match. A second, independent `pnpm build` from a concurrent
parallel agent/session (working the same shared tree at the same time, per
this project's swarm-orchestration model) then raced in immediately after
the first restart landed and would have reproduced the exact same outage
again within seconds, had it not also happened to be followed by its own
restart moments later.

## Fix applied

`sudo systemctl restart aether-web.service` (documented `[SAFE]` in
runbook §3) — once for each of the two builds that had landed underneath
the running process.

## Verification

Curl-based checks alone are insufficient for this failure mode — Next's
server-rendered HTML looks completely normal even when the static assets it
links to 404 a moment later. Verification therefore checked BOTH:

1. Every key public page (`/`, `/pricing`, `/terms`, `/login`, `/signup`,
   `/privacy-policy`) against the real public HTTPS URL
   (`https://5cb5f0620.abacusai.cloud`, never `localhost` with a synthetic
   `Host:` header — that bypasses the real envoy ingress path) returns
   HTTP 200 with real body content and zero occurrences of "Application
   error" / "client-side exception" in the rendered HTML.
2. Every `_next/static/*` asset (JS chunk, CSS) that the served HTML itself
   references was independently re-fetched and confirmed to resolve HTTP
   200 — this is the check that actually catches the failure mode; check
   #1 alone would not have, since the exact symptom is server-rendered HTML
   that looks fine while linking to now-deleted static files.
3. `.next/BUILD_ID` was confirmed stable (unchanged across a re-check a few
   seconds apart) and no `pnpm build`/`next build` process was still
   running, before declaring the site stable.
4. An independent `evidence` agent additionally ran a real-browser
   (Playwright) sweep across public AND authenticated dashboard screens,
   capturing console errors and network 4xx/5xx on `_next/static/*` —
   see `uat/reports/evidence/payment-review/INCIDENT-2026-07-21-client-exception-verification/`
   for the artifact.

## Prevention (permanent)

Added `docs/delivery/DEPLOYMENT-RUNBOOK.md` §0.3: `pnpm build` must never
be run inside this VM's live `apps/web` directory without an
`aether-web.service` restart immediately following it in the same
task/session — regardless of what an individual task's own charter says
about who "owns" restarting. A task whose charter forbids restarting must
instead forbid running `pnpm build` in the shared tree at all (verify via
`tsc --noEmit` + lint + vitest only, and leave the actual `pnpm build` +
restart to whichever agent owns the deploy step, back-to-back, with no
other build racing in between).

## Scope note

This incident is orthogonal to the billing-UX fix (`PAY-R3-03/05/06` +
plan-switch UI) the fixer was implementing at the time — that work was
independently verified (498/498 vitest, clean `pnpm build`, adversarial
code review) and is unrelated to why the site broke. The site broke because
of *when/where* the verification build ran, not what was in it.
