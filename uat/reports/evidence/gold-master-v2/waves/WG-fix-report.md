# WG-fix-report — GOLD-MASTER-V2 §9.2 / §15 step 3: admin entry points

Fixer session, frontend-only. Repo: `/home/ubuntu/github_repos/aether-job-career-agent`
(no remote — local checkout only, not pushed). All timestamps UTC,
2026-07-31. Input: `uat/reports/evidence/gold-master-v2/waves/WG-NUL-failing-tests.md`
(test-author's fail-before evidence for the three target test files) + the
three test files themselves, none of which were modified.

---

## 1. Files changed

| File | Change |
|---|---|
| `apps/web/src/app/login/page.tsx` | Added a small "Admin sign in" entry link (`<a href="/admin-login">`) below the sign-in form, above `PublicFooter`. |
| `apps/web/src/app/admin-login/page.tsx` | **New.** Standalone admin sign-in page — identifier + password form, posts to the same `POST /auth/login`, then routes to `/admin`. |
| `apps/web/src/components/topbar.tsx` | Added a persistent "Admin" badge/link (→ `/admin`), shown only when the live `fetchMe()` call resolves `isAdmin: true`. |
| `apps/web/src/app/admin/layout.tsx` | Comment-only change (explains why the entry point deliberately lives at `/admin-login`, not nested under `/admin/*`). No functional change — still `AdminGuard` + `AdminShell` unconditionally, unchanged from HEAD. |

No `apps/api/**` file was touched. No file under `apps/web/src/app/dashboard/resume/**` or
`apps/web/src/lib/api/resumes.ts` was touched. `git status --short apps/web/` at the end of
this session shows exactly these four paths (three modified + one new directory) — confirmed
clean of any other agent's concurrent work in `apps/web`.

## 2. Exact copy/labels shipped

- **§9.2.1 entry link** (`/login`): visible text **"Admin sign in"**, `href="/admin-login"`,
  styled `text-[11px] text-aether-muted-dim hover:text-aether-muted` — same subdued register as
  the `PublicFooter` legal links immediately below it, deliberately smaller/quieter than the
  "Create account" link so it doesn't invite a normal user to click it.
- **`/admin-login` page**: heading **"Admin sign in"**, subtitle "Restricted to platform
  administrators.", fields labelled **"Email or username"** / **"Password"** (identical contract
  to `/login`), submit button **"Sign in"** (→ "Signing in…" while pending), footer link
  **"Back to sign in"** → `/login`.
- **§9.2.3 Topbar indicator**: a pill reading **"Admin"** (`aria-label="Admin — go to the admin
  portal"`), `href="/admin"`, rendered only when `isAdmin === true`; renders nothing otherwise.

## 3. Why `/admin-login`, not `/admin/login` — and why a plain `<a>`, not `next/link`

Two non-obvious defects surfaced while making the e2e spec genuinely pass (not just the two
vitest unit tests), both documented in the shipped code's own comments:

1. **Path choice.** `/admin/*` is wrapped end-to-end by `apps/admin/layout.tsx`'s `AdminGuard`,
   which immediately bounces an unauthenticated visitor to `/login` — nesting the sign-in form
   itself under that tree is a contradiction (the guard would fire before the visitor ever saw
   the form). Separately, `wg-admin-login-path.spec.ts` asserts the post-login redirect via
   `page.waitForURL(/\/admin(\/|$|\?)/, ...)`. Playwright resolves `waitForURL` **immediately**
   if the current URL already matches — so an entry page literally at `/admin/login` satisfies
   that regex (contains `"/admin/"`) the instant the visitor arrives, before the form is ever
   submitted, making the wait a no-op that passes on the wrong page. `/admin-login` still starts
   with `/admin` (satisfying §9.2.1 / `wg-admin-entry-004.test.tsx`'s own contract: `href.startsWith("/admin")` and `href !== "/login"`) without colliding with that pattern.
2. **`<a>` vs `<Link>`.** Diagnosed by hand (see §5, empirical reproduction below): a `next/link`
   client-side transition leaves the *old* page's DOM (and its identically-labelled "Email or
   username" / "Password" fields) resolvable for a brief window while the new route's RSC
   payload is fetched. A fast, machine-speed `fill()` + `click()` sequence (exactly what the
   Playwright spec does, with no artificial delay — which is also what a real fast typist could
   do) can race that transition and submit the *general* `/login` form instead of the admin one,
   silently landing an admin login on `/dashboard`. A real top-level navigation (`<a href>`)
   makes the browser tear down the old document before any further interaction is possible,
   closing that window. This is documented in `apps/web/src/app/login/page.tsx`'s own comment
   next to the link.

## 4. How admin status is derived (§9.2.3's "same source" requirement)

Both the Topbar indicator and `/admin-login`'s post-login destination rely on the **same, already
existing, live-per-request source**: `fetchMe()` in `apps/web/src/lib/api/admin.ts`, which calls
`GET /auth/me` and reads its `isAdmin` boolean — the exact function `admin-guard.tsx` already used
before this change. No new client-side flag was introduced, nothing is cached beyond the
component's own mount-scoped `useState`, and nothing was invented on the backend:

- `Topbar` now calls `fetchMe()` once per mount (alongside its existing `fetchSettings` /
  `fetchAgents` / `fetchApprovals` calls) and renders the "Admin" badge only while `isAdmin` is
  `true` for *that* live response; a failed/401/network-error call is treated as non-admin
  (matches the existing graceful-fallback pattern used by the other Topbar fetches — no new error
  surface).
- `/admin-login` does **not** decide admin status itself. It performs the exact same
  `POST /auth/login` as `/login` (via the same `login()` client in `lib/api/auth.ts`), stores the
  token under the same `aether_token` key, and always routes to `/admin`. `AdminGuard` — unchanged
  — is what resolves `isAdmin` live from `/auth/me` and silently redirects a non-admin to
  `/dashboard` with no admin-specific denial text. This is deliberate: a distinct "you are not an
  administrator" message would leak, to anyone trying a real non-admin account, that those
  credentials are valid (a user-enumeration-adjacent signal — exactly what
  `wg-admin-login-path.spec.ts`'s second test guards against).

## 5. Verification

### 5a. Target test files — before / after

**Before** (quoted from the test-author's own evidence,
`uat/reports/evidence/gold-master-v2/waves/WG-NUL-failing-tests.md`, run 2026-07-31T07:48–07:51Z
— not re-run by me since the brief says not to touch the tests and the author's fail-before
capture is already fresh/authoritative for this same HEAD):

```
$ cd apps/web && npx vitest run src/app/login/__tests__/wg-admin-entry-004.test.tsx
 FAIL  ... > exposes a clearly-labelled "Admin" entry point linking to an admin login path
TestingLibraryElementError: Unable to find an accessible element with the role "link" and name `/admin/i`
 Test Files  1 failed (1)
      Tests  1 failed (1)

$ cd apps/web && npx vitest run src/components/__tests__/wg-admin-indicator-006.test.tsx
 × ... > shows a persistent Admin indicator in the shell for a logged-in admin
AssertionError: ... expected null not to be null
 ✓ ... > shows NOTHING admin-related for a standard (non-admin) user
 Test Files  1 failed (1)
      Tests  1 failed | 1 passed (1)

$ npx playwright test wg-admin-login-path.spec.ts --project=chromium --no-deps --reporter=list
  ✘ an admin login reaches /admin (the real admin portal), not /dashboard
  ✘ a non-admin hitting the admin login path is refused honestly, with no user-enumeration signal
  2 failed
  (both: "no 'Admin' entry link found on /login")
```

**After** [VERIFIED-WITH-FRESH-EVIDENCE, run 2026-07-31T08:32:32Z]:

```
$ cd apps/web && npx vitest run src/app/login/__tests__/wg-admin-entry-004.test.tsx src/components/__tests__/wg-admin-indicator-006.test.tsx

 RUN  v2.1.9 /home/ubuntu/github_repos/aether-job-career-agent/apps/web

 ✓ src/components/__tests__/wg-admin-indicator-006.test.tsx (2 tests) 59ms
 ✓ src/app/login/__tests__/wg-admin-entry-004.test.tsx (1 test) 71ms

 Test Files  2 passed (2)
      Tests  3 passed (3)
```

Playwright e2e — run against an isolated local API+web pair mirroring the test-author's own
documented harness (own ports, own `aether_test`-schema fixture users created via direct
`POST /auth/register` + one SQL `UPDATE "User" SET "isAdmin"=true`, never the seeded `admin`
identifier per this assignment's CRITICAL warning). **Production build** (`next build && next
start`), not `next dev` — see §6 for why. Run twice, back-to-back, with fresh fixture users each
time, to confirm the pass is stable and not a fluke:

```
$ WG_E2E_BASE_URL=http://127.0.0.1:3095 WG_E2E_ADMIN_EMAIL=wg-admin-f7a91c2e0d@example.com \
  WG_E2E_USER_EMAIL=wg-user-3b6d5a10e2@example.com WG_E2E_PASSWORD=WgE2eTest1 \
  npx playwright test wg-admin-login-path.spec.ts --project=chromium --no-deps --reporter=list

Running 2 tests using 1 worker
  ✓  an admin login reaches /admin (the real admin portal), not /dashboard (1.4s)
  ✓  a non-admin hitting the admin login path is refused honestly, with no user-enumeration signal (2.6s)
  2 passed (4.7s)
```

Second independent run (new fixture users `wg-admin-2c918e4f77@…` / `wg-user-9a04f61bd3@…`):

```
  ✓  an admin login reaches /admin (the real admin portal), not /dashboard (1.5s)
  ✓  a non-admin hitting the admin login path is refused honestly, with no user-enumeration signal (2.5s)
  2 passed (5.0s)
```

[VERIFIED-WITH-FRESH-EVIDENCE, runs 2026-07-31T08:26–08:27Z]

Both isolated processes (uvicorn :8090, next start :3095) were torn down after verification;
confirmed via `ss -ltnp` showing neither port bound.

### 5b. Full FE suite

```
$ pnpm --dir apps/web test
 Test Files  90 passed (90)
      Tests  631 passed (631)
   Duration  120.22s
```

[VERIFIED-WITH-FRESH-EVIDENCE, run 2026-07-31T08:27:14–08:29:14Z]. Baseline stated in the brief
was 628 passed / 0 failed plus the 3 new W-G reds (1 in `wg-admin-entry-004`, 2 in
`wg-admin-indicator-006`) = 631 expected total once green. **Matches exactly. Zero regressions.**

### 5c. Typecheck

```
$ cd apps/web && npx tsc --noEmit
$ echo $?
0
```

[VERIFIED-WITH-FRESH-EVIDENCE, run 2026-07-31T08:24Z] — clean, no output, exit 0.

## 6. A genuine, non-obvious defect found and fixed along the way (not scope creep — required to make the e2e spec pass honestly)

Getting `wg-admin-login-path.spec.ts` to a real, stable pass (not just the two vitest unit tests)
surfaced two real bugs that would have shipped invisibly if I'd stopped at "the two component
tests are green":

1. The `next/link` vs. `<a>` race described in §3.2 above — fixed in the shipped code.
2. **`next.config.mjs`'s `AETHER_API_PROXY` rewrite is resolved at `next build` time for a
   production build**, not read live at `next start`. My first isolated-harness attempt built
   with the env var unset (defaulting the baked-in rewrite to `127.0.0.1:8000`, a pre-existing,
   unrelated backend already running on this VM) and only set `AETHER_API_PROXY=…:8090` at
   `next start` — which has no effect once the routes manifest is frozen. This produced a
   thoroughly confusing false signal (real `POST /auth/login` traffic silently going to the wrong
   backend, returning genuine-looking 401s for fixture users that only exist in the isolated
   `aether_test` schema) that I ran to ground with `curl -v`, direct backend comparisons, and
   inspection of `.next/routes-manifest.json`'s baked-in `destination`. This is a pure **test
   harness/environment** issue — `next.config.mjs` itself was not touched, and this has no
   bearing on production (which is built via `DEPLOYMENT-RUNBOOK.md`, which is not this session's
   concern). Rebuilding with `AETHER_API_PROXY` set for the `pnpm run build` step fixed it. Noted
   here for whoever next uses this isolated-harness pattern.

Separately, mid-verification the shared `aether_test` schema was truncated by a concurrent
agent's pytest run (consistent with the documented shared-test-DB flakiness on this project) —
one fixture-email's login briefly returned 401/429 for reasons unrelated to my code; resolved by
registering a fresh fixture identity and confirmed by the two independent stable passes in §5a.

## 7. Post-deploy behaviour while the credential is unrotated (per the CRITICAL instruction)

Nothing shipped here depends on the seeded `admin` identifier or any specific credential value.
`/admin-login` performs a generic `POST /auth/login`; `AdminGuard` (unchanged) and the Topbar's
`fetchMe()` call both resolve `isAdmin` **live**, per request, from `/auth/me`. Once
BLOCKER-001's fix (commit `6dcf927`) is deployed and the owner account's `isAdmin` is revoked:

- The **"Admin sign in" link on `/login`** keeps rendering unconditionally (it's a static
  route, not gated on identity) — this is correct: it is a navigation affordance, not a privilege
  grant.
- **`/admin-login` itself** keeps accepting a normal login for *any* valid account. If the
  authenticated account is not (or no longer) an admin, `AdminGuard` silently redirects to
  `/dashboard` — no error, no denial text, same behaviour as today for any non-admin.
- The **Topbar "Admin" badge simply stops rendering** for that account once its `isAdmin` flips
  to `false` on its next `/auth/me` read — no stale/cached "you're still an admin" state, because
  nothing is cached beyond the current mount.

This is the expected, correct behaviour post-deploy-and-rotation, not a bug: an admin entry point
existing is orthogonal to who currently holds the privilege.

## 8. Commit

`fix(ML-WG-ADMIN): add /login admin entry point + persistent Topbar Admin indicator (§9.2.1/§9.2.3)`
— not pushed, per instructions.
