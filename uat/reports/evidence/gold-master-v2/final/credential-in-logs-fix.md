# BLOCKER-001 §0.5 — plaintext admin credential written to the API log on every boot

Status: FIXED. Evidence log:
`uat/reports/evidence/gold-master-v2/final/credential-in-logs-verify-20260731T165200Z.log`
(captured 2026-07-31T16:51:29Z, this session).

## 1. The captured defect [VERIFIED-WITH-FRESH-EVIDENCE — reproduced pre-fix in this session, see §4 "before"]

`apps/api/app/repositories/admin.py::_audit_admin_credential` (pre-fix) built its CRITICAL
diagnostic with:

```python
f"{email!r} — its AETHER_ADMIN_PASSWORD_HASH verifies the known-weak "
f"password {weak!r}. ..."
```

`weak` is the exact denylist entry that matched — on a degraded deploy that value **is** the
live plaintext password. `_record_admin_credential_state` (unchanged, still the caller on every
`apply_admin_rotation()`, i.e. every API boot) writes that string via both
`logger.critical(...)` and `print(..., file=sys.stderr)`. `start-api.sh` execs uvicorn with
`--log-config logging_config.json`; stderr is what systemd/the deploy pipeline redirects into
`/var/log/aether/api.log` per `docs/delivery/DEPLOYMENT-RUNBOOK.md`. Net effect: a complete,
working credential pair (operator email + plaintext password) was written to disk on **every**
restart, for as long as the credential stayed unrotated. Today's live value (`admin123`) is
already public, but the guard is unconditional — the moment the operator rotates to a real,
strong, unique password that value is what gets logged, forever, on every subsequent boot.

## 2. Failing test first (fail-before / pass-after)

New file: `apps/api/tests/test_blocker001_credential_in_logs.py` (2 tests):
* `test_weak_credential_diagnostic_names_no_denylist_entry` — every
  `_KNOWN_WEAK_ADMIN_PASSWORDS` entry, hashed and audited, must produce a diagnostic that quotes
  no denylist entry (`'entry'` / `"entry"`), while still naming `AETHER_ADMIN_PASSWORD_HASH` and
  `BLOCKER-001`.
* `test_degraded_boot_banner_never_writes_plaintext_password_to_the_log` — drives the exact
  `_record_admin_credential_state` call `apply_admin_rotation` makes on every boot, captures both
  the `logger.critical` record and the `stderr` print, and asserts neither channel quotes a
  denylist entry.

Detection uses the SAME quoted-value convention already pinned by
`tests/test_blocker001_restart_safety.py::test_degraded_state_is_surfaced_on_admin_health_without_leaking_secrets`
(`f"'{weak}'" not in text` / `f'"{weak}"' not in text`), not a bare substring check — several
denylist entries (`"admin"`, `"password"`, `"secret"`, `"aether"`) are also ordinary words that
legitimately appear inside safe vocabulary the diagnostic must keep using
(`AETHER_ADMIN_PASSWORD_HASH`, "a strong, unique password", "restart aether-api"); a bare
substring check would false-positive on those and miss the actual credential-shaped, quoted
leak this defect produces.

**RED (before fix)** — captured this session,
`flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_blocker001_credential_in_logs.py -v"`:

```
tests/test_blocker001_credential_in_logs.py::test_weak_credential_diagnostic_names_no_denylist_entry FAILED
tests/test_blocker001_credential_in_logs.py::test_degraded_boot_banner_never_writes_plaintext_password_to_the_log FAILED
...
E           AssertionError: BLOCKER-001/§0.5 VIOLATION: diagnostic quotes a known-weak password value ('admin123') — this is the exact shape a live plaintext credential would take once rotated. Text: "CRITICAL: DEGRADED ADMIN CREDENTIAL — ... BLOCKER-001: refusing to grant admin privilege to 'owner-f910975c@aether.io' — its AETHER_ADMIN_PASSWORD_HASH verifies the known-weak password 'admin123'. ..."
========================= 2 failed, 1 warning in 1.07s =========================
```

**GREEN (after fix)** — see the evidence log referenced above, `2 passed` for this file, `33
passed` overall.

## 3. The fix

`apps/api/app/repositories/admin.py::_audit_admin_credential` — removed `f"{weak!r}"` from the
returned string entirely. The message now names only:
* the env var to rotate (`AETHER_ADMIN_PASSWORD_HASH`),
* the nature of the problem ("hashes a well-known default/weak password... matches an entry on
  this deployment's known-weak-password denylist"),
* where to read the denylist in source if the operator wants specifics
  (`_KNOWN_WEAK_ADMIN_PASSWORDS` — reading source is safe, per the pre-existing rationale in this
  same module, because denylist entries are public by construction; the LIVE match is what must
  never be echoed),
* the exact remediation ("Rotate AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique
  password (not a common default) and restart").

No diagnostic usefulness is lost: the remediation is identical regardless of *which* denylist
entry matched ("pick a new strong, unique password"), so the operator loses no actionable
information — only the live secret value. Also updated the now-stale comment above
`_ADMIN_CREDENTIAL_DEGRADED` (module-level state var) that previously documented the old,
leaking behaviour as intentional; it now documents the corrected behaviour.

`git diff` (full, both hunks):

```diff
--- a/apps/api/app/repositories/admin.py
+++ b/apps/api/app/repositories/admin.py
@@ -95,10 +95,12 @@ _WEAK_HASH_AUDIT_CACHE_MAX = 64
 #: never latch on stale state. It is read by:
 #:   * :func:`weak_operator_credential_refused` — fail-CLOSED at auth, and
 #:   * :func:`health_overview` — so an operator sees the condition in the UI.
-#: NOTE: this message names the matched denylist entry, which on a degraded
-#: deploy IS the live password. It is written to the process log ONLY (an
-#: operator-only channel) and must never be returned over HTTP — see
-#: ``_DEGRADED_ADMIN_REMEDIATION`` for the safe, value-free public string.
+#: NOTE (§0.5): this message is written to the process log on every boot
+#: while the credential stays unrotated, so it deliberately never names the
+#: matched denylist entry — on a degraded deploy that value IS the live
+#: password (see ``_audit_admin_credential``). It still must never be
+#: returned over HTTP regardless — see ``_DEGRADED_ADMIN_REMEDIATION`` for
+#: the safe, value-free public string.
 _ADMIN_CREDENTIAL_DEGRADED: Optional[str] = None

@@ -191,14 +193,34 @@ def _audit_admin_credential(email: str, pw_hash: str) -> Optional[str]:
     weak = _weak_password_matching(pw_hash)
     if weak is None:
         return None
+    # §0.5 VALUE DISCIPLINE: this string is written to the process log on
+    # EVERY boot while the credential stays unrotated (_record_admin_credential_state
+    # -> logger.critical + stderr -> journalctl / /var/log/aether/api.log).
+    # It must therefore never interpolate the matched denylist entry: today
+    # that value happens to already be public (the confirmed live production
+    # password), but the guard runs unconditionally, so the SAME code path
+    # would print a real operator's freshly-rotated strong password in
+    # plaintext, forever, on every restart, the moment they reused (or
+    # mistyped into) a value this denylist happens to also contain. Naming
+    # the failure mode and the variable to rotate is fully actionable without
+    # the value: the remediation ("pick a new strong, unique password") is
+    # identical no matter which denylist entry matched. See
+    # ``_KNOWN_WEAK_ADMIN_PASSWORDS`` in this module for the full list, which
+    # is safe to read in source (public by construction) but must never be
+    # echoed back with the LIVE match highlighted.
     return (
         "BLOCKER-001: refusing to grant admin privilege to "
-        f"{email!r} — its AETHER_ADMIN_PASSWORD_HASH verifies the known-weak "
-        f"password {weak!r}. An admin account can read every user's email "
+        f"{email!r} — its AETHER_ADMIN_PASSWORD_HASH hashes a well-known "
+        "default/weak password (it matches an entry on this deployment's "
+        "known-weak-password denylist; the matched value is deliberately not "
+        "printed here — see _KNOWN_WEAK_ADMIN_PASSWORDS in "
+        "app/repositories/admin.py for the list — because this diagnostic is "
+        "written to the log on every boot and must never echo a live "
+        "credential value). An admin account can read every user's email "
         "address, change spend caps and issue real refunds; a guessable "
         "password on it is a full compromise of the platform. Rotate "
         "AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique "
-        "password and restart."
+        "password (not a common default) and restart."
     )
```

No DB/schema change was required — this is a pure string-content fix, so §7's "additive-only
lazy DDL" rule is not implicated.

## 4. Email decision — KEEP, redacted-nothing

**Decision: keep the operator email, unredacted, quoted exactly as before (`{email!r}`).**

Justification:
* The email is not a secret by itself — it is the operator's own account identifier, already
  visible to that operator (and to anyone with server access, which this log already requires).
* It is load-bearing for the diagnostic's purpose: `AETHER_ADMIN_EMAIL` is an operator-supplied
  env var, and if it were ever misconfigured (typo, wrong environment, stale value from another
  deployment) the email is exactly what lets the operator confirm *which* row/identity is being
  refused, without which the diagnostic degrades to "some admin credential somewhere is bad."
* Crucially, after this fix the email is no longer paired with anything password-shaped in the
  same message — the diagnostic no longer contains the matched denylist entry at all, so "email +
  password forms a usable pair" (the finding's stated concern) is now moot: there is no password
  value left in the message to pair it with. Redacting the email in addition would trade away
  real actionability (per the task's instruction: "Losing diagnostic usefulness is not an
  acceptable trade") for a benefit that no longer exists once the value-echo is removed.
* `_self_cancel_problem` (the sibling diagnostic for the self-cancelling
  `AETHER_ADMIN_EMAIL == seed identity` case) already quotes the email with no password
  alongside it, and was never flagged as a leak — the same reasoning applies here post-fix.

## 5. Grep sweep — every other log/exception path that could emit a password, hash, token, or DSN value

Commands run (this session, `apps/api/app/` only, per the finding's scope):

```
grep -rnE "(logger\.(debug|info|warning|error|critical|exception)|print\()" . --include="*.py" \
  | grep -iE "password|secret|token|dsn|api_key|apikey|credential|passwd|hash"

grep -rnE "raise .*(password|secret|token|dsn|api_key|apikey|passwd)" --include="*.py" . -i | grep -iE "\{"

grep -rnE "(logger\.[a-z]+\(|print\().*\{(access|refresh|secret|token|password|pw_hash|passwordHash|ciphertext|api_key|apiKey|client_secret)\b" --include="*.py" .

grep -rnE "os\.environ\b" --include="*.py" . | grep -iE "print\(|logger\.|dict\(os\.environ|json\.dumps\(os\.environ"

grep -rnE "DATABASE_URL|_dsn\b|conn_str|connection_string" --include="*.py" . | grep -iE "log|print"
```

| # | File:line | What it logs | Disposition |
|---|---|---|---|
| 1 | `repositories/admin.py` (the `_audit_admin_credential` call site + `_record_admin_credential_state`) | THE finding | **FIXED** — see §3 |
| 2 | `services/llm_client.py:854` `logger.debug("agent credentialRef lookup failed: %s", exc)` | `exc` from a DB `SELECT "credentialRef" FROM "AgentConfig"` query failure (missing column/table/DB hiccup) | SAFE — no change. `credentialRef` is an opaque row-id reference, not a secret; the query never selects a decrypted secret, and a psycopg2 query-shape error does not embed bound parameter values. |
| 3 | `services/llm_client.py:952` `logger.warning("credentialRef resolve failed: %s", exc)` | `exc` from `UserProviderCredentialRepository.get_secret_by_id`, which calls `credential_vault.decrypt` | SAFE — no change. `services/credential_vault.py`'s documented "Honesty contract" (module docstring) guarantees `decrypt`/`encrypt` failures raise `CredentialVaultError` describing the KEY problem (missing/invalid `AETHER_CREDENTIAL_KEY`), never the plaintext — decryption fails *before* any plaintext is produced. Verified by reading `credential_vault.py:44-80`. |
| 4 | `services/llm_client.py:968` `logger.warning("user credential resolve failed: %s", exc)` | `exc` from `UserProviderCredentialRepository.get_secret` | SAFE — same `credential_vault.decrypt` guarantee as #3. |
| 5 | `services/anthropic_oauth.py:294` `logger.debug("oauth_token .env sync skipped: %s", exc)` | `exc` from `env_file_writer.sync_oauth_token_env(access)` | SAFE — no change. `services/env_file_writer.py`'s module docstring states the token "is NEVER logged, echoed, or returned"; `write_oauth_token_env` raises only generic filesystem I/O exceptions (`OSError`/`PermissionError`-shaped) on `mkstemp`/`fchmod`/`os.replace` failure — none of those exception messages embed the token content, only paths/errno. |
| 6 | `services/discovery/ashby_adapter.py:46`, `services/discovery/greenhouse_adapter.py:52` `logger.warning("...: board %s failed: %s", token, exc)` | the per-request `token` | SAFE — no change. Confirmed via each adapter's own module docstring ("no API key") and `services/discovery/portals.py`: this "token" is a **public, config-driven job-board company slug** used to build a public URL path (`.../job-board/<token>`), not a credential. |
| 7 | `services/google_oauth.py:268` `raise OAuthError(f"Token exchange failed: {exc}") from exc` | `exc` from `google_auth_oauthlib`'s `flow.fetch_token(code=code)` | LOW RESIDUAL RISK, no change made — third-party library boundary (`google-auth-oauthlib`/`oauthlib`/`requests`). Failure messages from OAuth token-exchange errors are constructed by that library from **Google's own error response body** (`error`/`error_description` fields, e.g. `invalid_grant`), not by echoing the outgoing request body — so the app's `client_secret`/`code_verifier` are not expected to appear. Not independently re-auditable inside this diff's scope (would require auditing `google-auth-oauthlib` internals, out of scope for a minimal fix); flagged here per the task's "report every hit with a disposition" instruction rather than left unmentioned. Recommend a follow-up finding if this needs a stronger guarantee than "trust the library." |
| 8 | `apps/api/app/repositories/admin.py:190` (unchanged) — the operator-facing `print(CryptContext(...).hash('<your password>'))` code sample inside the malformed-hash diagnostic | N/A | SAFE — no change. `<your password>` is a literal placeholder string shown to the operator as an example command to run themselves; no runtime value is interpolated there. |
| 9 | `db.py:660` `logger.warning("... %d (userId, jobId) pair(s) already violate ...", violation_groups)` | an integer count | SAFE — unrelated to credentials, included for completeness of the sweep. |
| 10 | `start-api.sh`, `scripts/seed_demo.py` | env-var loading / one-off admin-seed print | SAFE — `start-api.sh` has no `set -x` and echoes nothing; `seed_demo.py:129` prints only `f"seeded admin user {ADMIN_EMAIL} (username={ADMIN_USERNAME})"`, no password. Not inside `apps/api/app/` (out of the finding's literal grep scope) but checked because they are boot-adjacent. |
| — | `os.environ` wholesale dump / `DATABASE_URL`/DSN logging | — | NONE FOUND across `apps/api/app/`. |
| — | request-body/payload logging middleware | — | NONE FOUND — `apps/api/app/middleware/` contains only `auth.py`; no request-body logger exists. |

## 6. Verbatim before/after

See §2 for the RED excerpt and the evidence log
`uat/reports/evidence/gold-master-v2/final/credential-in-logs-verify-20260731T165200Z.log`
(this session, 2026-07-31T16:51:29Z) for the full GREEN run: `ruff check app/ tests/` →
`All checks passed!`, then the combined pytest run →

```
tests/test_blocker001_credential_in_logs.py::test_weak_credential_diagnostic_names_no_denylist_entry PASSED
tests/test_blocker001_credential_in_logs.py::test_degraded_boot_banner_never_writes_plaintext_password_to_the_log PASSED
tests/test_blocker001_admin_overpermission.py (12 items) — all PASSED
tests/test_blocker001_restart_safety.py (5 items) — all PASSED
tests/test_gm2_s15_signup_nul_byte_500.py (14 items) — all PASSED
======================= 33 passed, 6 warnings in 58.20s =========================
```

Note: the task text says `test_blocker001_admin_overpermission.py (11)`; the file actually
collects **12** items (4 parametrized `weak_password` cases + 2 parametrized `malformed_hash`
cases + 6 non-parametrized tests = 12). Reported as observed, not adjusted to match the stated
count — all 12 pass.

## 7. Residual risks

* **google_oauth.py:268** (item #7 above) — third-party-library-boundary exception message, not
  independently verified line-by-line inside `google-auth-oauthlib`/`oauthlib`. Practically safe
  (provider error responses don't echo submitted secrets) but not proven to the same standard as
  the rest of this sweep. Recommend a follow-up finding if a stricter guarantee is required
  (e.g., wrap with a value-scrubbing formatter, or assert-test against the real library's error
  shapes).
* **Historical log retention**: this fix stops *future* boots from writing the plaintext value.
  It does not retroactively scrub `admin123` (already public) from any existing
  `/var/log/aether/api.log` content written by prior boots — out of scope for a source-code fix;
  log rotation/retention policy is an operator/ops concern, not addressed here.
* **`_KNOWN_WEAK_ADMIN_PASSWORDS` visibility in source**: the fix points operators at this
  constant in `app/repositories/admin.py` instead of quoting the live match. That list is
  intentionally public (documented at its definition: "these literals are rejection patterns, not
  credentials"), so this is not a new disclosure — it only removes the *live match* signal, which
  is the actual secret-bearing bit.
* Scope of this fix is `_audit_admin_credential`'s weak-password branch only, per the finding.
  The malformed-hash branch (line ~181-190) and `_self_cancel_problem` (email-only, no password)
  were reviewed and already contained no password/hash value — left unchanged, consistent with
  "change only what the finding requires."
