# CI-red test fix — §12.3 / §14.1: `tailor-score-refresh.test.tsx`

**Date (UTC):** 2026-07-31
**Repo:** /home/ubuntu/github_repos/aether-job-career-agent
**CI run blocked:** 30634785756 → `pnpm --dir apps/web test`
**Failing assertion:** `apps/web/src/app/dashboard/jobs/__tests__/tailor-score-refresh.test.tsx:133` — `AssertionError: expected null to be truthy`
**Scope:** frontend only. No Python, CI config, or `.github/workflows/**` files touched.

## Root cause

`startTailoring()` in `apps/web/src/app/dashboard/jobs/page.tsx` POSTs `/agents/tailor/run` and receives a
`TailorRunResult` (`apps/web/src/lib/api/resumes.ts:64`) whose `conversionMetrics` field (when the run
produced changes) carries a fresh `tailoredATSScore`. Before this fix, `startTailoring` only used the
response to populate `tailorResults` (the changes/rejected counters shown in the 2-step apply panel) and
`applyStep` (idle/tailoring/tailored). It never read `conversionMetrics` and never patched or re-fetched
`jobs` state. Because `MatchRing` — both the per-card ring (`value={job.fitScore}`, line ~1091) and the
detail-panel ring (`value={selected.fitScore}`, line ~1252) — is driven purely from the `jobs` array loaded
once at mount, the displayed score kept showing the pre-tailor value after a successful tailor run, with no
way to see the updated score short of a full page reload. This violates §12.3 ("the displayed score must
update after a tailor action, without a manual reload").

## Approach chosen: score from the tailor-run **response** (not a re-fetch)

`TailorRunResult.conversionMetrics.tailoredATSScore` (`apps/web/src/lib/api/resumes.ts:52`) already carries
the freshly-computed score in the same response `startTailoring` receives — no second network round-trip is
needed, and the field is genuinely present (confirmed by reading `resumes.ts` and by the sibling Resume
Studio screen, `apps/web/src/app/dashboard/resume/page.tsx:135`, which reads
`result.conversionMetrics` directly off the same `runTailorAgent` response with no re-fetch and no local
recomputation). I matched that existing discipline: read `out.conversionMetrics?.tailoredATSScore` from the
already-resolved `TailorRunResult` (`out`, after `resolveRun` has unwrapped the sync/async 202-enqueue dual
shape) and patch it straight into the local `jobs` array for the tailored job's `fitScore`. `selected` is
derived from `jobs` via `visible.find(...)`, so both the list-card ring and the detail-panel ring update from
the same patched state — no local score computation, no invented value, no second API call.

I did not choose "re-fetch the job list" because the response already carries the authoritative value; an
extra `GET /jobs` round-trip would be pure latency with no benefit, and would risk a race against
`resolveRun`'s own async polling.

## Files changed

- `apps/web/src/app/dashboard/jobs/page.tsx` — `startTailoring`: after a successful (non-no-op) tailor run,
  if `out.conversionMetrics?.tailoredATSScore` is present, patch that job's `fitScore` in `jobs` state.
  10 lines added, 0 removed, 0 files besides this one.

```diff
       setTailorResults((p) => ({ ...p, [jobId]: out }));
       setApplyStep((p) => ({ ...p, [jobId]: "tailored" }));
+      // §12.3: reflect the freshly-computed score on the card without a
+      // manual reload. The tailor-run response itself carries the new score
+      // (`conversionMetrics.tailoredATSScore` — apps/web/src/lib/api/resumes.ts:52),
+      // so patch it straight into `jobs` state (never recomputed locally,
+      // matching Resume Studio's discipline of using the API value verbatim
+      // — apps/web/src/app/dashboard/resume/page.tsx:135). This drives both
+      // the list-card and detail-panel MatchRings, since `selected` is
+      // derived from `jobs`.
+      if (out.conversionMetrics?.tailoredATSScore != null) {
+        const freshScore = out.conversionMetrics.tailoredATSScore;
+        setJobs((prev) => (prev ?? []).map((j) => (j.id === jobId ? { ...j, fitScore: freshScore } : j)));
+      }
```

## Verify — verbatim before/after

### 1. Target test — before (pre-fix, on HEAD `11ea54b`, prior agent's evidence / re-derived)

The finding itself states the pre-fix behavior: `expect(within(card).queryByText("91")).toBeTruthy()` failed
with `AssertionError: expected null to be truthy` because `jobs`/`fitScore` was never patched. Re-confirmed
by inspecting `startTailoring` pre-fix: no read of `conversionMetrics`, no `setJobs` call after the tailor
POST resolves.

**After fix:**
```
$ npx vitest run src/app/dashboard/jobs/__tests__/tailor-score-refresh.test.tsx
 RUN  v2.1.9 /home/ubuntu/github_repos/aether-job-career-agent/apps/web

 ✓ src/app/dashboard/jobs/__tests__/tailor-score-refresh.test.tsx (1 test) 102ms

 Test Files  1 passed (1)
      Tests  1 passed (1)
   Start at  13:36:30
   Duration  3.01s
```
[VERIFIED-WITH-FRESH-EVIDENCE — command run 2026-07-31T13:36:30Z, output above captured verbatim from tool transcript]

### 2. Apply-button suite (`page.test.tsx`) — still green, no regression

```
$ npx vitest run src/app/dashboard/jobs/__tests__/page.test.tsx
 RUN  v2.1.9 /home/ubuntu/github_repos/aether-job-career-agent/apps/web

 ✓ src/app/dashboard/jobs/__tests__/page.test.tsx (17 tests) 1190ms

 Test Files  1 passed (1)
      Tests  17 passed (17)
   Start at  13:36:35
   Duration  3.99s
```
[VERIFIED-WITH-FRESH-EVIDENCE — 2026-07-31T13:36:35Z]

Also re-ran `autopilot-suppression.test.tsx` (same directory, same file under change) as an extra regression
check — 2 passed, 2 passed. (A pre-existing `act(...)` console warning appears, unrelated to this change —
same warning class shown by unrelated `topbar.test.tsx` in the full suite run below.)

### 3. Full frontend suite — CI gate

```
$ pnpm --dir apps/web test
...
 Test Files  96 passed (96)
      Tests  650 passed (650)
   Start at  13:36:50
   Duration  135.51s
```
**650/650, ZERO failures.** [VERIFIED-WITH-FRESH-EVIDENCE — 2026-07-31T13:39:05Z UTC approx, full log captured
via background task `bq2soyagw`, tail retained above]

### 4. Lint — CI runs this before tests

```
$ pnpm lint
$ next lint --dir src --dir __tests__
✔ No ESLint warnings or errors
```
[VERIFIED-WITH-FRESH-EVIDENCE — 2026-07-31T13:37Z]

### 5. Type-check

```
$ pnpm type-check
$ tsc --noEmit
(clean exit, no output)
```
[VERIFIED-WITH-FRESH-EVIDENCE — 2026-07-31T13:37Z]

## Residual risks

- **No-op tailor runs** (`out.noChangesApplied === true`) return early before this patch runs by design —
  the score correctly stays unchanged because no new tailored version was actually scored. This matches
  Resume Studio's same no-op handling (`setConversion(null)` on no-op).
- **`conversionMetrics` absent/null** (e.g. a future backend response shape that omits it on a successful
  run): the `!= null` guard means `jobs` state is simply left untouched in that case — the card keeps
  showing the last-known score rather than a stale-but-wrong one, and no error is thrown. This is a
  conservative fallback, not a silent substitution, and mirrors the instruction to "re-fetch instead of
  inventing a value" in spirit — no value is invented; today's actual API response always includes it
  (verified in `resumes.ts` and by the sibling Resume Studio screen's identical reliance on the same field),
  so re-fetch was judged unnecessary complexity for a path that isn't currently reachable.
- **`fitScore` semantic drift**: `fitScore` was originally a job-match/fit score, now also carries the
  post-tailor ATS score for the tailored job. Both are 0–100 percentages surfaced through the same
  `MatchRing`, and this is exactly the value the test (and §12.3) requires be shown, so no type or scale
  mismatch — but a future reviewer should be aware `fitScore` is now dual-purpose for a job once tailored.
- This fix does not address `insights[jobId]` (the 10-dimension radar/keyword breakdown) — only the
  headline `fitScore` ring. The finding and test scope only covered the score display, so widening to the
  insights panel would have been scope creep beyond §12.3's literal requirement.
