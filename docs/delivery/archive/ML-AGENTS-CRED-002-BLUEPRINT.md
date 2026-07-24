# ML-agents-cred-002 — ARCHITECTURE BLUEPRINT: "Connect with Anthropic (subscription)" OAuth

**Status:** DRAFT — requires explicit fable-5 (orchestrator) approval before ANY implementation. No production fix code is written by this blueprint.
**Author:** arch sub-agent (MODELS-LIVE). **Repo HEAD:** `efa4047`. **Date:** 2026-07-22.
**Governing decision:** ADR-ML-1 (binding operator mandate) — the Anthropic configure-credentials window MUST open Anthropic's own auth web page for subscription users (in-app-initiated OAuth), with manual paste retained as an honest fallback.
**Live mechanics of record:** `uat/reports/evidence/models-live/catalog/ML-agents-cred-002-live-mechanics.md` (all constants below are the LIVE-VERIFIED values, not the stale historical ones).

Epistemic tags on every load-bearing claim: `[VERIFIED-WITH-SOURCE]`, `[INFERRED]`, `[ASSUMED-PENDING-PROBE]`.

---

## 0. Executive summary + the ONE binding decision

The flow is a **manual authorization-code paste** built on the **public Claude Code OAuth client** (`9d1c250a-…`), on Anthropic's OWN pages (`platform.claude.com`). We CANNOT use a full redirect-callback into our domain because the public client only allows Anthropic-hosted / loopback redirect URIs `[VERIFIED-WITH-SOURCE §7]`. The UX therefore is: **click "Connect with Anthropic" → new tab opens Anthropic's authorize page → operator logs in with Pro/Max + consents → Anthropic shows a code → operator pastes the code back into the modal → server exchanges it (PKCE) for an access+refresh token → stored encrypted, auto-refreshed before expiry.**

Almost all substrate already exists (tables, vault, transport headers, `.env` sync, resolver, quota handling) — see live-mechanics §8. The net-new surface is small: 3 backend endpoints, 1 refresh helper + its resolver hook, 1 FE affordance + paste step, and status plumbing.

**DECISION-1 (needs fable-5 ruling) — token store + resolver wiring.** Two viable shapes; blueprint RECOMMENDS Option A:
- **Option A (RECOMMENDED): authoritative `AnthropicOAuthToken` + one small resolver branch.** Store access+refresh+expiry+scopes in the purpose-built `AnthropicOAuthToken` row (keyed by the operator's `userId`) — **zero new DDL** (it already has `refreshCipher`, `expiresAt`, `scopes`, `mark_needs_reauth`). Add ONE anthropic-only source, checked FIRST, to `resolve_user_credential`: refresh-if-needed then return that token as an `oauth_token` resolution; else fall through UNCHANGED to the existing ProviderCredential/env logic (manual paste = honest fallback). Single source of truth; `resolve_provider` (billing routing) is genuinely untouched.
- **Option B (alternative): mirror into `ProviderCredential`.** Store access token in the deployment-wide `ProviderCredential` (authMode `oauth_token`, exactly like manual paste → resolver 100% untouched) and keep refresh+expiry in `AnthropicOAuthToken`; refresh re-writes both. Zero resolver change, but the access secret lives in two rows (split-brain risk on refresh).

The rest of this blueprint is written to Option A, calling out the Option-B deltas where they differ.

---

## A. UX — ProviderConfigModal "Connect with Anthropic (subscription)"

**File:** `apps/web/src/components/agents/ProviderConfigModal.tsx` (edited) + `apps/web/src/components/agents/api.ts` (edited). `[VERIFIED-WITH-SOURCE — current modal read in full]`

Today the Anthropic card shows two radio auth modes: `api_key` and `oauth_token` (paste from `claude setup-token`), both writing `PUT /agents/providers/anthropic/credential`. The billing copy is already honest. We ADD a third, primary affordance ABOVE the manual field — it does not remove the manual paths (honest fallback preserved).

### A.1 Affordance
- A prominent **"Connect with Anthropic (subscription)"** button in the Anthropic card only (`view.id === "anthropic"`). Subtitle: "Sign in on Anthropic's site with your Claude Pro/Max plan — no token to copy from a terminal."
- Below it, an unobtrusive "or paste a token manually" disclosure that reveals the EXISTING radio group (`api_key` / `oauth_token`) + secret field unchanged.

### A.2 Connect click → open Anthropic's page (manual-code-paste flow) `[VERIFIED-WITH-SOURCE §3,§7]`
1. FE calls `POST /agents/providers/anthropic/oauth/start` → `{ authorizeUrl, state }`.
2. FE `window.open(authorizeUrl, "_blank", "noopener")` (new tab/popup). If the popup is blocked, render the URL as a clickable "Open Anthropic sign-in" link (no silent failure).
3. The modal transitions to a **"Paste the code from Anthropic"** step: a single text input ("After you approve, Anthropic shows a code — paste it here"), a "Finish connecting" button, and a "Cancel / back" affordance. The input accepts either the bare code or the whole `code#state` / full redirect URL string (server normalizes). `[INFERRED — accepts full-URL paste, mirroring Claude Code's own "paste the full URL from the address bar" fallback]`
4. On "Finish connecting" the FE calls `POST /agents/providers/anthropic/oauth/exchange { code }` (the pasted string). The `state` is NOT trusted from the client for authorization — the server re-derives/validates it (see B.2).

### A.3 States (honest; no fabricated success)
- **loading**: "Waiting for you to approve in the Anthropic tab…" while the paste step is shown; the exchange call shows "Connecting…".
- **success**: only after a real token round-trip verify returns 2xx — badge flips to `saved` / connected, shows `Ends …<last4>` from `secretHint`, and (new) an expiry line "Subscription session active — auto-renews".
- **error**: the server's honest message verbatim (e.g. "state mismatch", "Invalid authorization code", "Anthropic subscription quota reached", "Encryption unavailable (503)"). Never a green badge on failure.
- **needs_reauth** (surfaced from status): "Anthropic subscription session expired — click Connect to sign in again." (Set when auto-refresh has failed; see C.3.)

### A.4 Preserved fallback
The manual `oauth_token` (paste `claude setup-token`) and `api_key` (Console key) paths remain fully functional and visible. If Anthropic rejects the web-mediated code (see G risks), the operator still has the manual path. `[VERIFIED-WITH-SOURCE — existing paths retained]`

---

## B. Backend endpoints

**File:** `apps/api/app/routers/agents.py` (edited) + NEW `apps/api/app/services/anthropic_oauth.py` (service module holding constants + PKCE + HTTP; keeps the router thin and unit-testable). Paths are NEW and clearly namespaced (deliberately NOT the historical deleted `/agents/auth/anthropic/*` paths, per the compliance-sensitivity note). `[VERIFIED-WITH-SOURCE — router structure + deleted-path history read]`

Constants live in the new service module (NOT hardcoded secrets — the client_id is a PUBLIC distributed constant `[VERIFIED-WITH-SOURCE §1]`; overridable by env `AETHER_ANTHROPIC_OAUTH_CLIENT_ID` for staging, defaulting to the public one):

```
AUTHORIZE_URL   = "https://platform.claude.com/oauth/authorize"
TOKEN_URL       = "https://platform.claude.com/v1/oauth/token"
REDIRECT_URI    = "https://platform.claude.com/oauth/code/callback"   # Anthropic-hosted; NOT ours
CLIENT_ID       = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"              # public Claude Code client
SCOPE           = "org:create_api_key user:profile user:inference"
BETA_HEADER     = "oauth-2025-04-20"
STATE_TTL       = 10 min   (AnthropicOAuthState.expiresAt already defaults to now()+10min)
REFRESH_SKEW    = 5 min
```

### B.1 `POST /agents/providers/anthropic/oauth/start` (auth required) `[VERIFIED-WITH-SOURCE — reuses AnthropicOAuthStateRepository.create]`
1. Generate PKCE: `verifier = token_urlsafe(64)`, `challenge = b64url(sha256(verifier)).rstrip('=')` (S256).
2. Generate opaque `state = token_urlsafe(24)`.
3. `AnthropicOAuthStateRepository().create(state, current_user["id"], verifier)` — persists `{state → verifier, userId}` with a 10-min TTL, server-side. The verifier NEVER leaves the server.
4. Build the authorize URL (params per §A.2 / live-mechanics §3, incl. `code=true`).
5. Return `{ "authorizeUrl": <url>, "state": <state> }`. (The state is returned only so the FE can display/telemetry it; it is NOT the trust anchor.)

### B.2 `POST /agents/providers/anthropic/oauth/exchange` (auth required) `[VERIFIED-WITH-SOURCE — AnthropicOAuthState.consume is atomic single-use; token transport confirmed]`
Body: `{ "code": <string> }` — the pasted value (bare code, or `code#state`, or full success URL).
1. **Normalize**: strip whitespace; if it contains `#`, split into `(code, returned_state)`; if it looks like a URL, parse `code` and `state` from the query/fragment. `[INFERRED — delimiter/format; see live-mechanics §7]`
2. **CSRF / state validation**: `row = AnthropicOAuthStateRepository().consume(returned_state)` — atomic fetch-and-delete of a NON-expired row (single use, replay-proof). If `None` → `HTTP 400 "state mismatch or expired — restart the connection"`. Require `row.userId == current_user["id"]` (bind to the initiating operator) → else `403`. Use `row.codeVerifier` for the exchange. If the pasted value had no `#state`, fall back to the single most-recent live state row for THIS user (still consumed atomically) — this tolerates a bare-code paste while keeping CSRF binding to the user. `[INFERRED — bare-code tolerance]`
3. **Exchange** at `TOKEN_URL` (`grant_type=authorization_code, code, redirect_uri=REDIRECT_URI, client_id=CLIENT_ID, code_verifier=row.codeVerifier`). Parse the Anthropic error envelope on non-2xx (both `{"error":{type,message}}` and `{"type":"error","error":{...}}`) and surface `type`/`message` honestly. `[VERIFIED-WITH-SOURCE §5,§6]`
4. **Validate response**: require `token_type == "Bearer"` and a non-empty `access_token`; compute `expires_at = now + expires_in`. `[VERIFIED-WITH-SOURCE §6]`
5. **Store** (Option A): `AnthropicOAuthTokenRepository().upsert(userId, access_ciphertext=vault.encrypt(access_token), refresh_ciphertext=vault.encrypt(refresh_token), secret_hint=vault.secret_hint(access_token), expires_at=expires_at, scopes=granted_scope)`. Then `env_file_writer.sync_oauth_token_env(access_token)` (best-effort; worker/restart survival; token never logged). Vault-missing → honest `503` BEFORE any store (no plaintext, no fake success). `[VERIFIED-WITH-SOURCE — vault + repo + env_file_writer contracts]`
6. **Verify + return**: run a real 1-token Messages round-trip via the existing `verify_user_credential("anthropic", userId)` so the badge is truthful; return the masked status object (never the token). A failed verify records `failed` and returns honestly (no green badge).

### B.3 `POST /agents/providers/anthropic/oauth/refresh` (auth required; also invoked internally) `[VERIFIED-WITH-SOURCE §6]`
- Reads `AnthropicOAuthTokenRepository().get(userId)`; if no refresh token → `409 needs_reauth`.
- POST `TOKEN_URL` (`grant_type=refresh_token, refresh_token, client_id`). On 2xx: re-`upsert` new access + rotated refresh + new expiry; re-`sync_oauth_token_env`. On failure: `mark_needs_reauth(userId)` and return an honest error. NEVER returns a stale/expired token; NEVER rotates to another provider.
- This endpoint mainly exists for tests + a manual "renew now" button; production refresh is automatic via the resolver hook (C.3).

### B.4 Status
Extend the Anthropic provider status object (`_provider_status_object` / user-credential masked row) with `oauthConnected: bool`, `oauthExpiresAt`, `oauthNeedsReauth: bool`, derived from `AnthropicOAuthToken` for the current user. `[VERIFIED-WITH-SOURCE — status object shape read]` No secret is ever included.

---

## C. Storage, vault, transport, auto-refresh

### C.1 Vault + at-rest `[VERIFIED-WITH-SOURCE — credential_vault read]`
Access and refresh tokens are stored ONLY as Fernet ciphertext (`AETHER_CREDENTIAL_KEY`) plus a `…last4` hint. Missing key → honest `503`, never a plaintext/fake row. `AnthropicOAuthToken` masked reads never include `ciphertext`/`refreshCipher`.

### C.2 Transport UNCHANGED `[VERIFIED-WITH-SOURCE §8 / llm_client:793-820]`
The resolved `oauth_token` access token flows through the existing `anthropic_auth_headers('oauth_token', secret)` → `Authorization: Bearer <token>` + `anthropic-beta: oauth-2025-04-20` + `anthropic-version`. No transport change.

### C.3 Auto-refresh hook — the hard requirement `[VERIFIED-WITH-SOURCE — resolver structure; operator's on-disk token already expired 2026-07-21]`
NEW helper `anthropic_oauth.refresh_if_needed(user_id) -> access_token | None` (in the new service module), invoked at the TOP of the anthropic branch of `resolve_user_credential` (Option A) BEFORE returning a resolution:
1. Load `AnthropicOAuthToken.get(user_id)`. If absent → return `None` (fall through to manual paste / env — same-provider only).
2. If `scopes == 'needs_reauth'` → return `None` (treated as absent; modal shows needs_reauth). No silent use of a broken session.
3. If `expiresAt - now > REFRESH_SKEW` → return the decrypted access token (still valid).
4. Else refresh (B.3 logic). On success → return the FRESH access token. On failure → `mark_needs_reauth` and **raise an honest, anthropic-scoped error** (surfaced as a 429/401-style honest failure to the run) — do NOT return the expired token, do NOT fall through to a DIFFERENT provider. `[VERIFIED-WITH-SOURCE — no-cross-provider invariant]`

**No silent fallthrough guarantee:** a refresh failure never (a) reuses an expired token, (b) reroutes to OpenRouter, or (c) fabricates success. It marks needs_reauth and fails loudly, exactly like Claude Code's own "expired with no refresh" hard error. `[VERIFIED-WITH-SOURCE §6]`

**DECISION-1b (fable-5 to confirm):** on refresh failure, may the resolver silently fall through to a manually-pasted Anthropic `api_key`/`oauth_token` in `ProviderCredential` (same provider, explicitly configured), or must it fail loudly and force reconnect? Blueprint recommends: **fail loudly + surface needs_reauth** (honest), and let the operator explicitly choose the manual credential — do not silently mask a broken subscription session.

### C.4 Concurrency
Refresh should be single-flight per user to avoid two concurrent runs both refreshing (double rotation could invalidate one). Use a short Postgres advisory lock (`pg_advisory_xact_lock` on a hash of `('anthropic_oauth_refresh', user_id)`) around the read-refresh-write, mirroring the existing DDL-lock pattern. `[INFERRED — standard refresh single-flight; advisory-lock pattern already used in repo]`

---

## D. resolve_provider / billing — UNCHANGED, no regression `[VERIFIED-WITH-SOURCE — resolve_provider read at llm_client:437-459]`
- `resolve_provider(model)` is a pure function: bare `claude-*`/`anthropic*` → `anthropic`; any `vendor/model` (slash) → `openrouter`. This work does NOT touch it. Slash ids still bill OpenRouter; bare `claude-*` still bills direct Anthropic (now via this subscription token). `[VERIFIED-WITH-SOURCE]`
- Only `resolve_user_credential`'s anthropic credential-SOURCE ordering gains one prepended source (the OAuth token). All existing branches, the `subscription_oauth` block, the no-cross-provider guard, and the `CLAUDE_CODE_OAUTH_TOKEN`-is-not-a-source rule are preserved verbatim. `[VERIFIED-WITH-SOURCE]`
- Regression guard: the existing `test_provider_config::TestNoCrossProviderFallback` + `test_gap_p5_auth_compliance` + `test_gap_p7_def_a_dual_mode` MUST stay green unchanged (see F).

---

## E. Compliance note (supersedes Phase-6 ToS caution, per ADR-ML-1) `[VERIFIED-WITH-SOURCE §1,§4 + ADR-ML-1]`
This flow uses the operator's OWN Anthropic subscription, authenticated on Anthropic's OWN pages (`platform.claude.com`), using the SAME public OAuth client (`9d1c250a-…`) and the SAME `org:create_api_key user:profile user:inference` scopes that Anthropic's own `claude setup-token` uses. The operator personally logs in and consents; our server only exchanges the code the operator pastes and stores the operator's own tokens encrypted. This is functionally identical to `claude setup-token` (where the human also copies a code from the same Anthropic page) — the only difference is the paste target (our modal vs a terminal). This is why ADR-ML-1 supersedes the Phase-6 prohibition (which was about our app acting as its OWN unregistered OAuth client with our OWN redirect_uri — a design we explicitly do NOT use). **Honest fallback:** if Anthropic's authorization server rejects a web-mediated paste, the manual `claude setup-token` paste + Console `api_key` paths remain, unchanged. `[ASSUMED-PENDING-PROBE — end-to-end acceptance confirmed only by the operator's real consent click]`

---

## F. Test plan (for test-author)

### F.1 Unit (pytest, no network)
- `anthropic_oauth`: PKCE S256 challenge = b64url(sha256(verifier)) no padding; authorize URL contains client_id, `response_type=code`, redirect_uri, S256 challenge, scope, state, `code=true`. `[machine-verifiable]`
- Exchange body assembly (grant_type/code/redirect_uri/client_id/code_verifier); refresh body assembly (grant_type/refresh_token/client_id). Error-envelope parser handles BOTH Anthropic error shapes.
- `refresh_if_needed`: valid→returns token no HTTP; within-skew→refresh path; refresh-failure→`mark_needs_reauth` + honest raise + NO cross-provider; `needs_reauth`→treated absent.
- Vault round-trip: encrypt→decrypt access+refresh; `key_present()` false → 503 path; masked reads exclude ciphertext/refreshCipher.
- `resolve_provider` unchanged (bare `claude-*`→anthropic, slash→openrouter) — assert byte-for-byte behavior.

### F.2 Integration (FastAPI TestClient, token endpoint MOCKED)
- `start` → persists AnthropicOAuthState (verifier not returned), returns authorizeUrl+state.
- `exchange` happy path (mock token 200) → stores encrypted AnthropicOAuthToken, syncs `.env` (temp dir via `AETHER_ENV_FILE_PATH`), returns masked status, verify mocked ok.
- `exchange` CSRF: unknown/expired/replayed state → 400; state.userId != caller → 403; state consumed exactly once (second use → 400).
- `exchange` token-endpoint 400 `invalid_grant` → honest 400, NO row stored, NO `.env` write.
- `exchange` vault missing → 503 before any store.
- `refresh` success rotates + re-syncs; refresh failure → needs_reauth, honest error, resolver then yields no anthropic OAuth resolution and does NOT route to openrouter.
- Resolver: with a live AnthropicOAuthToken, a bare `claude-*` run resolves the OAuth token with Bearer+beta headers; with only a slash id it still routes OpenRouter (billing unchanged).
- Quota: a mocked Anthropic 429 subscription-quota during a run records a block + raises QuotaExhaustedError (no fallthrough) — existing behavior preserved.

### F.3 Playwright (FE; backend `start`/`exchange` stubbed)
- Anthropic modal shows "Connect with Anthropic (subscription)"; click calls `start`, opens a new tab to an URL whose params include the real client_id + S256 `code_challenge` + `state` (assert on the captured `window.open` arg). `[machine-verifiable — no consent]`
- Paste step accepts a code; "Finish connecting" calls `exchange`; success flips badge to connected + shows `Ends …<last4>` + "auto-renews"; error shows the server message verbatim; needs_reauth state renders the reconnect CTA.
- Manual paste fallback (radio `oauth_token`/`api_key`) still present and functional.

### F.4 HUMAN-GATED (cannot be machine-verified)
- The operator's real login + Pro/Max consent on `platform.claude.com` and the real code paste (consumes real consent). `[ASSUMED-PENDING-PROBE]`
- A real 200 token-exchange body + the literal success-page `code` format + a real end-to-end agent run billed to the subscription. `[ASSUMED-PENDING-PROBE]`
- These are recorded as HUMAN-GATED in the gap ledger; the machine tests above mock the token endpoint so CI is fully green without them.

---

## G. Risk / rollback + minimal-diff plan

### G.1 Files
**New (2):**
- `apps/api/app/services/anthropic_oauth.py` — constants, PKCE, authorize-URL builder, exchange/refresh HTTP, `refresh_if_needed`. (Re-creates a compliant subset of the deleted module; deliberately NOT restoring the deleted router paths.)
- `apps/api/tests/test_ml_cred_002_anthropic_oauth.py` — F.1/F.2 suites.

**Edited (4):**
- `apps/api/app/routers/agents.py` — 3 endpoints (start/exchange/refresh) + status fields.
- `apps/api/app/services/llm_client.py` — prepend the OAuth source in `resolve_user_credential`'s anthropic branch + call `refresh_if_needed` (Option A). ~15 lines, additive; existing branches untouched.
- `apps/web/src/components/agents/ProviderConfigModal.tsx` — Connect button + paste step + states.
- `apps/web/src/components/agents/api.ts` — `startAnthropicOAuth` / `exchangeAnthropicOAuth` clients + status field types.
- (+ a Playwright spec under `apps/web` e2e for F.3.)

**DDL:** NONE (Option A). `AnthropicOAuthState` + `AnthropicOAuthToken` already have every needed column `[VERIFIED-WITH-SOURCE §8]`. Option B would add `ALTER TABLE "ProviderCredential" ADD COLUMN IF NOT EXISTS "expiresAt"/"refreshCipher"/"oauthScopes"` (additive-only) — avoided by choosing A.

### G.2 Risks
1. **Anthropic rejects a web-mediated code** (client expects terminal/loopback). Mitigation: manual `setup-token` paste + Console key remain; feature is additive. Likelihood LOW (same page, same client, human copies the code either way). `[ASSUMED-PENDING-PROBE]`
2. **Refresh-token rotation race** → single-flight advisory lock (C.4).
3. **Success-page code format drift** (`code#state` vs full-URL). Mitigation: exchange normalizer accepts bare code, `code#state`, and full URL; unit-tested. `[INFERRED]`
4. **client_id / endpoint drift** if Anthropic changes the public client. Mitigation: constants centralized + env-overridable; a failing verify surfaces honestly. `[VERIFIED-WITH-SOURCE — env override pattern]`
5. **Secret leakage** — enforced: tokens only vault-encrypted; `.env` write atomic 0600 + never logged; masked reads exclude ciphertext; no token in error messages. `[VERIFIED-WITH-SOURCE — existing contracts reused]`

### G.3 Rollback
Fully additive + feature-flaggable. Rollback = hide the Connect button (FE) and/or remove the 3 endpoints; the manual paste + Console key paths (and all existing resolution) are unchanged, so removal restores exact prior behavior. No data migration to reverse (tables were already present and empty). `[VERIFIED-WITH-SOURCE]`

### G.4 Prohibited-actions self-check
No production fix code written here. No self-approval. No destructive DDL (zero DDL in Option A). No secrets in source (client_id is public + env-overridable; tokens vault-only). No silent credential-type fallthrough (C.3). No fixture content in any production path. Awaiting fable-5 approval.

---

## Appendix — open questions for fable-5
1. DECISION-1: Option A (authoritative AnthropicOAuthToken + 1 resolver source) vs Option B (mirror into ProviderCredential, zero resolver change). Blueprint recommends A.
2. DECISION-1b (C.3): on refresh failure, fail loudly + force reconnect (recommended) vs silently fall through to a manual same-provider Anthropic credential.
3. Scope of the OAuth token: per-user (operator's `userId`, matches AnthropicOAuthToken PK + agent-run user context) — confirm this is the intended scope for the single-operator product (vs deployment-wide). Blueprint assumes per-user (operator).
4. Whether to also expose a manual "Renew now" button (B.3) in the modal, or keep refresh fully automatic.
