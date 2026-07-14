# Provider-Config Run — In-UI Agent Provider Configuration + Gmail PKCE Fix

Run started 2026-07-14. Orchestrator session 6efd74e1. Discovery evidence: `uat/reports/evidence/provider-config/` (scout-fe/be/db/test/oauth, gitignored by design).

## 0. Requirements register

| REQ | Success criterion | Deliverable | Production evidence (filled by QA) |
|---|---|---|---|
| REQ-PC-1 | Agents screen configures provider credentials fully in-UI; the two `.env`-instruction strings (`apps/web/src/components/agents/logic.ts:42,61`) are gone; no UX path tells the user to edit `.env` | FE branch | |
| REQ-PC-2 | Anthropic provider supports two auth modes: `subscription_oauth` (Claude Max token `sk-ant-oat…` → `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20`) and `api_key` (`sk-ant-api…` → `x-api-key`) | BE branch | |
| REQ-PC-3 | OpenRouter provider: `api_key` mode (`Authorization: Bearer`) | BE branch | |
| REQ-PC-4 | **Billing separation is structural**: a model whose catalog provider is `anthropic` only ever calls `api.anthropic.com` with the Anthropic credential (native Messages API); every other model only ever calls OpenRouter with the OpenRouter credential. No silent cross-provider fallback — missing credential = honest error | BE branch | |
| REQ-PC-5 | Credentials encrypted at rest (Fernet, key `AETHER_CREDENTIAL_KEY` from server env), masked in every API response (last-4 hint only), never logged | BE branch | |
| REQ-PC-6 | `/agents/providers` status derives DB-first with honest `source`: `database` / `environment` (legacy env fallback) / `none`; D-0020 never-fabricate-connection preserved (409 on enable without real credential) | BE branch | |
| REQ-PC-7 | Test-connection endpoint performs a real provider round-trip and records honest result | BE branch | |
| REQ-PC-8 | Per-agent model selection (existing `PUT /agents/config/{key}` + AgentConfig) is honored by the runtime LLM path so Anthropic-billed and OpenRouter-billed models can coexist across agents | BE branch | |
| REQ-GM-1 | "Connect Gmail" completes token exchange (no `(invalid_grant) Missing code verifier`); PKCE verifier carried in the signed state JWT and replayed at `fetch_token`; real `build_consent_url → exchange_code` round-trip covered by tests (no `exchange_code` monkeypatching) | Gmail branch | |
| REQ-PC-9 | Wireframe traceability: `design/screens/agents.html` updated to show the provider-config UI so app and wireframe stay 1:1 | FE branch | |

## 1. Binding API contract (both fixers code against this verbatim; deviations need orchestrator ruling)

```
# NOTE (ruled 2026-07-14): status enum is the EXISTING codebase vocabulary
# 'connected'|'warning'|'unconfigured' with a 'name' field (NOT 'not_configured'/'label').
# BE and FE both correctly preserved it; the enriched fields below are purely additive.
GET  /agents/providers            → [{ id, name, status: 'connected'|'warning'|'unconfigured',
                                       source: 'database'|'environment'|'none',
                                       authMode: 'api_key'|'subscription_oauth'|null,
                                       secretHint: string|null,          // e.g. '…x4Qz'
                                       lastVerifiedAt: string|null, lastVerifyStatus: 'ok'|'failed'|null,
                                       detail: string }]
PUT  /agents/providers/{id}/credential   body { authMode, secret, baseUrl? } → provider row (masked)
DELETE /agents/providers/{id}/credential → provider row (falls back to env source if present)
POST /agents/providers/{id}/verify       → { ok: bool, status, detail }   // real round-trip
```
Existing endpoints unchanged: `GET /agents/catalog|providers|stats`, `PUT /agents/config/{key}`, `PUT /agents/providers/{id}`, `POST /agents/test-run`.

## 2. Orchestrator rulings (ADRs — binding, do not re-litigate)

- **ADR-PC-1 (Gmail PKCE):** carry `code_verifier` as a plain `cv` claim in the existing signed state JWT (`google_oauth.py encode_state/decode_state`). Rationale: confidential client — token exchange still requires `client_secret`; state is signed, audience-scoped, 5-min TTL; PKCE here is defense-in-depth, and this restores exactly the pre-PKCE confidential-client security floor. A server-side verifier store was considered and rejected as a larger change with no material gain for this deployment. Documented in code.
- **ADR-PC-2 (no billing cross-fallback):** if the resolved provider for a model has no credential, the call fails with an honest, user-visible error. Never reroute an Anthropic-provider model through OpenRouter or vice versa — that is precisely the billing contamination this feature exists to prevent.
- **ADR-PC-3 (vault):** Fernet symmetric encryption; key from `AETHER_CREDENTIAL_KEY` env (generated once at deploy, appended to server `.env`). DB stores ciphertext + last-4 hint. Missing key ⇒ credential writes fail with honest 503-style error; reads degrade to `source: environment|none`.
- **ADR-PC-4 (no secret migration):** existing `.env` `OPENROUTER_API_KEY` is NOT auto-copied into the DB. Env remains a recognized fallback (`source: 'environment'`); the user replaces it via UI at their own pace.
- **ADR-PC-5 (catalog honesty):** Anthropic catalog model IDs must be real, currently-served IDs (`claude-opus-4-8` default reasoning tier, `claude-sonnet-5`, `claude-haiku-4-5`; `claude-fable-5` may be listed only as an explicit user choice). Cosmetic/fake IDs are defects (truth bar §SOP-5).
- **ADR-PC-6 (scope exclusion, recorded gap):** GoogleCredential plaintext access/refresh tokens are a pre-existing security gap — OPEN follow-up item GAP-PC-SEC-1, not fixed in this run (would touch the OAuth fix mid-flight; needs its own migration of live rows).
- **ADR-PC-7 (parallel-build safety):** each fixer works in its own `git worktree` on its own branch; ALL pytest invocations (fixers, reviewers, QA) run under `flock /tmp/aether-pytest.lock` because the suite shares one `aether_test` schema. Web `pnpm` work is serialized to the FE lane only.

## 3. Dispatch plan

| Lane | Branch | Fixer | Reviewer (adversarial, cross-model) |
|---|---|---|---|
| BE: vault + credential endpoints + LLM routing/transports | `feat/provider-config-be` | T1 opus | T2 sonnet |
| FE: agents-screen config UI + wireframe | `feat/provider-config-fe` | T1 opus | T2 sonnet |
| Gmail PKCE fix | `fix/gmail-pkce` | T2 sonnet | T1 opus |

Merge order after approvals: `fix/gmail-pkce` → `feat/provider-config-be` → `feat/provider-config-fe`. Then deploy (build, restart `aether-web`/`aether-api`, ensure `AETHER_CREDENTIAL_KEY` in server `.env`, health checks) → independent production QA (sole closure authority) → regression sweep (`uat/phase4_sweep.py`, `uat/uat_runner.py`).

## 4. Gap/It­em ledger

| ID | Item | Severity | Status |
|---|---|---|---|
| GAP-PC-001 | UI instructs `.env` editing instead of in-app config (logic.ts:42,61) | HIGH | OPEN → dispatched FE |
| GAP-PC-002 | No in-app credential entry/storage exists; env-var presence is the only "connected" signal, keys never validated | HIGH | OPEN → dispatched BE |
| GAP-PC-003 | No Anthropic transport exists (client is OpenAI-compatible only); Anthropic-billed models impossible today | HIGH | OPEN → dispatched BE |
| GAP-PC-004 | Gmail OAuth token exchange fails: PKCE verifier generated then discarded (google_oauth.py:143-156 vs 170-191) | CRITICAL | OPEN → dispatched Gmail |
| GAP-PC-005 | Generic provider detail string hardcodes "standby (Anthropic is the active path)" regardless of truth (agents.py:257-262) | MEDIUM | OPEN → dispatched BE |
| GAP-PC-SEC-1 | GoogleCredential access/refresh tokens stored plaintext | HIGH | OPEN (follow-up run, ADR-PC-6) |

## 5. Run log

- 2026-07-14: Discovery complete (wf_7cd11682-74d 4/4 scouts, wf_7a240985-bb2 oauth RCA confirmed). Plan + contract + ADRs recorded (this doc). Build wave dispatched.
- 2026-07-14: Build complete (wf_041f7edb-494). BE @c8e6613, FE @2d33f07, Gmail @18bdcbe. Branches reconciled onto feat/provider-config-be, feat/provider-config-fe, fix/gmail-pkce.
- 2026-07-14: Adversarial cross-model review (wf_2d497cd5-156). FE APPROVE, Gmail APPROVE. BE REJECT — 2 required changes: (CRIT) GAP-PC-006 billing crossover: openrouter env-fallback can adopt the Anthropic secret when AETHER_LLM_API_KEY+anthropic-base is set (llm_client.py resolve_credential openrouter branch missing the mirror 'anthropic.com' guard); (HIGH) GAP-PC-001b .env-leak via detail/409 strings (agents.py 235/238/242/257/271/274/1008). Bounded BE re-fix dispatched.

## 6. Gap ledger updates (review)

| ID | Item | Severity | Status |
|---|---|---|---|
| GAP-PC-006 | OpenRouter env-fallback adopts Anthropic secret/base when AETHER_LLM_API_KEY+anthropic base set → non-Claude model billed to Anthropic (cross-provider crossover, violates ADR-PC-2) | CRITICAL | OPEN → BE re-fix |
| GAP-PC-001b | `.env` instruction leaks to UI via backend `detail` strings + 409 message (FE renders p.detail) | HIGH | OPEN → BE re-fix |
| GAP-PC-004 (gmail) | PKCE verifier fix | CRITICAL | VERIFIED-CLOSED (fix deployed + confirmed live: state JWT carries `cv`, code_challenge present, redirect URI exact) |
| REQ-PC-1..9 FE | in-app config UI | HIGH | VERIFIED-CLOSED (prod QA2 PASS) |

## 7. Closure (2026-07-14)

**All lanes merged to main, deployed, and independently QA-verified on production.** Final HEAD chain: gmail(fa5bfad) → be(4292971) → fe(d0b79d5) → test-hermeticity(b1d61a2) → deploy-parser-fix(5c8a83a) → toast-honesty(6e526d4).

Gates: pytest 370 / vitest 244+ / web build clean. Deployed: `AETHER_CREDENTIAL_KEY` (Fernet) in server env; `aether-api`/`aether-web` restarted; health 200.

- **GAP-PC-006** (billing crossover) — CLOSED: re-fix + cross-model re-verify both directions (0 HTTP, honest raise).
- **GAP-PC-001b** (.env leak via detail/409) — CLOSED: strings rewritten to in-app vocabulary; grep clean.
- **GAP-PC-007** (deploy blocker) — `start-api.sh`/`start-web.sh` `IFS='='` parser stripped the Fernet key's trailing `=` (44→43 chars) → vault 503 on every save. FIXED (split on first `=`); prod save round-trip now 200. CLOSED.
- **GAP-PC-008** (toast honesty) — credential save/verify toast showed generic "AI model is busy" for 503/422; now surfaces the real backend detail. CLOSED.

**Independent production QA (QA2): PASS** — save round-trip (200, masked, reload-persist, delete), subscription-mode save (authMode subscription_oauth), honest verify failure (real Anthropic 401), corrected toast, 0 console errors, no test credential left behind. Evidence: `uat/reports/evidence/provider-config/qa2/`.

**Deferred (recorded, not in scope):** GAP-PC-SEC-1 (GoogleCredential plaintext tokens, ADR-PC-6) — future run.

**USER ACTION REQUIRED (external, cannot be automated):** the real Connect-Gmail inbox round-trip needs interactive Google consent — click **Connect Gmail** on the Email screen and approve. The PKCE fix + redirect URI are confirmed live, so it should now complete without the "Missing code verifier" error. Ping me after and I'll verify triage/draft/label on the live inbox.
