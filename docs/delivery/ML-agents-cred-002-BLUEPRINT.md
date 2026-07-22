# BLUEPRINT — ML-agents-cred-002: In-app "Connect with Anthropic" OAuth

**Finding:** ML-agents-cred-002 (BLOCKER, operator-mandated, ADR-ML-1).
**Directive:** the Anthropic configure-credentials window must OPEN ANTHROPIC'S
AUTH WEB PAGE for subscription users, so they never hand-paste a long-lived token.
**Status:** PLAN ONLY — no production code written. This spec drives test-author
+ fixer. All external mechanics are [VERIFIED] from a fresh binary extraction of
the installed CLI (see `uat/reports/evidence/models-live/catalog/ML-agents-cred-002-cli-oauth-extract.md`);
token-endpoint *response* shapes are [INFERRED-FROM-BINARY] (flow never run).

---

## 1. Design decision (Design-Q1): REJECT app-hosted callback; ADOPT manual redirect + code paste-back + backend exchange

**Chosen: option (b).** Use Claude Code's own PUBLIC OAuth client
`9d1c250a-e61b-44d9-88ed-5944d1962f5e` with `redirect_uri =
https://platform.claude.com/oauth/code/callback` (Anthropic's own code-display
page). The operator authorizes on Anthropic's real page, Anthropic shows a
one-time `code#state`, the operator pastes it back into the modal, and the
**backend** exchanges it for tokens. This is byte-for-byte what `claude
setup-token` does — same client, same endpoints, same inference-only scope — with
the code paste-back moved from the terminal into the modal.

**Why (a) app-hosted callback is rejected (evidence):**
- The public client `9d1c250a` carries **no client_secret** (PKCE-only) and its
  redirect_uri is validated server-side by Anthropic against a fixed registered
  set: `platform.claude.com/oauth/code/callback` (manual) and
  `http://localhost:<port>/callback` (loopback) only. An arbitrary
  `https://5cb5f0620.abacusai.cloud/…/callback` is **not registerable** against
  this client. [VERIFIED — extract §1, §3, §8]
- (a) with a *separate* aether-registered client (the historical
  `AETHER_ANTHROPIC_OAUTH_CLIENT_ID`) is precisely the flow deleted as
  non-compliant in `94f3ab8`, and cannot be provisioned: no such client is
  registered, the env var is unset, and Anthropic offers no third-party OAuth
  client registration for consumer Pro/Max **subscription-billed inference**.
  [VERIFIED — mechanics doc §1/§8, RCA .env has only `CLAUDE_CODE_OAUTH_TOKEN`]
- The `http://localhost:<port>/callback` loopback variant is unusable here: the
  app is a REMOTE server; consent completes in the operator's browser; there is
  no aether listener on the operator's localhost. [INFERRED — deployment topology]

**Directive satisfaction:** the operator clicks "Connect with Anthropic", the app
opens Anthropic's genuine auth page, and the operator pastes back a **one-time
authorization code** — never the long-lived `sk-ant-oat01-` secret. The token is
minted server-side and stored encrypted. This eliminates both the local
`claude setup-token` CLI dependency and the hand-pasting of the secret token,
which is exactly the operator directive.

**ADR-ML-1 compliance:** operator authorizes on *their own* Anthropic account on
*Anthropic's own* pages; credentials never cross providers (stored as
`anthropic`/`oauth_token` only); manual API-key paste retained as honest
fallback; token values never logged/committed (vault + `…last4` hints only); no
silent quota fallthrough (existing 429→block path unchanged).

---

## 2. Verified constants to hardcode (single module)

| Purpose | Value | Source |
|---|---|---|
| Client id (default) | `9d1c250a-e61b-44d9-88ed-5944d1962f5e` | extract §1 |
| Client-id override env | `CLAUDE_CODE_OAUTH_CLIENT_ID` (optional) | extract §1 |
| Authorize URL (subscription) | `https://claude.com/cai/oauth/authorize` | extract §1/§3 (`loginWithClaudeAi=true`) |
| Token URL | `https://platform.claude.com/v1/oauth/token` | extract §1/§4 |
| Redirect URI (manual) | `https://platform.claude.com/oauth/code/callback` | extract §1/§4 |
| Scope | `user:inference` | extract §2/§7 (`inferenceOnly`) |
| `code_challenge_method` | `S256` | extract §3 |
| Extra authorize param | `code=true` | extract §3 |
| Requested lifetime | `expires_in = 31536000` | extract §7 (`rZe`) |
| Inference transport (already live) | `Authorization: Bearer <tok>` + `anthropic-beta: oauth-2025-04-20` | llm_client.py:793-820 |

Exchange & refresh bodies are **JSON** (`Content-Type: application/json`), the
exchange body includes **`state`**, and both POST to
`platform.claude.com/v1/oauth/token`. (These three details differ from the
deleted `anthropic_oauth.py`; do NOT copy its form-encoded / api.anthropic.com
shape.)

---

## 3. End-to-end flow

```
[modal] "Connect with Anthropic"  ─POST /agents/providers/anthropic/oauth/start
        server: gen verifier+S256 challenge, gen random state,
                AnthropicOAuthStateRepository.create(state, userId, verifier)
        ← { authorizeUrl }                     (verifier/state NEVER sent raw twice)
[modal] window.open(authorizeUrl, "_blank")    → Anthropic claude.com consent page
[user]  logs into their Anthropic (Pro/Max) account, clicks Authorize
[anthropic] redirects to platform.claude.com/oauth/code/callback → displays "code#state"
[user]  copies "code#state", pastes into the modal's code field, submits
        ─POST /agents/providers/anthropic/oauth/exchange { pastedCode }
        server: split "#"→(code,state); consume(state)→(userId,verifier)  [single-use, CSRF]
                assert userId == current_user.id
                POST token_url JSON {grant_type:"authorization_code", code,
                     redirect_uri:MANUAL_REDIRECT_URL, client_id, code_verifier:verifier,
                     state, expires_in:31536000}
                → {access_token: sk-ant-oat01-…, refresh_token: sk-ant-ort01-…, expires_in}
                persist (see §4.3); run real verify round-trip; mark_verified
        ← masked ProviderCredential row (…last4 + verify status)
[modal] shows "Connected — subscription (…AbC)"; badge from server truth
```

---

## 4. Backend changes

### 4.1 `apps/api/app/services/anthropic_oauth.py` — RE-ADD (compliant rewrite)
Do NOT `git revert` the deleted module — its endpoints/URLs/authMode are wrong.
New module, self-contained, no network in unit tests (isolate the POST):

- Constants from §2 (module-level).
- `client_id() -> str` — env `CLAUDE_CODE_OAUTH_CLIENT_ID` else the hardcoded
  public id. (Never raises; the public id is always available — unlike the old
  `OAuthNotConfiguredError` path.)
- `generate_pkce() -> (verifier, challenge)` — reuse old S256 impl verbatim
  (`secrets.token_urlsafe(64)` → sha256 → urlsafe_b64 rstrip `=`).
- `generate_state() -> str` — `secrets.token_urlsafe(32)` (opaque; URL-safe so it
  survives the `code#state` round-trip; NOT a JWT — the verifier is held
  server-side in `AnthropicOAuthState`, so no signed state needed).
- `build_authorize_url(challenge, state) -> str` — replicate `hXn` for the
  subscription/manual/inference-only case: base `CLAUDE_AI_AUTHORIZE_URL`, params
  `code=true, client_id, response_type=code, redirect_uri=MANUAL_REDIRECT_URL,
  scope=user:inference, code_challenge, code_challenge_method=S256, state`.
- `_post_token(body) -> dict` — isolated `httpx.post(TOKEN_URL, json=body,
  timeout=30)`; non-2xx → `OAuthExchangeError` (text truncated, **token never in
  message**). Monkeypatched in tests.
- `exchange_code(code, verifier, state) -> dict` — JSON body per §4 incl.
  `expires_in=31536000`; normalize `{access_token, refresh_token, expires_at,
  scope}` (`expires_at = now + expires_in`).
- `refresh_tokens(refresh_token) -> dict` — JSON body per §5, `scope=[user:inference]`.
- `_is_expiring(expires_at)` + `refresh_if_needed(user_id)` — port the old logic
  but persist as **`oauth_token`** (§4.3), not `subscription_oauth`; on refresh
  failure `AnthropicOAuthTokenRepository.mark_needs_reauth(user_id)` (never reuse
  an expired token — solves the ML-agents-cred-001 expiry root cause).
- `persist_tokens(user_id, tok)` — see §4.3.

### 4.2 New endpoints in `apps/api/app/routers/agents.py`
Mounted under existing `/agents` prefix. Scope to the **deployment-wide**
Anthropic credential (the window the operator actually uses — RCA shows
`PUT /agents/providers/anthropic/credential`), but require an authenticated
`current_user` and key the refresh store by `current_user["id"]`.

- `POST /providers/anthropic/oauth/start` → `{ authorizeUrl: str }`
  - Generate verifier/challenge/state; `AnthropicOAuthStateRepository().create(
    state, current_user["id"], verifier)`; return `build_authorize_url(...)`.
  - 503 if `AETHER_CREDENTIAL_KEY` absent (refresh token can't be stored honestly).
- `POST /providers/anthropic/oauth/exchange` body `{ pastedCode: str }` → masked row
  - `code, _, state = pastedCode.strip().partition("#")`; 422 (honest, no token in
    msg) if either empty.
  - `row = AnthropicOAuthStateRepository().consume(state)`; 400 if `None`
    (unknown/expired/replayed).
  - 403 if `row["userId"] != current_user["id"]`.
  - `tok = anthropic_oauth.exchange_code(code, row["codeVerifier"], state)`;
    `OAuthExchangeError` → 502 honest ("Anthropic rejected the authorization
    code — restart Connect with Anthropic").
  - `anthropic_oauth.persist_tokens(current_user["id"], tok)` (§4.3).
  - Best-effort real verify (`verify_provider_credential("anthropic")`) +
    `mark_verified`; return `_provider_status_object("anthropic", user_id)`.
- Delete the "OAuth was REMOVED" tombstone comment block (agents.py:2365-2373).

### 4.3 Storage (`persist_tokens`) — reuse existing repos, additive only
Both stores already exist (`user_provider_credential.py`) with `oauth_token`
already in the widened CHECK — **no new DDL required**.
- Live access token → `ProviderCredentialRepository().upsert("anthropic",
  auth_mode="oauth_token", secret=access_token, base_url=None)`. This is the row
  `resolve_credential("anthropic")` reads DB-first; `anthropic_auth_headers`
  already emits Bearer + `anthropic-beta: oauth-2025-04-20` for `oauth_token`
  (llm_client.py:793-820) — **transport unchanged**.
- Refresh material → `AnthropicOAuthTokenRepository().upsert(user_id,
  access_ciphertext=enc(access), refresh_ciphertext=enc(refresh),
  secret_hint=…last4, expires_at=…, scopes="user:inference")`.
- Also call `env_file_writer.sync_oauth_token_env(access_token)` (mirror the
  existing paste path, agents.py:2189-2195) so a restart survives — best-effort,
  DB row is source of truth, token never logged.

### 4.4 Auto-refresh hook (solves the expiry BLOCKER, ML-agents-cred-001)
Call `anthropic_oauth.refresh_if_needed(operator_user_id)` at the start of the
live Anthropic call path when `auth_mode == "oauth_token"` and a refresh row
exists — placed in `resolve_credential`/`_call_live` before the Messages POST.
Must be best-effort and MUST NOT introduce a silent cross-provider fallthrough:
on refresh failure, mark needs_reauth and let the existing honest
no-credential / 401 path surface (never substitute another provider).
[UNSURE — exact call site: see §8.2]

### 4.5 Untouched invariants (do NOT modify)
`resolve_provider` semantics (`/`→openrouter, bare `claude-*`→anthropic);
`anthropic_auth_headers`; the 429 subscription-quota→`AgentQuotaBlock` path;
the fabrication/entailment guards; `subscription_oauth` stays blocked
(`_resolution_is_supported`). The new tokens are `oauth_token`, already supported.

---

## 5. Frontend changes

### 5.1 `apps/web/src/components/agents/api.ts`
Add two typed calls mirroring `putProviderCredential` (same `request` helper,
same error mapping):
- `startAnthropicOAuth(): Promise<{ authorizeUrl: string }>` →
  `POST /agents/providers/anthropic/oauth/start`.
- `exchangeAnthropicOAuth(pastedCode: string): Promise<Provider>` →
  `POST /agents/providers/anthropic/oauth/exchange`.
Zod-validate responses (reuse `ProviderSchema` for the exchange result).

### 5.2 `apps/web/src/components/agents/ProviderConfigModal.tsx`
When `view.id === "anthropic"` add a THIRD, primary option ABOVE the two paste
modes: **"Connect with Anthropic (subscription)"**.
- Renders a "Connect with Anthropic" button (not a secret input). On click:
  `const { authorizeUrl } = await startAnthropicOAuth(); window.open(authorizeUrl,
  "_blank", "noopener");` then reveal a **"Paste the code from Anthropic"** field
  + "Complete connection" button that calls `exchangeAnthropicOAuth(code)`.
- The existing `api_key` and `oauth_token` (manual `setup-token` paste) options
  remain as the **honest fallback** (ADR-ML-1) — do not remove them.
- Copy: "Opens Anthropic's sign-in page in a new tab. Approve access to your
  Claude Pro/Max account, then paste the one-time code shown by Anthropic. Your
  token is created on the server — you never copy the token yourself."
- No token/secret is ever placed in component state on this path; only the
  short-lived `code#state` string. Reuse the existing `data-testid` conventions
  (`authmode-connect`, `anthropic-oauth-start`, `anthropic-oauth-code-input`,
  `anthropic-oauth-complete`).
- `ProviderAuthMode` union gains `"connect"` (UI-only mode; server still stores
  `oauth_token`).

---

## 6. Test plan (fail-before / pass-after) — under `flock /tmp/aether-pytest.lock`

**Backend — new `apps/api/tests/test_ml_agents_cred_002_oauth_connect.py`:**
1. `build_authorize_url` contains exactly: `claude.com/cai/oauth/authorize`,
   `client_id=9d1c250a-…`, `response_type=code`,
   `redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback`,
   `scope=user%3Ainference`, `code_challenge_method=S256`, `state=…`, `code=true`.
   FAIL-BEFORE: module absent → ImportError.
2. `start` endpoint: 200 → `authorizeUrl`; a row exists in `AnthropicOAuthState`
   for the user with a stored verifier. 503 when `AETHER_CREDENTIAL_KEY` unset.
3. `exchange` happy path (monkeypatch `_post_token` → fake
   `{access_token:"sk-ant-oat01-XYZ", refresh_token:"sk-ant-ort01-…",
   expires_in:31536000}`): 200 masked row; `ProviderCredential` anthropic row has
   `authMode='oauth_token'`; `AnthropicOAuthToken` has a refresh cipher; the raw
   token appears in NO response body and NO log line.
4. `exchange` sends the correct **JSON** body (assert captured POST: keys
   `grant_type=authorization_code, code, redirect_uri=MANUAL_REDIRECT_URL,
   client_id, code_verifier, state, expires_in`).
5. CSRF/replay: `exchange` with unknown/expired state → 400; a second `exchange`
   reusing a consumed state → 400 (single-use).
6. Ownership: state minted by user A, exchanged as user B → 403.
7. Malformed paste (no `#`, or empty half) → 422, message names neither token.
8. `refresh_if_needed`: expired row + monkeypatched `refresh_tokens` → new access
   persisted as `oauth_token`; refresh failure → `mark_needs_reauth`, and
   `resolve_credential` does NOT return a cross-provider credential (no silent
   fallthrough).
9. Transport regression: a persisted `oauth_token` still yields Bearer +
   `anthropic-beta: oauth-2025-04-20` via `anthropic_auth_headers` (guards §4.5).

**Frontend — `ProviderConfigModal` vitest:**
10. Anthropic modal shows the "Connect with Anthropic" option + button.
11. Clicking Connect calls `startAnthropicOAuth` and `window.open(authorizeUrl)`
    (mock `window.open`); the code field then appears.
12. Completing calls `exchangeAnthropicOAuth(code)` and renders the returned
    masked/connected state; the raw code is never persisted after submit.
13. api_key / setup-token paste fallbacks remain rendered (ADR-ML-1).

All new tests must be RED before the fix and GREEN after; run the existing
`test_gap_p7_def_a_dual_mode.py` + `test_gap_p5_auth_compliance.py` +
`test_provider_config.py` to prove no regression on transport / no-cross-provider
/ blocked-`subscription_oauth`.

---

## 7. Cross-cutting compliance checklist
- Additive DB only: **zero new DDL** (reuses existing tables; `oauth_token`
  already in the CHECK). ✅
- Secrets via `os.environ` only; `CLAUDE_CODE_OAUTH_CLIENT_ID` optional override. ✅
- Credentials never cross providers: stored as `anthropic`/`oauth_token`; refresh
  scoped to anthropic. ✅
- No silent fallback / no silent model substitution: refresh failure → honest
  needs_reauth + surfaced error. ✅
- Fabrication/entailment guards untouched. ✅
- Token values never logged/committed; only `…last4` hints + masked rows. ✅
- Commit (fixer, later): `fix(ML-agents-cred-002): in-app Connect-with-Anthropic OAuth`.

---

## 8. UNSURE / orchestrator decisions

**8.1 Endpoint scoping — deployment-wide vs per-user.** RECOMMENDED: deployment-wide
(`/agents/providers/anthropic/oauth/*`) storing into `ProviderCredential`, because
the RCA shows the operator uses the deployment-wide `PUT /agents/providers/
anthropic/credential` window and ADR-ML-1 frames this as a single-operator
product. ALTERNATIVE: put it on the per-user path (`/agents/user/providers/…`,
storing into `UserProviderCredential`), which is more multi-tenant-correct but is
NOT the window the operator hit. Refresh material is user-keyed either way
(`AnthropicOAuthToken` PK = userId). Needs an orchestrator ruling before coding.

**8.2 Auto-refresh call site.** RECOMMENDED: inside the live-call resolution for
anthropic `oauth_token` (once per run, before the Messages POST). ALTERNATIVE: a
lightweight scheduled sweep. The 1-year `expires_in` makes refresh rarely urgent,
but the ML-agents-cred-001 root cause (operator's token expired) means auto-refresh
is REQUIRED, not optional. Confirm the site so it can't create a hot-path per-token
network call storm.

**8.3 Authorize host.** Using `CLAUDE_AI_AUTHORIZE_URL = https://claude.com/cai/
oauth/authorize` (current, subscription/`loginWithClaudeAi` branch). The legacy
`https://claude.ai/oauth/authorize` (historical aether + mechanics doc) is an
alias that may still 3xx-redirect; the fixer should smoke-test the built URL opens
Anthropic's consent page in a real browser before sign-off. [ASSUMED-PENDING-PROBE
— not exercised, per no-interactive-flow constraint.]

**8.4 Token-endpoint response field names / long-lived-refresh availability.**
`{access_token, refresh_token, expires_in}` is [INFERRED-FROM-BINARY]; the refresh
token's existence for an inference-only long-lived grant is [VERIFIED] indirectly
(operator's `~/.claude/.credentials.json` contains `refreshToken` sk-ant-ort01-,
RCA §4). The exchange test (§6.3) pins the parser to that shape; a live smoke test
by the fixer is the final gate.

---

## 9. Risks
- **R1 (client-impersonation):** we reuse Claude Code's public client id. This is
  what `setup-token` does with the operator's own account/consent; ADR-ML-1
  authorizes it. If Anthropic later gates the manual redirect to first-party UAs,
  the honest fallback (manual `setup-token` paste + API key) still works — no
  silent breakage.
- **R2 (Cloudflare bot challenge on the authorize URL):** irrelevant — the URL is
  opened in the operator's real browser, not fetched server-side (mechanics doc §5).
- **R3 (state via `#` fragment vs query):** Anthropic returns `code#state` as a
  single copyable string (not a URL fragment we must read) — we parse the pasted
  string, so no fragment-stripping ambiguity.
</content>
