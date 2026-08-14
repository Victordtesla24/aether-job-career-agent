# ADR-SEC-TOKEN-STORE — migrate the session JWT out of localStorage

- **Status:** Proposed — execution deferred post-launch, per orchestrator prompt Wave D
  (`docs/delivery/ORCH-DELTA-2026-08-14.md:41`, row "D localStorage tokens | Plan migration |
  Confirmed `aether_token` in localStorage; no migration plan exists | PARTIAL | Author migration
  ADR (execute post-launch)"). This document satisfies that "author migration ADR" step. It does
  not itself change any code.
- **Date:** 2026-08-14
- **Scope:** `apps/web` session-token storage and every FE read-site; the FastAPI auth dependency
  that must accept the new credential during migration.

---

## 1. Current state (verified against the repo, not assumed)

### 1.1 The token and its central helper

`apps/web/src/lib/api/client.ts:14` — `const TOKEN_STORAGE_KEY = "aether_token";`

Same file:
- `getToken()` (~line 249-267) reads `window.localStorage.getItem(TOKEN_STORAGE_KEY)`; a cache-miss
  redirects to `/login` via `window.location.replace` rather than silently failing.
- `clearToken()` (~line 269-274) calls `window.localStorage.removeItem(TOKEN_STORAGE_KEY)`.
- `apiRequest<T>()` (~line 294-334) sets `Authorization: Bearer ${token}` on every outgoing `fetch`
  call (line ~308) and, on a 401, clears the token and retries once with a freshly-read token.
- `apiBaseUrl()` (line 16-24): browser calls resolve to same-origin `/api`; only SSR/dev falls back
  to `http://127.0.0.1:8000`. **This confirms the FastAPI backend is same-origin via the `/api/`
  path in production** — `deploy/5cb5f0620.conf`'s `location /api/` block rewrites `/api/(.*)` →
  `/$1` and proxies to `127.0.0.1:8000` on the same host/port as the Next.js app. A `SameSite=Lax`
  (or even `Strict`) cookie set by FastAPI would ride along on every same-origin fetch without any
  cross-site cookie complication.

There is no shared import of `TOKEN_STORAGE_KEY` — every consumer below independently re-declares
the literal `"aether_token"` string or the constant.

### 1.2 Exhaustive list of FE read/write sites (grep-verified across `apps/web/src`)

| File | What it does with the token |
|---|---|
| `apps/web/src/lib/api/client.ts` | canonical `getToken`/`clearToken` (§1.1) |
| `apps/web/src/app/login/page.tsx` (line ~69) | `localStorage.setItem(TOKEN_STORAGE_KEY, session.accessToken)` after a successful login; also reads it (~line 53) to redirect an already-logged-in visitor away from `/login` |
| `apps/web/src/app/signup/page.tsx` (line ~65) | writes the token after registration; reads it (~line 30) for the same already-logged-in guard |
| `apps/web/src/app/admin-login/page.tsx` (line ~63) | writes the token after admin login |
| `apps/web/src/app/page.tsx` (marketing root, line ~25) | reads it only to decide whether to show an authed CTA (`Boolean(getItem(...))`) |
| `apps/web/src/app/pricing/page.tsx` (line ~58, ~116) | same presence-check pattern, twice |
| `apps/web/src/components/auth-guard.tsx` (line ~14, ~21) | reads it to decide whether to redirect to `/login` |
| `apps/web/src/components/admin/admin-guard.tsx` (line ~18, ~28) | reads it for the same purpose on admin routes (comment at ~line 36 notes the backend remains the real authority) |
| `apps/web/src/lib/auth/logout.ts` (line ~9) | imports `clearToken`; **also already defensively clears an `aether_token` cookie** — `document.cookie = "aether_token=; Max-Age=0; path=/; SameSite=Lax"` — even though nothing sets that cookie today |
| `apps/web/src/components/user-menu.tsx` (line ~13, ~52) | calls the logout helper; no direct localStorage access |

**Nine production files** touch the token directly or via the two helpers above; all nine, plus
their test suites (`apps/web/src/app/login/__tests__/page.test.tsx`,
`apps/web/src/app/signup/__tests__/page.test.tsx`, `apps/web/src/app/pricing/__tests__/page.test.tsx`,
`apps/web/src/components/__tests__/auth-guard.test.tsx`,
`apps/web/src/components/__tests__/user-menu.test.tsx`,
`apps/web/src/lib/auth/__tests__/logout.test.ts`, and two dashboard-settings tests that mock the
token), must change together if `localStorage` access is removed. This is the exhaustive list a
migration PR must cover — a partial migration that leaves even one read-site on the old key would
silently reintroduce the localStorage token as a live attack surface for that one screen.

### 1.3 Login flow

Backend: `apps/api/app/routers/auth.py:119`, `def login(request, body: LoginRequest) ->
TokenResponse`, verifies credentials and at line 179 calls `create_access_token(user["id"],
user["email"])` (`apps/api/app/security.py:74`), returning the token in the JSON body. The signing
secret is read by `apps/api/app/security.py:29-32`: env var **`JWT_SECRET`**, falling back to
**`NEXTAUTH_SECRET`** if unset (`os.environ.get("JWT_SECRET") or os.environ.get("NEXTAUTH_SECRET")`).

Frontend: `apps/web/src/lib/api/auth.ts` posts to this endpoint and returns `{accessToken, userId,
email}`; `login/page.tsx`, `signup/page.tsx`, and `admin-login/page.tsx` each take that
`accessToken` and write it to `localStorage` directly (§1.2) — the token never lives anywhere else
in the browser today.

### 1.4 Backend auth dependency

`apps/api/app/middleware/auth.py`:
- Line 13: `oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")` — **Bearer-header only,
  no cookie fallback exists anywhere in this file today.**
- Line 38: `get_current_user(token: Annotated[str, Depends(oauth2_scheme)])` decodes the JWT
  (`decode_access_token`, `security.py`), rejects suspended users, and enforces password-reset
  invalidation by comparing the token's `iat` against `passwordChangedAt` (lines ~68-80).
- A repo-wide grep for `set_cookie`/`Set-Cookie` across `apps/api` returns **zero hits** — the
  backend has never set a cookie of any kind. This ADR's recommendation (§3) is new backend surface,
  not a change to existing behavior.

### 1.5 CSRF — none exists today

`apps/web/src` grep for `csrf` (case-insensitive): zero hits. `apps/api` grep: two hits, both
unrelated to session auth — a comment in `apps/api/app/routers/agents.py` and the *OAuth `state`
parameter* CSRF protection inside `apps/api/app/services/anthropic_oauth.py:143` (for the
Anthropic-account-connect flow, a different feature entirely). **There is no CSRF protection for
the session credential today** — expected, since Bearer-header auth is inherently CSRF-immune (a
malicious page cannot read `localStorage` cross-origin, and cannot set a custom `Authorization`
header via a simple cross-site form/img/script). This immunity is exactly what moving to a cookie
gives up, and exactly why §3 makes CSRF protection a mandatory part of the same change, not a
follow-up.

### 1.6 HTTP client stack

`apps/web/package.json` has no axios/ky/swr/react-query — confirmed by grep, zero hits. All
requests go through native `fetch()` in `client.ts`. Any CSRF token attachment must be hand-added to
`apiRequest<T>()`'s existing header-setting code; there is no interceptor layer to hook into.

### 1.7 Prior art already in the repo (currently disconnected, not a migration target as-is)

`apps/web/src/lib/auth/{jwt.ts, session.ts, credentials.ts, options.ts, require-auth.ts}` is an
inert NextAuth.js scaffold (docstrings self-label it "P1-S03"/"P1-S06 TODO" from an earlier phase).
`next-auth` is a listed dependency (`apps/web/package.json`, `"next-auth": "^4.24.14"`), but a
repo-wide grep for `next-auth` imports or `NextAuth(` calls outside this directory returns zero
hits — **nothing in the live app wires it up**, and there is no `app/api/auth/[...nextauth]` route.
(`docs/delivery/INCOMPLETE-FEATURE-INVENTORY-FRONTEND.md:196,215-222` claims this scaffold is
"live-mounted" — that claim could not be verified against the current tree and should be treated as
stale.) Notably, `session.ts` already defines `SESSION_COOKIE_NAME = "aether.session-token"` and
`require-auth.ts` already supports a Bearer-then-cookie fallback pattern — architecturally close to
what §3 proposes, but entirely disconnected from `apps/api` today (no FastAPI route issues or reads
that cookie). Worth reusing as a starting point if it fits; not assumed to be reusable as-is without
review.

`docs/delivery/DECISIONS.md:313-320` (decision D-0006) records that a cookie-based session via
NextAuth was **considered and explicitly deferred** early in the project ("real login UX is a later
slice; the client seam already accepts an injected token") — this ADR is that deferred work,
now scoped concretely against the shipped Bearer-token implementation rather than a hypothetical
one.

---

## 2. Why localStorage is the wrong long-term store

Any XSS on any page that can execute JS in the app's origin can read `localStorage.getItem
("aether_token")` and exfiltrate it — full account takeover, no server-side signal, valid until the
JWT's own expiry. The blast radius is every one of the nine read-sites in §1.2 today, and every
future one added without discipline (there is no lint rule or shared accessor enforcing use of
`getToken()`/`clearToken()` — three of the nine files write the token by literal string, not via the
helper).

An httpOnly cookie is not readable by JS at all, so the same XSS gets nothing from the storage layer
itself. It trades that for CSRF exposure (§1.5), which is why §3 pairs the migration with an
explicit CSRF strategy rather than treating the cookie alone as sufficient.

---

## 3. Decision

**Recommended target state:** FastAPI sets the session credential as an **httpOnly,
`SameSite=Lax`, `Secure` cookie** on login/signup/admin-login responses, in addition to (during
migration) or instead of (after migration) the JSON `accessToken` field. `get_current_user` accepts
the cookie as well as the existing `Authorization: Bearer` header. A CSRF token — a random value the
backend also sets as a **non-httpOnly** cookie (so JS can read it) and the frontend echoes back as a
custom request header (`X-CSRF-Token`) on every state-changing request — protects the
state-changing routes, since `SameSite=Lax` alone still allows simple top-level GET navigations to
carry the cookie. This is the double-submit-cookie pattern; it requires no server-side session store
beyond what `"StripeEvent"`-style idempotency work already assumes about the DB layer, and needs no
new infrastructure.

Why `SameSite=Lax` rather than `Strict`: the app is same-origin end-to-end in production (§1.1), so
`Lax` already blocks the cross-site POST/PUT/DELETE cases that matter; `Strict` would additionally
break any legitimate top-level-navigation login link from outside the app (e.g. an email link into
`/login`) for no added protection here, since the CSRF token is the actual defense for
state-changing requests either way.

### 3.1 Phased, compatible migration (dual-accept window)

1. **Phase 1 — backend accepts both, changes nothing about issuance.** Add cookie-setting to
   `login`/`register`/admin-login responses (`Set-Cookie: aether_session=<jwt>; HttpOnly; Secure;
   SameSite=Lax; Path=/`) *alongside* the existing JSON `accessToken`. Extend
   `apps/api/app/middleware/auth.py`'s dependency to check the cookie if the `Authorization` header
   is absent, falling back to today's Bearer-only behavior otherwise. Add the CSRF-cookie +
   header-check pair, enforced only on the new cookie-authenticated path (Bearer-header requests
   stay CSRF-exempt exactly as today, since they're not attacker-triggerable). No FE change yet;
   old builds keep working unmodified because the JSON token is still present.
2. **Phase 2 — frontend stops reading/writing `localStorage`.** Update all nine files in §1.2:
   remove the `setItem`/`getItem`/`removeItem` calls, remove the `Authorization` header construction
   in `apiRequest<T>()` (the cookie now rides automatically with `fetch(..., {credentials:
   "same-origin"})` — note this must be added explicitly, since `fetch` does not send cookies by
   default even same-origin unless `credentials` is set), and add the CSRF header read/attach. Update
   all associated test suites (§1.2) to mock the cookie/CSRF flow instead of `localStorage`.
3. **Phase 3 — backend stops issuing the JSON `accessToken`** (or keeps it clearly marked
   deprecated for any non-browser API consumer that still needs a bearer token, e.g. scripts/CI —
   check `scripts/` and `ci/` for any direct API callers before removing it outright). Remove the
   Bearer-header fallback from `get_current_user` once nothing depends on it, or keep it
  permanently if a non-browser consumer is confirmed to need it.
4. Each phase ships and is verified independently; Phase 1 is safe to deploy without any FE change
   and has no user-visible effect until Phase 2 lands.

### 3.2 XSS blast-radius comparison

| | localStorage (today) | httpOnly cookie (proposed) |
|---|---|---|
| Token readable by injected JS | Yes — `localStorage.getItem` | No — `HttpOnly` blocks all JS access |
| Token exfiltratable to attacker origin | Yes, trivially | No |
| New attack surface introduced | None | CSRF on state-changing routes — mitigated by the double-submit token in §3 |
| Attacker with XSS can still act as the user *while the page is open* | Yes | Yes (cookie rides along automatically) — this is not eliminated by either design, only exfiltration-after-the-fact is |
| Blast radius if XSS exists on one low-trust page (e.g. a rendered résumé preview) | Full token theft, reusable anywhere, any time, until JWT expiry | No token theft; attacker is confined to actions performable from that page during that session |

The proposed design does not eliminate all XSS risk (an attacker with script execution can still
issue authenticated requests while the victim's tab is open) — its concrete win is closing the
**exfiltrate-and-reuse-later** class, which is the more damaging one, since it survives tab closure
and lets the attacker act outside any rate-limit/behavioral context the live page would have
provided.

---

## 4. Consequences

- **Deferred, not blocking:** per the orchestrator prompt's Wave D framing, this migration executes
  post-launch. This ADR is the plan; no code changes accompany it.
- Nine FE files + their tests change in Phase 2; two backend files (`middleware/auth.py`,
  `routers/auth.py`) change in Phase 1; `client.ts`'s `apiRequest<T>()` needs `credentials:
  "same-origin"` added when cookies become the transport (native `fetch` does not send cookies by
  default).
- The already-present `document.cookie` clear in `apps/web/src/lib/auth/logout.ts` needs no change
  in Phase 1 (it is a no-op today since nothing sets that cookie) but becomes load-bearing in
  Phase 2 — confirm its `path`/`SameSite` attributes exactly match what the backend actually sets,
  or logout will leave a stale cookie behind.
- The dead NextAuth scaffold (§1.7) is not required for this migration and should not be resurrected
  without a separate review — reusing its `SESSION_COOKIE_NAME` constant as documentation/naming
  inspiration is fine; wiring it in as the actual NextAuth runtime is out of scope here.

## 5. Not verified / open questions

- Whether any non-browser client (a script under `scripts/`, a CI job, an external integration)
  currently authenticates via the JSON `accessToken` field and would break if Phase 3 removed it —
  not audited as part of this ADR; check before executing Phase 3.
- The claim in `docs/delivery/INCOMPLETE-FEATURE-INVENTORY-FRONTEND.md` that a NextAuth route is
  "live-mounted" could not be reproduced against the current tree (§1.7) — flagged as stale, not
  corrected here (out of this ADR's scope to edit that document).
- Exact current values of `JWT_SECRET`/`NEXTAUTH_SECRET`/token TTL were not read (secrets); only
  their env var names and fallback order were confirmed from `apps/api/app/security.py:29-32`.
