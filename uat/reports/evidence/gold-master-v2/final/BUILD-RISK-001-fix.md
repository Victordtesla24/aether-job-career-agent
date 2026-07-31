# BUILD-RISK-001 — stale `/api/*` rewrite in the on-disk Next build (FIXED, pre-deploy)

**Phase:** GOLD-MASTER-V2, blocking pre-deploy fix
**Agent:** fixer-hard (serial, no sub-agents)
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Work window:** 2026-07-31T12:51Z → 2026-07-31T13:09Z
**Service restarted:** **NO.** `aether-web.service` PID 234331 is still the process started
2026-07-30T12:27:09Z. Verified after every destructive step. [VERIFIED]

---

## 1. The mechanism

`apps/web/next.config.mjs:12-13` resolves the `/api/*` proxy upstream from a **build-time**
environment variable:

```js
async rewrites() {
  const apiOrigin = process.env.AETHER_API_PROXY ?? "http://127.0.0.1:8000";
  return [{ source: "/api/:path*", destination: `${apiOrigin}/:path*` }];
},
```

- **Offending variable:** `AETHER_API_PROXY`
- **Precise expression:** `process.env.AETHER_API_PROXY ?? "http://127.0.0.1:8000"`
- **Not a hardcode, not a default gone wrong.** The `??` default is correct (`:8000`). The
  poison came from the variable being *exported in the shell that ran `pnpm build`*.

### Where `8090` came from — it is nowhere in the repo

```
$ grep -rn "8090" . | grep -v node_modules | grep -v /.next/ | grep -v ^./.git/
docs/delivery/GOLD-MASTER-V2-STATE.json     # only the finding record itself
$ grep -rn "AETHER_API_PROXY" . | grep -v node_modules | grep -v ^./.git/
docs/delivery/GOLD-MASTER-V2-STATE.json:707 # the finding record
apps/web/next.config.mjs:12                 # the read site
```
[VERIFIED 2026-07-31T12:51Z]

`AETHER_API_PROXY` is absent from the repo-root `.env`, absent from `apps/web/` (there is no
`.env*` there at all), absent from the `aether-web.service` unit (`Environment=` is empty),
and absent from `start-web.sh`. [VERIFIED 2026-07-31T12:52Z]

**Conclusion: it was exported interactively in the shell that produced the 08:25 build.**

### The recurrence vector — `apps/web/playwright.config.ts`

```ts
webServer: {
  command: "pnpm run build && pnpm exec next start -p 3000",
  reuseExistingServer: !process.env.CI,
}
```

Running Playwright in this tree **builds into the live `.next`** and then *reuses the running
production server* as the test target. Any e2e run with a sandbox `AETHER_API_PROXY` exported
leaves a restart-fatal artefact behind. This is consistent with the runbook's existing §0.3
incident (`INCIDENT-2026-07-21-web-build-clobber.md`) and is the most likely provenance of the
08:25 build. [INFERRED — the shell history itself is not recoverable; every other candidate
source was eliminated above]

---

## 2. Does `next start` read the built manifest, or re-evaluate the config at boot?

**It reads the BUILT manifest. The config is NOT re-evaluated at boot. A rebuild is therefore
mandatory — correcting the environment alone would have fixed nothing.**

Static evidence — `node_modules/next/dist/server/next-server.js:1136`:
```js
getRoutesManifest() {
    return getTracer().trace(NextNodeServerSpan.getRoutesManifest, ()=>{
        const manifest = loadManifest(join(this.distDir, ROUTES_MANIFEST));
```

### PROOF-A — empirical, against the poisoned 08:25 build [VERIFIED 2026-07-31T12:54:57Z]

A marker HTTP server was bound to the "dead" port so the two outcomes are distinguishable:

```
$ curl -s http://127.0.0.1:8090/health
{"marker":"DEAD-PORT-8090-REACHED","path":"/health"}
```

Then `next start` on a spare port with the variable **explicitly unset**:

```
$ env -u AETHER_API_PROXY NODE_ENV=production npx next start -p 3999
  ▲ Next.js 14.2.35   ✓ Ready in 1547ms
$ env -u AETHER_API_PROXY bash -c 'echo "${AETHER_API_PROXY:-<UNSET>}"'
<UNSET>

$ curl -s http://127.0.0.1:3999/api/health
{"marker":"DEAD-PORT-8090-REACHED","path":"/health"}
$ curl -s http://127.0.0.1:3999/api/v1/whatever
{"marker":"DEAD-PORT-8090-REACHED","path":"/v1/whatever"}
```

With the variable unset, the server **still** proxied to `:8090`. The value is frozen in the
artefact. Only a rebuild clears it.

*(This probe ran on port 3999 against the same `.next` read-only; production PID 234331 was
confirmed unchanged immediately afterwards.)*

---

## 3. The rebuild

### Exact command [VERIFIED 2026-07-31T12:57:06Z → 12:59:45Z, exit 0]

```bash
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/web
rm -rf .next
env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm build
```

`env -u` was used rather than mutating the shell, per instruction. `NEXT_PUBLIC_API_BASE_URL`
was unset as well — see §5 for why it belongs in the same clean-env fence.

The pre-fix `.next` (215 MB, the poisoned 08:25 artefact) was archived first to
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/next-backup-8090-build`
so the exact prior state is recoverable and so the new gate could be proven against it (§6).

Build result: exit 0, 2m39s, 33 routes emitted, new `BUILD_ID` `InSs8pBEYhoXkWmagLNDF`.

### BEFORE — verbatim [VERIFIED 2026-07-31T12:55:33Z]

```
$ grep -o '"destination":"http://127.0.0.1:[0-9]*/:path\*"' apps/web/.next/routes-manifest.json
"destination":"http://127.0.0.1:8090/:path*"
```
```json
[
  {
    "source": "/api/:path*",
    "destination": "http://127.0.0.1:8090/:path*",
    "regex": "^/api(?:/((?:[^/]+?)(?:/(?:[^/]+?))*))?(?:/)?$"
  }
]
```

### AFTER — verbatim [VERIFIED 2026-07-31T12:59:55Z]

```
$ grep -o '"destination":"http://127.0.0.1:[0-9]*/:path\*"' apps/web/.next/routes-manifest.json
"destination":"http://127.0.0.1:8000/:path*"
```
```json
[
  {
    "source": "/api/:path*",
    "destination": "http://127.0.0.1:8000/:path*",
    "regex": "^/api(?:/((?:[^/]+?)(?:/(?:[^/]+?))*))?(?:/)?$"
  }
]
```

```
$ grep -rl "127.0.0.1:8090" apps/web/.next/
NONE
$ grep -o '.\{40\}127\.0\.0\.1:[0-9]*.\{25\}' apps/web/.next/required-server-files.json
ce":"/api/:path*","destination":"http://127.0.0.1:8000/:path*"}],"fallback":[]}
```

**The poison was in TWO files, not one** — `routes-manifest.json` *and*
`required-server-files.json` (`$.config._originalRewrites.afterFiles[0]`). A gate that checked
only `routes-manifest.json` would have been incomplete; the new gate checks both.
(A third grep hit, `prerender-manifest.json`, was a **false positive** — `8090` appears inside
the hex string `...ed9b0ec8090bdadd...` of `previewModeSigningKey`. Not pollution.)

### PROOF-B — the fix actually routes to the live API [VERIFIED 2026-07-31T13:00:26Z]

The marker server was **left listening on 8090** so a regression could not hide:

```
$ curl -s http://127.0.0.1:8090/health           # marker still up
{"marker":"DEAD-PORT-8090-REACHED","path":"/health"}

$ env -u AETHER_API_PROXY NODE_ENV=production npx next start -p 3999   # NEW build
$ curl -s http://127.0.0.1:3999/api/health
{"status":"ok","version":"0.2.0"}
$ curl -s http://127.0.0.1:8000/health           # direct, for comparison
{"status":"ok","version":"0.2.0"}
```

Identical to the real API and *not* the marker. Both probe processes were then killed **by
PID** and ports 3999/8090 confirmed free.

> **Process note worth recording:** an early cleanup attempt used
> `pkill -f "next start -p 3999"`, which **self-matched the invoking shell** and killed it
> (exit 144) — the exact hazard runbook §0.2 item 2 warns about. Production was immediately
> verified unaffected (PID 234331, start time unchanged) and cleanup was redone with
> PID-targeted `kill`. No production impact. [VERIFIED 2026-07-31T12:55:14Z]

---

## 4. Production was never touched

| Check | Result | Timestamp |
|---|---|---|
| `aether-web.service` `ExecMainPID` | `234331` (unchanged) | 12:52 / 12:55 / 13:00 |
| `ExecMainStartTimestamp` | `Thu 2026-07-30 12:27:09 UTC` (unchanged) | 12:52 / 12:55 / 13:00 |
| `ActiveState` | `active` | throughout |
| `https://5cb5f0620.abacusai.cloud/login` | HTTP 200, 0 × "Application error" | 12:53, 12:59 |
| `/dashboard`, `/dashboard/jobs` | HTTP 200, 0 × "Application error" | 12:53, 12:59 |
| every `_next/static/*` referenced in those pages | all HTTP 200 (no 404s) before **and** after the rebuild | 12:53, 12:59 |
| 11-route sweep (`/`, `/login`, `/signup`, `/pricing`, `/dashboard`, `/dashboard/{jobs,resume,applications,agents,settings}`) | all HTTP 200, 0 × "Application error", **0 asset misses** | 13:07 |

The single non-200 in that sweep was `/admin-login` → HTTP 404, which is **pre-existing
staleness, not rebuild damage**: that route was added at 08:34Z, after the running process
booted. It is present and correct in the new on-disk build (see §5 item 3).

The §0.3 asset-clobber check was run deliberately across the rebuild because `rm -rf .next`
regenerates content-hashed chunks. It came back clean on both sides. `.env` was **not**
modified — no change to it was required. The production database was not touched.

---

## 5. Stale-build assessment — clean rebuild was warranted, and was done

**Recommendation: full clean `rm -rf .next && pnpm build`. This was performed, not just
recommended.** Rationale:

1. **The running process predates the tree by 70 commits.** The web process booted at
   2026-07-30T12:27:09Z, last commit at/before that being `e453032`. Between `e453032` and
   `HEAD` there are 70 commits, and `apps/web/src` alone changed by
   **25 files, +1770 / −33** — including a new `usePolling` hook, topbar changes, and
   `lib/api/resumes.ts`. The deploy is a genuinely large delta. [VERIFIED 13:04Z]
2. **`.next/cache` (210 MB) was produced under the same polluted session.** Webpack's
   filesystem cache is content-addressed and normally safe to keep — **but it caches compiled
   modules with `process.env.*` already inlined.** `apps/web/src/lib/api/client.ts:17` reads
   `process.env.NEXT_PUBLIC_API_BASE_URL`, which is a compile-time inline, therefore cacheable,
   therefore a second poisonable channel independent of the rewrite. Keeping that cache would
   have meant reasoning probabilistically about a gold-master artefact. It was deleted.
3. **Direct proof the running process is stale, independent of the manifest.** `/admin-login`
   was added by `2bdb060` at 2026-07-31T08:34:19Z. It exists in the new on-disk build
   (`.next/server/app/admin-login.html`) and in source (`apps/web/src/app/admin-login/page.tsx`),
   but **production returns HTTP 404 for it right now**. The running process's route table, like
   its rewrite table, was loaded once at boot and never refreshed. [VERIFIED 13:07Z]
4. **The blast radius of the pollution was verified as bounded before deciding** — exactly 2
   real occurrences, both in server manifests; the client bundle contained no absolute API
   origin at all (`grep -rl "127.0.0.1:8000" .next/static/` → empty), i.e.
   `NEXT_PUBLIC_API_BASE_URL` was *not* set during the 08:25 build and the browser bundle
   correctly uses the same-origin `/api` path. So the client bundle was never poisoned — but
   that was established by measurement, not assumption.

Nothing else in `.next/` looked environment-polluted.

### Important caveat for W-L

My rebuild (12:57:06Z) is **newer than the newest `apps/web` commit** (`ceba5e2`, 12:52:21Z)
and the `apps/web` working tree is clean, so the current on-disk build is correct *as of now*.
[VERIFIED 13:04Z] **However, this is a shared live tree with concurrent sessions** — `HEAD`
moved from `57f56ff` to `ceba5e2` during this very task. The W-L deploy must still run its own
Phase 3 build after its `git pull`, followed by the Phase 3b gate. **Treat my build as proof of
the fix and a safe interim state, not as a substitute for the deploy's own build.**

---

## 6. The permanent control — `scripts/verify-web-build.sh`

**Path:** `/home/ubuntu/github_repos/aether-job-career-agent/scripts/verify-web-build.sh`

What it asserts:

1. **Check 0** — refuses to run if `AETHER_API_PROXY` is exported in the invoking shell with a
   non-default value (that shell would poison the *next* build).
2. **Check 1** — a complete build exists (`routes-manifest.json`, `required-server-files.json`,
   `BUILD_ID`, `static/`).
3. **Check 2** — walks **both** manifests generically and asserts every absolute `/api/*`
   rewrite destination targets `http://127.0.0.1:8000`. It **fails if it found zero rewrites to
   check**, so a future Next upgrade that changes the manifest shape fails loudly instead of
   silently verifying nothing.
4. **Check 3** — belt-and-braces `grep` for any other `http://127.0.0.1:<port>` in either
   manifest.

**Design decision:** the expected upstream is **hardcoded**, not read from `AETHER_API_PROXY`.
A gate that trusted the same environment that poisoned the build would validate the poison. An
explicit CLI argument (never an env var) overrides it for non-production use.

### Fail-before / pass-after [VERIFIED 2026-07-31T13:01:43Z and 13:01:54Z]

**PASS-AFTER — against the rebuilt `.next`:**
```
[web-build-gate] OK: 2 /api/* rewrite destination(s) target http://127.0.0.1:8000
[web-build-gate] OK: BUILD_ID InSs8pBEYhoXkWmagLNDF
[web-build-gate] PASS — build is safe to serve; restart authorised.
EXIT=0
```

**FAIL-BEFORE — against the archived, genuinely poisoned 08:25 `.next`:**
```
[web-build-gate] FAIL: 2 /api/* rewrite(s) do not target http://127.0.0.1:8000:
  routes-manifest.json $.rewrites[0]
    source      = /api/:path*
    destination = http://127.0.0.1:8090/:path*
  required-server-files.json $.config._originalRewrites.afterFiles[0]
    source      = /api/:path*
    destination = http://127.0.0.1:8090/:path*
...
DO NOT restart aether-web.service.
EXIT=1
```

This is a real fail-before against the actual historical artefact, not a synthetic fixture.

Other guards, all exercised: `AETHER_API_PROXY=...:8090` in the shell → EXIT=1;
`AETHER_API_PROXY=...:8000` (correct) → EXIT=0; no build present → EXIT=1.

### Where it is wired

`docs/delivery/DEPLOYMENT-RUNBOOK.md`:

- **New §0.4 addendum** — full incident writeup: the mechanism, why it stayed invisible, the
  two corollaries (env fix is insufficient; the e2e harness is the vector), and the binding
  rule: *no `aether-web.service` restart without `scripts/verify-web-build.sh` exiting 0.*
- **New §5 Phase 3b** — blocking gate between the build (Phase 3) and the restart (Phase 4).
- **Complete Deploy Recipe** — renumbered `[1/6]`→`[1/7]`; the build step now runs as
  `env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm build`, and a new `[5/7]` step runs
  the gate with `|| exit 1` before any restart.
- **§5 Phase 5 step 3b** — a post-restart curl of `http://127.0.0.1:3000/api/health` that goes
  through next-server's own rewrite table rather than nginx.
- **Deployment Timeline table** — gate row added, build duration corrected for a cold `.next`.

---

## 7. Verification after the rebuild

| Suite | Command | Result |
|---|---|---|
| Typecheck | `npx tsc --noEmit` | **exit 0, no output — clean** [VERIFIED 13:02:13Z → 13:02:25Z] |
| Frontend unit | `pnpm test` (vitest run) | **649 passed / 1 failed**, 95 of 96 files pass, 412.73s [VERIFIED 13:02:11Z → 13:09Z] |

```
 Test Files  1 failed | 95 passed (96)
      Tests  1 failed | 649 passed (650)
   Duration  412.73s
=== VITEST EXIT: 1 ===
```

The **single** failure is:

```
FAIL src/app/dashboard/jobs/__tests__/tailor-score-refresh.test.tsx
  > W-J item 6 — displayed match score after a tailor run (§12.3)
  > updates the displayed score to the fresh tailoredATSScore once tailoring
    completes, without a manual reload
```

This is the **KNOWN-RED file-ownership fence** flagged in the task brief. It is the only
failure, it is the expected one, and it is **not** a regression from the rebuild —
**no new failures were introduced.** The rebuild changes build output only; it touches no
source file. The suite's non-zero exit code is attributable entirely to this known-red test.

---

## 8. THE MOMENT OF TRUTH — what to check immediately after the first restart

**The running `next-server` (PID 234331) still holds the old in-memory `:8000` rewrite table.
It has never read the corrected artefact. The FIRST restart after this fix — the W-L deploy's
Phase 4, or any incidental restart — is the first time the on-disk manifest actually takes
effect.** Until then, the fix is unproven *in production* no matter how green the offline
proofs are.

Immediately after that restart, in this order:

1. **Gate first, restart second.** `scripts/verify-web-build.sh` must exit 0 *before* the
   restart command is issued. If it fails, do not restart.
2. **The `/api` proxy through next-server itself (the decisive check):**
   ```bash
   curl -s --max-time 10 http://127.0.0.1:3000/api/health
   # Expect: {"status":"ok","version":"0.2.0"}
   ```
   A hang, empty body, or 500 means the rewrite upstream is wrong → roll back per §6
   immediately. This bypasses nginx deliberately: nginx has its own correct `/api → :8000`
   rule, so a public-URL curl can look healthy while next-server's table is broken.
3. **Confirm the manifest the new process actually loaded:**
   ```bash
   grep -o '"destination":"http://127.0.0.1:[0-9]*/:path\*"' apps/web/.next/routes-manifest.json
   # Expect: "destination":"http://127.0.0.1:8000/:path*"
   ```
4. **A real authenticated API call through the browser path**, not just `/health` — e.g. log in
   on `https://5cb5f0620.abacusai.cloud/login` and confirm `/dashboard` populates. `/health` is
   unauthenticated and would still pass if only authenticated routes were broken.
5. **§0.3 asset check** (mandatory after any build+restart): for each of `/login`,
   `/dashboard`, `/dashboard/jobs`, assert HTTP 200, zero occurrences of
   `Application error`/`client-side exception`, **and** that every `_next/static/*` URL
   referenced in the returned HTML independently resolves 200.
6. `tail -20 /var/log/aether/web.log` for a clean Next.js ready line and no proxy errors.

---

## 9. Files changed

| File | Change |
|---|---|
| `scripts/verify-web-build.sh` | **NEW** — the blocking pre-flight gate |
| `docs/delivery/DEPLOYMENT-RUNBOOK.md` | §0.4 addendum, §5 Phase 3b, Phase 5 step 3b, deploy recipe renumber + gate wiring, timeline table |
| `apps/web/.next/**` | rebuilt (untracked build output, not committed) |

`apps/web/next.config.mjs` was **not** changed. The `?? "http://127.0.0.1:8000"` default is
already correct; the defect was environmental, and the correct control is a gate on the
artefact, not a change to the config's semantics.

## 10. Follow-up filed for the orchestrator (NOT actioned — out of scope)

`apps/web/playwright.config.ts` `webServer.command` builds into the live serving tree and
`reuseExistingServer` points e2e at the running production server. That is the recurrence
vector for both this finding and runbook §0.3. Fixing it (isolated `distDir`/worktree for e2e,
or a dedicated port) is a separate change requiring an orchestrator ruling — the new gate
contains the *consequence*, but does not remove the *cause*.
