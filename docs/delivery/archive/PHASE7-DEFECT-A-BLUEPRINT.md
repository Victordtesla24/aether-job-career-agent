# PHASE-7 DEFECT-A BLUEPRINT — Claude Code OAuth token (dual-mode Anthropic credential)

- **Gap:** GAP-P7-DEF-A (CRITICAL, priority 1) — `docs/delivery/phase7-gap-analysis.json`
- **Ruling:** ADR-P7-01 (Phase-7 §14 supersedes ADR-P6-OAUTH; pasted `claude setup-token` ≠ in-app OAuth flow)
- **Spec:** `/home/ubuntu/aether-subscription-prompt.md` §14.1–14.7, §12 Journey J1
- **Author:** arch sub-agent (claude-opus-4). **Status: DRAFT — REQUIRES fable-5 APPROVAL BEFORE ANY IMPLEMENTATION.**
- **PART-1 wire evidence:** `uat/reports/evidence/phase7/claude-code-token-verification.md`

> Every claim below is tagged `[VERIFIED-WITH-SOURCE: file:line | live probe]`, `[INFERRED]`, or `[ASSUMED-PENDING-PROBE: <named probe>]`. There are **zero** unresolved `[ASSUMED-PENDING-PROBE]` items; the two residual probes are pre-implementation checks the fixer runs first (§8).

---

## 0. PART-1 observed wire mechanics (governs everything below)

| Attempt | Header(s) | HTTP | Meaning |
|---|---|---|---|
| oat01 + `x-api-key` | `x-api-key: <token>` | **401** invalid x-api-key | x-api-key REJECTS oat01 |
| oat01 + Bearer + beta | `Authorization: Bearer <token>` + `anthropic-beta: oauth-2025-04-20` | **200** real completion | working transport |
| oat01 + x-api-key + beta | `x-api-key` + `anthropic-beta` | **401** | x-api-key still rejected |

[VERIFIED-WITH-SOURCE: live probe, 2026-07-17, `claude-code-token-verification.md`]. Token prefix `sk-ant-oat01-`, length 108.

**Consequence:** §14.1/§14.4's "both modes use `x-api-key`" is FALSE. The design routes headers **per authMode**:
- `api_key` (`sk-ant-api…`) → `x-api-key: <secret>` (unchanged) [VERIFIED-WITH-SOURCE: llm_client.py:586-587]
- `oauth_token` (`sk-ant-oat01-…`) → `Authorization: Bearer <secret>` + `anthropic-beta: oauth-2025-04-20` [VERIFIED-WITH-SOURCE: live probe CALL2; the same combo is documented in the repo's own removed comment llm_client.py:578-580]

---

## 1. Naming decision — authMode value = `oauth_token` (NOT `subscription_oauth`)

The codebase already carries a **`subscription_oauth`** authMode from the Phase-6 in-app OAuth flow that ADR-P6-OAUTH removed for compliance (PKCE `AnthropicOAuthState`/`AnthropicOAuthToken` tables, `_resolution_is_supported` blocks it) [VERIFIED-WITH-SOURCE: user_provider_credential.py:70,86-108; llm_client.py:350-359].

Phase-7 introduces a **distinct** value **`oauth_token`** for the user-pasted `claude setup-token` credential:

- §14 mandates the literal string `oauth_token` (billingAuditJson.authMode, GATE-05, J1 step 6) [VERIFIED-WITH-SOURCE: aether-subscription-prompt.md §14.5, §12 J1 step 6].
- Keeping `subscription_oauth` **separate and still-blocked** preserves ADR-P7-01's NON-goal (no in-app OAuth flow) and keeps the retained legacy-rejection test valid [VERIFIED-WITH-SOURCE: test_gap_p5_auth_compliance.py:118-141].
- On the wire both are identical (Bearer+beta); the distinction is provenance (pasted token = allowed; in-app authorize flow = prohibited). [INFERRED from ADR-P7-01 + PART-1]

**Prefix mapping (single source of truth = the secret prefix):**
- `sk-ant-api` → `api_key`
- `sk-ant-oat01-` → `oauth_token` (supported)
- any other `sk-ant-oat…` → `subscription_oauth` (legacy, blocked — never accepted by the write path, never used at run time)
- anything else → 422 [VERIFIED-WITH-SOURCE: design; consistent with llm_client.py:340-347]

---

## 2. Validation change (§14.2)

**File/site:** `apps/api/app/routers/agents.py:1435-1458` `_validate_provider_auth(provider, auth_mode, secret)` — called by both `put_provider_credential` (deployment-wide, :1476) and `put_user_credential` (per-user, :1576) [VERIFIED-WITH-SOURCE: agents.py:1435,1476,1576].

**Current (broken):** rejects any authMode ≠ `api_key` and any anthropic secret not `sk-ant-api` → the 422 observed in probe-p7-08a [VERIFIED-WITH-SOURCE: agents.py:1443-1457].

**Design:** introduce `_detect_anthropic_auth_mode(value) -> str` that **derives** the mode from the secret prefix (prefix is authoritative), and rewire `_validate_provider_auth`:

1. For `provider == "anthropic"`: compute `detected = _detect_anthropic_auth_mode(secret)`.
   - `sk-ant-api…` → `api_key`; `sk-ant-oat01-…` → `oauth_token`; else → **422 naming BOTH formats**.
2. **Anti-mislabel guard (no silent credential-type fallthrough):** if the client-supplied `body.authMode` is non-null and contradicts `detected`, raise 422 ("credential prefix is a `<detected>`; you selected `<authMode>`"). Never silently store a mismatched label — a mislabeled row would pick the wrong header and fail at run time. [Design; enforces prompt prohibition "no silent credential-type fallthrough"]
3. The stored authMode is always `detected` (server-derived), not the client's claim.
4. `subscription_oauth` (legacy label, or a non-`oat01` `sk-ant-oat` secret) stays a 422 for the anthropic write path.

**422 message (names both formats, per GATE-04 / J1 step 10):**
```
Anthropic credential not recognized. Console API keys start with 'sk-ant-api'.
Claude Code OAuth tokens start with 'sk-ant-oat01-'. Check which credential you are pasting.
```
The value is **never** included in the message or logs [VERIFIED-WITH-SOURCE: existing pattern, agents.py never logs secret].

**Body model:** `ProviderCredentialBody.authMode` is `str = Field(min_length=1)` (no pattern) → already accepts `oauth_token` [VERIFIED-WITH-SOURCE: agents.py:1430]. `AgentConfigUpdate.authMode` is `Field(pattern="^(api_key)$")` and **must widen to `^(api_key|oauth_token)$`** so a user can pin an agent to oauth mode [VERIFIED-WITH-SOURCE: agents.py:1111].

---

## 3. Storage (§14.3)

### 3.1 Vault (unchanged)
Fernet encrypt/decrypt via `AETHER_CREDENTIAL_KEY`; only a `…last4` hint is ever returned [VERIFIED-WITH-SOURCE: credential_vault.py:66-94]. Key present in prod `.env` [VERIFIED-WITH-SOURCE: live `.env` key scan, 2026-07-17]. Ciphertext columns already exist on both `ProviderCredential` and `UserProviderCredential` [VERIFIED-WITH-SOURCE: live DB columns, 2026-07-17].

### 3.2 authMode column + additive migration
- **Deployment-wide `ProviderCredential.authMode`** — `text NOT NULL`, **no CHECK** → stores `oauth_token` with **no migration** [VERIFIED-WITH-SOURCE: provider_credential.py:62; live DB, no constraint found]. **This is the table the modal writes to** (§5) [VERIFIED-WITH-SOURCE: api.ts:259 → agents.py:1461].
- **Per-user `UserProviderCredential.authMode`** — `text NOT NULL CHECK ("authMode" IN ('api_key','subscription_oauth'))`, live constraint name `UserProviderCredential_authMode_check` on schemas `aether` AND `aether_test` [VERIFIED-WITH-SOURCE: user_provider_credential.py:69-70; live `pg_constraint` query, 2026-07-17]. **Must widen additively** (superset — zero rows invalidated, zero data loss):

```sql
-- Idempotent, additive widening. Run inside _ensure_user_agent_tables()
-- (the only DDL that executes in prod — no migration runner) under the existing
-- _USER_AGENT_LOCK advisory lock so concurrent first-hits cannot race.
ALTER TABLE "UserProviderCredential"
  DROP CONSTRAINT IF EXISTS "UserProviderCredential_authMode_check";
ALTER TABLE "UserProviderCredential"
  ADD CONSTRAINT "UserProviderCredential_authMode_check"
  CHECK ("authMode" IN ('api_key','subscription_oauth','oauth_token'));
```
Also update the inline CHECK in the `CREATE TABLE IF NOT EXISTS` (user_provider_credential.py:70) to the 3-value set for fresh installs. Documentary mirror: append to `apps/api/migrations/0020_per_user_agent_creds.sql` (record only). [VERIFIED-WITH-SOURCE: user_provider_credential.py:8,50-83]. **Owner: `migrator` agent (additive-only).** No DROP TABLE/COLUMN, no ALTER TYPE.

### 3.3 Atomic `.env` write of `CLAUDE_CODE_OAUTH_TOKEN` (oauth_token mode ONLY)

**CRITICAL CORRECTION to §14.3:** the spec's `env_path="…/apps/api/.env"` is WRONG — **`apps/api/.env` does not exist**. The real env file is the **repo-root** `.env` [VERIFIED-WITH-SOURCE: `ls apps/api/.env` → No such file; root `.env` 600 perms; start-api.sh:20 reads `/home/ubuntu/github_repos/aether-job-career-agent/.env`, 2026-07-17].

Design:
- Resolve the path from a new setting `AETHER_ENV_FILE_PATH` defaulting to `/home/ubuntu/github_repos/aether-job-career-agent/.env` (do not hardcode inline). [Design]
- Write **only** for `oauth_token` mode; `api_key` mode never touches `.env` (§14.3, GATE test `test_api03_does_not_write_env_var`).
- Atomic sequence: read current content → replace-or-append the single `CLAUDE_CODE_OAUTH_TOKEN=<value>` line → `tempfile.mkstemp(dir=<same dir>)` → `os.fchmod(fd, 0o600)` → write → `os.rename(tmp, env)` (same-filesystem atomic) → on any error `os.unlink(tmp)` and re-raise. Value NEVER logged/returned/echoed [VERIFIED-WITH-SOURCE: §14.3 reference impl is sound; matches secure-write pattern].
- **Format compatibility:** the line must be unquoted `KEY=value` with no spaces around `=`. `start-api.sh` splits on the first `=` and strips surrounding quotes; the oat token is `[A-Za-z0-9_-]` so it survives verbatim [VERIFIED-WITH-SOURCE: start-api.sh:9-23; token charset from PART-1]. The final `.env` stays mode 600 (tmp chmod'd before rename) [VERIFIED-WITH-SOURCE: root `.env` is `-rw-------`].
- `.env` is gitignored → the secret never enters git [VERIFIED-WITH-SOURCE: `git check-ignore .env` → IGNORED, 2026-07-17].

---

## 4. Test-connection per mode (§14.4)

**Design decision — REUSE the existing endpoint, do NOT add a new `/test-connection`.** OBSERVED reality already has `POST /agents/providers/{provider}/verify` (deployment-wide) and `POST /agents/user/providers/{provider}/verify` (per-user), each performing a **real** Anthropic round-trip via `verify_resolved_credential → build_anthropic_request → anthropic_auth_headers` [VERIFIED-WITH-SOURCE: agents.py:1508-1523; llm_client.py:685-755,596-626]. A separate `/test-connection` (§14.4) would duplicate this. The modal already calls `/verify` [VERIFIED-WITH-SOURCE: api.ts:291; ProviderConfigModal.tsx:230].

Two changes make `/verify` correct per mode:
1. Once `anthropic_auth_headers` supports `oauth_token` (§5 runtime change), `verify_resolved_credential` sends the correct Bearer+beta header automatically for an oauth_token credential — no endpoint change needed [VERIFIED-WITH-SOURCE: llm_client.py:724-732 calls build_anthropic_request with `cred.auth_mode`].
2. **429 disambiguation:** `verify_resolved_credential:749-755` currently maps any non-2xx to `"failed"`. Add: on `429`, parse the body — if `error.message` contains a subscription-quota signal → return status `quota_exhausted` with an honest message ("subscription quota reached; retry later or switch to API-key mode"); otherwise `rate_limited` (per-minute, transient) [VERIFIED-WITH-SOURCE: llm_client.py:749-755; §14.4]. The exact quota-signal substring is confirmed by §8 PROBE-DEFA-2.

The verify result is stamped to `lastVerifyStatus`/`lastVerifiedAt` (already implemented) and surfaced in the modal [VERIFIED-WITH-SOURCE: agents.py:1522; ProviderConfigModal.tsx:307-318].

---

## 5. Agent-run credential routing + billing audit + quota (§14.5)

### 5.1 Header selection at run time
`anthropic_auth_headers(auth_mode, secret)` (llm_client.py:574-593) currently supports only `api_key`. **Add the `oauth_token` branch:**
```
oauth_token → { "authorization": f"Bearer {secret}",
                "anthropic-beta": "oauth-2025-04-20",
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json" }
```
Any authMode that is neither `api_key` nor `oauth_token` (e.g. legacy `subscription_oauth`) keeps raising the honest RuntimeError [VERIFIED-WITH-SOURCE: llm_client.py:582-592; PART-1 transport].

### 5.2 Resolution supports oauth_token (no fallthrough)
- `_resolution_is_supported` (llm_client.py:350-359) must return **True** for `anthropic + oauth_token` while keeping `subscription_oauth` blocked [VERIFIED-WITH-SOURCE: llm_client.py:359].
- `_infer_anthropic_auth_mode` (llm_client.py:340-347) must return `oauth_token` for `sk-ant-oat01-`, `subscription_oauth` for other `sk-ant-oat`, else `api_key` — used for env-sourced classification and the status badge (agents.py:1296) [VERIFIED-WITH-SOURCE: llm_client.py:340-347; agents.py:1296].
- **`.env` token resolution:** the anthropic env branch of `resolve_credential` (llm_client.py:402-419) reads `AETHER_LLM_API_KEY`/`ANTHROPIC_API_KEY` but **NOT** `CLAUDE_CODE_OAUTH_TOKEN`. Add a branch: if `CLAUDE_CODE_OAUTH_TOKEN` is set → resolve as `("anthropic", "oauth_token", <token>, None, "environment")`. Without this, the `.env` write (§3.3) is never consumed by the env path — the DB row is the only live source [VERIFIED-WITH-SOURCE: llm_client.py:402-419]. (Ordering: DB row still wins; env is the fallback / worker source per §14.1.)

### 5.3 Billing audit records authMode (GATE-05)
`_billing_audit` already writes `{"authMode": cred.auth_mode, ...}` to `AgentRun.billingAuditJson` via `set_billing_audit` [VERIFIED-WITH-SOURCE: agents.py:396-425,385-393; agent_run.py:58-71; DB column `AgentRun.billingAuditJson jsonb` live]. Once resolution returns `oauth_token`, the audit records it with **no further change** — J1 step 6 / GATE-05 satisfied by existing code.

### 5.4 Quota exhaustion — explicit 429, NEVER fall through (GATE-06)
Existing infra (all present, mostly dormant):
- `QuotaExhaustedError(provider, expires_at, reason)` [VERIFIED-WITH-SOURCE: llm_client.py:252-266].
- `_record_run` catches it → refunds the reserved run → `_quota_429(...)` (HTTP 429, honest message, no reroute) [VERIFIED-WITH-SOURCE: agents.py:569-581,428-452].
- Pre-existing cooldown block short-circuits a run with `QuotaExhaustedError` [VERIFIED-WITH-SOURCE: llm_client.py:975-982].
- `AgentQuotaBlockRepository.set_block/get_active` [VERIFIED-WITH-SOURCE: user_provider_credential.py:413-459].

**GAP the fixer MUST close:** the LIVE 429 → block wiring does not exist. `_call_live:1028` turns **any** `status_code >= 400` (including 429) into a generic `RuntimeError`, so a real subscription-quota 429 today surfaces as a 503, and **`set_block` has ZERO production callers** [VERIFIED-WITH-SOURCE: llm_client.py:1028; grep `set_block` → only the definition]. Add, in the anthropic branch of `_call_live` (after the httpx response):
- if `resp.status_code == 429`: parse body; **subscription-quota** (message contains the quota signal from PROBE-DEFA-2) → `AgentQuotaBlockRepository().set_block(user_id, provider, expires_at=now()+get_quota_block_hours(), reason="subscription_quota_exceeded")` then `raise QuotaExhaustedError(provider, ...)`; **per-minute rate-limit** → transient `RuntimeError` (allowed to hit the existing single retry, NOT a block).
- This must sit BEFORE the generic `raise RuntimeError` and must apply to **both** `oauth_token` and `api_key` anthropic calls. [VERIFIED-WITH-SOURCE: llm_client.py:1028-1029]

**No-fallthrough proof obligation:** the fixer MUST confirm the LLMClient fallback-model / fixture wrapper **re-raises** `QuotaExhaustedError` (never catches broad `Exception` → different credential or fixture). The class docstring asserts this [VERIFIED-WITH-SOURCE: llm_client.py:253-257] but it must be exercised by `test_quota_exhaustion_oat01_does_not_fall_through_to_api_key` with BOTH an oauth_token and an api_key credential present.

---

## 6. UI changes (§14.6)

**File:** `apps/web/src/components/agents/ProviderConfigModal.tsx` + `apps/web/src/components/agents/api.ts`.

The modal **already** renders: a radio group when `options.length > 1` (lines 321-350), a per-mode active hint/placeholder (line 380, `active.hint`), "Test connection" + "Remove" (Disconnect) buttons (lines 402-422), a masked `Ends …hint` (299-306), and a last-tested timestamp (307-318) [VERIFIED-WITH-SOURCE: ProviderConfigModal.tsx]. So §14.6 maps to small additive changes:

1. `authModeOptions("anthropic")` (lines 43-52) currently returns ONLY `api_key`. **Add** a second option:
   `{ value: "oauth_token", label: "Claude Code OAuth Token", hint: "Paste the token from `claude setup-token` (starts sk-ant-oat01-…). Bills against your Claude Pro/Max subscription.", placeholder: "sk-ant-oat01-…" }`.
   With two options, the existing radio + per-mode hint rendering activates automatically — the "two mutually-exclusive radio sections" of §14.6 [VERIFIED-WITH-SOURCE: ProviderConfigModal.tsx:42-61,321-350].
2. `api.ts`: widen `ProviderAuthMode = "api_key" | "subscription_oauth"` → add `"oauth_token"`, and the three `z.enum([...])` schemas (lines 52,60,123,166) to include `"oauth_token"` [VERIFIED-WITH-SOURCE: api.ts:52,60,123,166].
3. `billingNote("anthropic")` (lines 65-67) copy → mention both billing paths (API credits vs subscription quota) so the mode's billing implication is legible [VERIFIED-WITH-SOURCE: ProviderConfigModal.tsx:64-72].
4. The subtitle "no `.env` editing" (lines 276-278) stays TRUE (the USER never edits `.env`; the server writes it transparently). No change required; the operator override in §14.1 is a **backend-behavior** override (server MAY write `.env`), not a UI copy mandate. [INFERRED from §14.1 "operator overrides the current modal copy" vs. observed backend-only write]

Note: "Test connection"/"Disconnect" are per-credential (one stored anthropic credential at a time), not literally duplicated per mode. Switching the radio selects which mode the next Save stores; the stored row's authMode drives verify + run headers. This satisfies §14.6's intent (per-mode Test + Disconnect against the active mode) without a second concurrent credential. [Design; matches existing single-credential-per-provider storage, provider_credential.py UNIQUE(provider)]

---

## 7. Superseded / new tests (§14.7)

### 7.1 `apps/api/tests/test_gap_p5_auth_compliance.py` — invert/replace/keep

| Test (line) | Action | Reason |
|---|---|---|
| `test_anthropic_oauth_start_endpoint_removed` (42) | **KEEP** | In-app OAuth flow stays removed (ADR-P7-01 non-goal) |
| `test_anthropic_oauth_callback_endpoint_removed` (47) | **KEEP** | same |
| `test_put_deployment_credential_rejects_subscription_oauth` (61) | **REPLACE** | Now: `sk-ant-oat01-` → 200 `oauth_token`; keep `subscription_oauth` **label** rejected |
| `test_put_user_credential_rejects_subscription_oauth` (73) | **REPLACE** | same, per-user path |
| `test_agent_config_rejects_subscription_oauth_authmode` (85) | **UPDATE** | assert `oauth_token` accepted; `subscription_oauth` still 422 |
| `test_anthropic_headers_use_x_api_key_only` (99) | **SPLIT/KEEP** | api_key → x-api-key stays true; drop the "OAuth transport gone" assertion (now false) |
| `test_anthropic_headers_reject_subscription_oauth` (108) | **KEEP** | `subscription_oauth` label still unsupported by the header fn |
| `test_preexisting_subscription_oauth_credential_not_resolved` (118) | **KEEP** | legacy `sk-ant-oat-LEGACY…` (non-oat01) stays blocked |
| module docstring (1-17) + comment `llm_client.py:11-12,577-580,343-345` | **REWRITE** | "x-api-key ONLY / OAuth transport gone" is now false for `oauth_token` |

### 7.2 New file `apps/api/tests/test_gap_p7_def_a_dual_mode.py` (§14.7)

| Test | Exercises (target) |
|---|---|
| `test_oat01_token_accepted_returns_200` | PUT `/agents/providers/anthropic/credential` with `sk-ant-oat01-…` → 200, stored authMode `oauth_token` |
| `test_api03_key_still_accepted_returns_200` | `sk-ant-api03-…` → 200, `api_key` (regression) |
| `test_garbage_credential_returns_422_naming_both_formats` | `sk-GARBAGE-` → 422; body names `sk-ant-api` AND `sk-ant-oat01-` |
| `test_oat01_writes_env_var_atomically` | after oat01 save, `AETHER_ENV_FILE_PATH` contains `CLAUDE_CODE_OAUTH_TOKEN=` (tmp env path) |
| `test_oat01_env_var_has_600_permissions` | `stat` of the written env file == 0o600 |
| `test_api03_does_not_write_env_var` | api_key save leaves `.env` untouched |
| `test_token_never_logged_in_response_body` | response body / masked row carry only `…last4`, never full token |
| `test_test_connection_oat01_success` | `verify_resolved_credential` for oauth_token builds Bearer+beta header (assert on prepared request; no live call) |
| `test_test_connection_api03_success` | api_key builds x-api-key header |
| `test_quota_exhaustion_oat01_does_not_fall_through_to_api_key` | with both creds present, a 429 subscription-quota → `QuotaExhaustedError`/429, NEVER an api_key retry |
| `test_billing_audit_records_auth_mode_oauth` | `_billing_audit` → `authMode == "oauth_token"` |
| `test_billing_audit_records_auth_mode_api_key` | `_billing_audit` → `authMode == "api_key"` |
| `test_no_cross_credential_substitution` | resolver never returns a different-provider or different-authMode secret than requested |

Additional (beyond §14.7 list, recommended): `test_anthropic_oauth_headers_use_bearer_and_beta` (positive header assertion), `test_subscription_oauth_label_still_rejected`, `test_agent_config_accepts_oauth_token_authmode`, `test_migration_widens_authmode_check` (per-user oauth_token insert succeeds).

Frontend: extend the existing modal test to assert two anthropic radio options and the oat01 placeholder/hint render.

---

## 8. Pre-implementation probes the fixer MUST run first (zero open ASSUMED items)

1. **PROBE-DEFA-1 (constraint name at deploy time):** re-run the `pg_constraint` query against the LIVE prod schema immediately before the migration to confirm the constraint is still named `UserProviderCredential_authMode_check` (it was, 2026-07-17). If a prior deploy renamed it, adjust the `DROP CONSTRAINT` name. [VERIFIED-WITH-SOURCE: live query 2026-07-17 — re-confirm at deploy]
2. **PROBE-DEFA-2 (429 body signal):** the exact substring distinguishing a subscription-quota 429 from a per-minute rate-limit 429 was NOT observed (the operator token was not quota-exhausted during PART-1). The fixer must confirm the discriminator (candidate: `error.type == "rate_limit_error"` always; subscription vs per-minute distinguished by message text or a `retry-after` magnitude) via Anthropic docs or a controlled 429, and use that in §4/§5.4. Until confirmed, the safe default is: treat a 429 whose message mentions "quota"/"usage limit"/"plan" as subscription-quota (set block); otherwise transient. [ASSUMED-PENDING-PROBE: PROBE-DEFA-2 — fixer runs before wiring §5.4; not blocking the blueprint]

---

## 9. Rollout, backward-compat, failure modes, NON-goals

**How `.env` reaches the process:** `systemd aether-api.service` (User=ubuntu, WorkingDirectory=repo root) runs `start-api.sh`, which **exports the repo-root `.env` at process startup** (while-read loop) and then `exec`s uvicorn; there is **no `EnvironmentFile=`** directive [VERIFIED-WITH-SOURCE: `/etc/systemd/system/aether-api.service`; start-api.sh:1-25]. `config.py` also declares `env_file=".env"` but reads from `os.environ` populated by start-api.sh [VERIFIED-WITH-SOURCE: config.py:23-28].

**Implication:** a newly written `CLAUDE_CODE_OAUTH_TOKEN` is **NOT** live in the running process until `sudo systemctl restart aether-api`. **The DB row makes oauth_token immediately usable without restart** (resolution reads the DB first); the `.env` write is for (a) the async worker (ASYNC-001) and (b) surviving restarts. Document the restart as an operator step; do NOT auto-restart from the request path. [VERIFIED-WITH-SOURCE: resolve_credential DB-first, llm_client.py:379-401; start-api.sh startup load]

**Backward compatibility:** api_key mode is byte-for-byte unchanged (x-api-key). No existing row changes value; the CHECK widening is a strict superset. `subscription_oauth` stays blocked. Current prod has no `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` in `.env`; anthropic traffic is served via stored/OpenRouter creds [VERIFIED-WITH-SOURCE: live `.env` key scan].

**Failure modes:** missing `AETHER_CREDENTIAL_KEY` → honest 503 (unchanged) [VERIFIED-WITH-SOURCE: agents.py:1477-1482]. `.env` write failure → the save must still succeed on the DB row but surface a warning; decide policy with fable-5 (recommend: DB write is the source of truth; `.env` write failure logs a non-secret warning and returns success with a `envSync:false` flag). Token revoked/expired → verify returns `failed`; run returns honest error, never fixture. Quota exhausted → explicit 429, never api_key reroute (§5.4).

**Security invariants:** token never logged/echoed/returned (only `…last4`); `.env` written 600 via temp+fchmod+rename in the same dir; `.env` gitignored; no fixture content on any path; no destructive DDL. [VERIFIED-WITH-SOURCE: credential_vault, §3.3, .gitignore]

**NON-goals (ADR-P7-01):** NO in-app OAuth authorize/PKCE flow — the `AnthropicOAuthState`/`AnthropicOAuthToken` tables and any `/agents/auth/anthropic/*` endpoints stay removed/unused [VERIFIED-WITH-SOURCE: user_provider_credential.py:86-108; test_gap_p5_auth_compliance.py:42-53]. No auto-restart of the API from a request. No token refresh handling in-app (the pasted token is used as-is; refresh is the operator's `claude setup-token` responsibility). Async/worker consumption of `CLAUDE_CODE_OAUTH_TOKEN` is designed under GAP-P7-ASYNC-001, not here.

---

## 10. Change inventory (for the fixer, minimal-diff)

| # | File | Change |
|---|---|---|
| 1 | `apps/api/app/routers/agents.py` | `_detect_anthropic_auth_mode` + rewire `_validate_provider_auth` (§2); widen `AgentConfigUpdate.authMode` pattern; call `_atomic_env_write` for oauth_token in the put paths |
| 2 | `apps/api/app/services/llm_client.py` | `anthropic_auth_headers` oauth_token branch (§5.1); `_resolution_is_supported`+`_infer_anthropic_auth_mode` allow/return oauth_token (§5.2); `CLAUDE_CODE_OAUTH_TOKEN` env branch; live-429→set_block+QuotaExhaustedError in `_call_live` (§5.4); verify 429 disambiguation (§4); rewrite stale docstrings/comments |
| 3 | `apps/api/app/repositories/user_provider_credential.py` | widen inline CHECK + additive `ALTER … CHECK` in `_ensure_user_agent_tables` (§3.2) |
| 4 | `apps/api/app/config.py` (or a small helper) | `AETHER_ENV_FILE_PATH` setting + `_atomic_env_write` helper (§3.3) |
| 5 | `apps/web/src/components/agents/ProviderConfigModal.tsx` | second anthropic auth option + billing copy (§6) |
| 6 | `apps/web/src/components/agents/api.ts` | `oauth_token` in type + zod enums (§6) |
| 7 | `apps/api/tests/test_gap_p5_auth_compliance.py` | invert/replace/keep per §7.1 |
| 8 | `apps/api/tests/test_gap_p7_def_a_dual_mode.py` | NEW, §7.2 |
| 9 | `apps/api/migrations/0020_per_user_agent_creds.sql` | documentary mirror of §3.2 (record only) |
| 10 | `.env.example` | add commented `CLAUDE_CODE_OAUTH_TOKEN=` |

**No production fix code is written by arch. fable-5 approval is required before implementation begins.**
