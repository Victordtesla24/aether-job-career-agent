# WB Wave 1 — Failing Tests (GOLD-MASTER-V2 §15 step 2)

**Role:** test-author (writes tests only; never implements fixes — §0.4 separation of duties)
**Repo commit at time of writing:** `7f82105b56d77b10a3215680428a5654076f2ffe`
**Run environment:** `apps/api` test suite, `DATABASE_URL_TEST` pinned to `schema=aether_test` via `scripts/run-tests.sh` (never sourced repo-root `.env`)
**Command wrapper used for every run:** `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh <file> -v"`
**Evidence timestamp:** 2026-07-31T00:27:20Z [VERIFIED-WITH-FRESH-EVIDENCE]

Four confirmed W-B wave 1 defects. One new test file per defect, all under
`apps/api/tests/`. Every test below was run against **current** (unfixed)
code; verbatim failure output is captured per test. All four defects
reproduce for the right reason — no import/fixture/collection errors.

---

## 1. ML-settings-006 — NUL byte → 500 instead of 422

**File:** `apps/api/tests/test_wb1_ml_settings_006_nul_byte.py`
**Command:** `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wb1_ml_settings_006_nul_byte.py -v"`

| Node id | Result | Reason |
|---|---|---|
| `test_nul_byte_in_full_name_returns_422_not_500` | **FAILED** [VERIFIED] | got 500, expected 422 |
| `test_nul_byte_in_target_role_returns_422_not_500` | **FAILED** [VERIFIED] | got 500, expected 422 |
| `test_nul_byte_in_location_returns_422_not_500` | **FAILED** [VERIFIED] | got 500, expected 422 |
| `test_nul_byte_in_email_returns_422_regression_guard` | PASSED (expected — see below) | email validator already rejects the NUL byte pre-DB |

### Verbatim failing output (fullName — representative; targetRole/location are byte-identical in shape)

```
resp = <Response [500 Internal Server Error]>, field = 'fullName'

    def _assert_honest_422(resp, field: str) -> None:
>       assert resp.status_code == 422, (
            f"NUL byte in profile.{field} must be rejected with 422 (honest, "
            f"specific validation error) — never 500. Got {resp.status_code}. "
            f"Body: {resp.text[:2000]!r}"
        )
E       AssertionError: NUL byte in profile.fullName must be rejected with 422 (honest, specific validation error) — never 500. Got 500. Body: 'Internal Server Error'
E       assert 500 == 422
E        +  where 500 = <Response [500 Internal Server Error]>.status_code

tests/test_wb1_ml_settings_006_nul_byte.py:74: AssertionError
```

Summary line: `3 failed, 1 passed, 6 warnings in 6.37s` (isolated run); reproduced identically (`... in 50.23s` overall) in the combined WB1 run below.

**Reproduction technique note:** the endpoint's real behaviour is a raw, unhandled `ValueError` (`psycopg2`: "A string literal cannot contain NUL (0x00) characters.") propagating out of `update_settings`. The default `TestClient` (`raise_server_exceptions=True`) would re-raise that `ValueError` straight into the test process instead of surfacing what a production uvicorn deployment actually sends. Per the same technique already established in `tests/test_ml_signup_001.py`, we bind a second `TestClient(client.app, raise_server_exceptions=False)` to the same app/DB so `resp.status_code`/`resp.text` reflect the real HTTP 500 response — matching the live production evidence in `uat/reports/evidence/gold-master-v2/runtime/RUNTIME-MONITOR-REPORT-2-500-correlation.md` exactly (500, body `Internal Server Error`, no traceback leak — Starlette's `ServerErrorMiddleware` default).

**Unexpected-pass flag:** `test_nul_byte_in_email_returns_422_regression_guard` PASSES today. This is EXPECTED, not a defect in the test: `SettingsProfile.email` runs through `_validate_settings_email` (a pydantic `AfterValidator` backed by `email_validator`) *before* the DB layer, and `email_validator` already rejects a NUL byte in the local-part as an invalid character (empirically confirmed against the installed `email-validator==2.3.0` in this environment: `validate_email('john\x00doe@aether.local', ...)` → `EmailNotValidError: The email address contains invalid characters before the @-sign: U+0000.`). The finding's root-cause evidence names `fullName`/`targetRole`/`location`/`email` as "one of" the affected fields (root cause is the DB-layer `cur.execute` call, which `email` never reaches when malformed this way) — the `email` parametrize id is kept in the same file as a **regression guard** documenting that boundary, not a second reproduction of the 500.

---

## 2. BLOCKER-002 — cover letter signed with a test-probe placeholder name

**File:** `apps/api/tests/test_wb1_blocker002_placeholder_signer_name.py`
**Command:** `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wb1_blocker002_placeholder_signer_name.py -v"`

| Node id | Result |
|---|---|
| `test_cover_letter_refuses_placeholder_signer_name[GAP-P7-DEF-B Probe 1785452243543]` | **FAILED** [VERIFIED] |
| `test_cover_letter_refuses_placeholder_signer_name[QA Test Runner 445566778899]` | **FAILED** [VERIFIED] |
| `test_cover_letter_refuses_placeholder_signer_name[probe_user_20260731093000]` | **FAILED** [VERIFIED] |
| `test_cover_letter_accepts_normal_human_name` | PASSED (expected — false-positive guard) |

### Verbatim failing output (exact production-contaminated value)

```
    @pytest.mark.parametrize("placeholder_name", PLACEHOLDER_NAMES)
    def test_cover_letter_refuses_placeholder_signer_name(client, auth_headers, placeholder_name):
        _set_profile_name(client, auth_headers, placeholder_name)
        job = _seed_job(client, auth_headers)
    
        resp = client.post(
            "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
        )
    
>       assert resp.status_code == 422, (
            "cover-letter generation must FAIL HONESTLY (422) when the profile "
            f"name looks like a placeholder/test artefact ({placeholder_name!r}) "
            "instead of emitting it onto a customer-facing document. Got "
            f"{resp.status_code}: {resp.text[:2000]!r}"
        )
E       AssertionError: cover-letter generation must FAIL HONESTLY (422) when the profile name looks like a placeholder/test artefact ('GAP-P7-DEF-B Probe 1785452243543') instead of emitting it onto a customer-facing document. Got 200: '{"cover_letter_id":"c7fb72a71ef76fdfff32475fa","cover_letter":"31 July 2026\n\nHiring Team\nCulture Amp\nRe: DevOps Engineer\n\n...Sincerely,\nGAP-P7-DEF-B Probe 1785452243543\n","approval_id":"c2794d5f2b117a81bfdae9fcf","approval_status":"pending"}'
E       assert 200 == 422
E        +  where 200 = <Response [200 OK]>.status_code
```

(The other two parametrize ids — `QA Test Runner 445566778899`, `probe_user_20260731093000` — fail identically: 200 instead of 422, with the placeholder string visible verbatim in the `Sincerely,\n{name}` sign-off of `resp.json()["cover_letter"]`.) Summary line: `3 failed, 1 passed, 6 warnings in 25.80s`.

**Detection rule used (test-author's design choice, as explicitly invited by the finding text):** a signer name is placeholder-looking if it contains the case-insensitive substrings "probe" or "test", OR the literal marker "GAP-", OR a run of 8+ consecutive digits. `test_cover_letter_accepts_normal_human_name` asserts the false-positive guard the finding explicitly requires: "Jordan Rivera" is accepted (200) and renders correctly (`"Sincerely,\nJordan Rivera"` present in the letter) — this id PASSES today and must keep passing after any fix.

---

## 3. INC-B-002 / FE-D-002 — emailVerificationEnabled inert + unvalidated

**File:** `apps/api/tests/test_wb1_incb002_email_verification_toggle.py`
**Command:** `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wb1_incb002_email_verification_toggle.py -v"`

| Node id | Result |
|---|---|
| `test_email_verification_enabled_blocks_login_for_unverified_user` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[1]` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[0]` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[yes]` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[no]` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[on]` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[off]` | **FAILED** [VERIFIED] |
| `test_admin_settings_rejects_non_boolean_email_verification_value[TRUE]` | **FAILED** [VERIFIED] |
| `test_admin_settings_already_rejects_structurally_invalid_values[banana]` | PASSED (expected — control) |
| `test_admin_settings_already_rejects_structurally_invalid_values[123]` | PASSED (expected — control) |
| `test_admin_settings_already_rejects_structurally_invalid_values[bad_value2]` (`[1,2]`) | PASSED (expected — control) |
| `test_admin_settings_already_rejects_structurally_invalid_values[bad_value3]` (`{"a":1}`) | PASSED (expected — control) |

### Verbatim failing output — (a) enforcement parity with signupEnabled

```
    login = client.post("/auth/login", json={"email": email, "password": password})
>       assert login.status_code in (401, 403), (
            "emailVerificationEnabled=true must block login for an account that "
            "has never verified its email -- the SAME enforcement contract "
            "signupEnabled already gets at registration (auth.py: "
            "'Public registration is currently disabled', 403). Got "
            f"{login.status_code}: {login.text}"
        )
E       AssertionError: emailVerificationEnabled=true must block login for an account that has never verified its email -- the SAME enforcement contract signupEnabled already gets at registration (auth.py: 'Public registration is currently disabled', 403). Got 200: {"access_token":"eyJ...","token_type":"bearer","userId":"c38bf46147771f2c9f7bc38b6","email":"unverified-a2069afa@example.com"}
E       assert 200 in (401, 403)
E        +  where 200 = <Response [200 OK]>.status_code
```

### Verbatim failing output — (b) reject non-boolean values (representative: `garbage=1`)

```
    @pytest.mark.parametrize("garbage", GARBAGE_BUT_CURRENTLY_ACCEPTED)
    def test_admin_settings_rejects_non_boolean_email_verification_value(client, garbage):
        headers, _ = _admin(client)
        resp = client.post(
            "/admin/settings", json={"emailVerificationEnabled": garbage}, headers=headers
        )
>       assert resp.status_code == 422, (
            "POST /admin/settings must reject a non-boolean (garbage) value for "
            "emailVerificationEnabled with 422 rather than silently coercing and "
            f"persisting it, got {resp.status_code} for {garbage!r}: {resp.text[:500]!r}"
        )
E       AssertionError: POST /admin/settings must reject a non-boolean (garbage) value for emailVerificationEnabled with 422 rather than silently coercing and persisting it, got 200 for 1: '{"signupEnabled":true,"emailVerificationEnabled":true}'
E       assert 200 == 422
E        +  where 200 = <Response [200 OK]>.status_code
```

All of `0`, `"yes"`, `"no"`, `"on"`, `"off"`, `"TRUE"` fail identically (200 + the value silently coerced and persisted — visible in each response body above). Summary line: `8 failed, 4 passed, 10 warnings in 19.56s`.

**Unexpected-pass flag / control group explanation:** `test_admin_settings_already_rejects_structurally_invalid_values` (parametrized over `"banana"`, `123`, `[1,2]`, `{"a":1}`) PASSES today. This is EXPECTED and BY DESIGN, not a defect in the test: empirically probed directly against `app.routers.admin.SettingsRequest` in this environment, pydantic's own `bool_parsing`/`bool_type` errors already reject those specific shapes with 422 (a JSON array/object can never coerce to bool at all; `"banana"`/`123` fail pydantic's lax bool-string/int parsing). The genuine, currently-unguarded gap is narrower than "any non-boolean value": it is specifically the set of JSON values pydantic's LAX coercion silently accepts as bool-like despite not being the JSON boolean literal — `1`, `0`, `"yes"`, `"no"`, `"on"`, `"off"`, `"TRUE"` — which is exactly what `GARBAGE_BUT_CURRENTLY_ACCEPTED` targets and what the finding's "persisting garbage" language matches (see verbatim response bodies above: the coerced boolean is genuinely persisted, `GET`-visible in the same response). The control test locks in the already-correct boundary so a future fix for the loose-coercion gap can't accidentally regress it.

---

## 4. INC-B-001 — `customer.subscription.trial_will_end` webhook is a bare `pass`

**File:** `apps/api/tests/test_wb1_incb001_trial_will_end_webhook.py`
**Command:** `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wb1_incb001_trial_will_end_webhook.py -v"`

| Node id | Result |
|---|---|
| `test_trial_will_end_webhook_records_something_not_silently_discarded` | **FAILED** [VERIFIED] |

### Verbatim failing output

```
    after = _trial_notified_at(test_user_id)
>       assert after is not None, (
            "customer.subscription.trial_will_end must leave a durable, queryable "
            "record that the reminder was handled (this test's chosen contract: "
            "Subscription.trialEndNotifiedAt stamped to now()) -- not silently "
            "discard the event. billing.py:298 is currently a bare `pass`, so "
            "no such record exists (before=%r, after=%r)." % (before, after)
        )
E       AssertionError: customer.subscription.trial_will_end must leave a durable, queryable record that the reminder was handled (this test's chosen contract: Subscription.trialEndNotifiedAt stamped to now()) -- not silently discard the event. billing.py:298 is currently a bare `pass`, so no such record exists (before=None, after=None).
E       assert None is not None
```

Summary line: `1 failed, 6 warnings in 3.05s`.

**Test-author's chosen contract (documented in the test file's module docstring, same latitude the finding text explicitly grants BLOCKER-002 for its detection rule):** no outbound-email infrastructure exists anywhere in this codebase (grepped for `smtplib`/`EmailMessage`/`sendgrid`/`postmark`/`resend` — zero hits outside `app/services/gmail_service.py`, which is the *user's own* OAuth inbox, not something Aether can send *from*), and no notification/reminder-tracking table exists either. "Notify" (a real outbound email) is therefore not a buildable minimal fix without new infrastructure a fixer would have to design from scratch; "record" is. The test asserts the smallest additive analogue of the pattern every sibling handler already uses (`UPDATE "Subscription" SET ... WHERE "userId"=%s`): a new nullable `Subscription."trialEndNotifiedAt"` timestamptz column, stamped to `now()` for the resolved user when a `trial_will_end` event is processed. The test checks `information_schema.columns` first so a not-yet-existing column produces this clean assertion failure rather than a raw `psycopg2.errors.UndefinedColumn` DB error — which is itself direct proof of "no state change," matching the code comment verbatim (`# hook point for a reminder notification; no state change`). A fixer may also wire a real outbound reminder on top of this; the test only requires the durable record.

---

## Combined run (all four files together, isolated re-run for cross-file-interference sanity)

**Command:** `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wb1_ml_settings_006_nul_byte.py tests/test_wb1_blocker002_placeholder_signer_name.py tests/test_wb1_incb002_email_verification_toggle.py tests/test_wb1_incb001_trial_will_end_webhook.py -v"`

Result: `15 failed, 6 passed, 10 warnings in 50.23s` [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-31T00:27:20Z] — identical pass/fail set and identical failure reasons to the four isolated per-file runs above; no cross-test interference, no collection/import/fixture errors anywhere.

---

## Summary — required output shape

```json
{
  "test_files": [
    "apps/api/tests/test_wb1_ml_settings_006_nul_byte.py",
    "apps/api/tests/test_wb1_blocker002_placeholder_signer_name.py",
    "apps/api/tests/test_wb1_incb002_email_verification_toggle.py",
    "apps/api/tests/test_wb1_incb001_trial_will_end_webhook.py"
  ],
  "node_ids": [
    "tests/test_wb1_ml_settings_006_nul_byte.py::test_nul_byte_in_full_name_returns_422_not_500",
    "tests/test_wb1_ml_settings_006_nul_byte.py::test_nul_byte_in_target_role_returns_422_not_500",
    "tests/test_wb1_ml_settings_006_nul_byte.py::test_nul_byte_in_location_returns_422_not_500",
    "tests/test_wb1_ml_settings_006_nul_byte.py::test_nul_byte_in_email_returns_422_regression_guard",
    "tests/test_wb1_blocker002_placeholder_signer_name.py::test_cover_letter_refuses_placeholder_signer_name[GAP-P7-DEF-B Probe 1785452243543]",
    "tests/test_wb1_blocker002_placeholder_signer_name.py::test_cover_letter_refuses_placeholder_signer_name[QA Test Runner 445566778899]",
    "tests/test_wb1_blocker002_placeholder_signer_name.py::test_cover_letter_refuses_placeholder_signer_name[probe_user_20260731093000]",
    "tests/test_wb1_blocker002_placeholder_signer_name.py::test_cover_letter_accepts_normal_human_name",
    "tests/test_wb1_incb002_email_verification_toggle.py::test_email_verification_enabled_blocks_login_for_unverified_user",
    "tests/test_wb1_incb002_email_verification_toggle.py::test_admin_settings_rejects_non_boolean_email_verification_value[1|0|yes|no|on|off|TRUE]",
    "tests/test_wb1_incb002_email_verification_toggle.py::test_admin_settings_already_rejects_structurally_invalid_values[banana|123|bad_value2|bad_value3]",
    "tests/test_wb1_incb001_trial_will_end_webhook.py::test_trial_will_end_webhook_records_something_not_silently_discarded"
  ],
  "all_fail_for_right_reason": true,
  "unexpected_passes": [
    {
      "node_id": "tests/test_wb1_ml_settings_006_nul_byte.py::test_nul_byte_in_email_returns_422_regression_guard",
      "meaning": "Expected pass, not a test defect: SettingsProfile.email is validated by email_validator BEFORE the DB layer and already rejects a NUL byte pre-existing behaviour, unrelated to the workspaces.py:1092 DB-layer root cause. Kept as a regression guard, not a second reproduction."
    },
    {
      "node_id": "tests/test_wb1_blocker002_placeholder_signer_name.py::test_cover_letter_accepts_normal_human_name",
      "meaning": "Expected pass by design: the false-positive guard the finding explicitly requires ('assert the HAPPY path'). Confirms a normal name is not rejected today and must keep working after a fix."
    },
    {
      "node_id": "tests/test_wb1_incb002_email_verification_toggle.py::test_admin_settings_already_rejects_structurally_invalid_values[*]",
      "meaning": "Expected pass, not a test defect: pydantic's own bool_parsing/bool_type validation already 422s on structurally-invalid values (string 'banana', a bare int outside {0,1}-like coercion, an array, an object). Kept as a control locking in the already-correct boundary, distinct from the genuine loose-coercion gap the other (b) test targets."
    }
  ],
  "failing_output_excerpts": [
    "ML-settings-006: AssertionError: NUL byte in profile.fullName must be rejected with 422 ... Got 500. Body: 'Internal Server Error'",
    "BLOCKER-002: AssertionError: ... Got 200: '{...\"Sincerely,\\nGAP-P7-DEF-B Probe 1785452243543\\n\"...}'",
    "INC-B-002(a): AssertionError: emailVerificationEnabled=true must block login ... Got 200: {\"access_token\":...}",
    "INC-B-002(b): AssertionError: ... must reject a non-boolean (garbage) value ... got 200 for 1: '{\"signupEnabled\":true,\"emailVerificationEnabled\":true}'",
    "INC-B-001: AssertionError: ... must leave a durable, queryable record ... billing.py:298 is currently a bare `pass` ... (before=None, after=None)"
  ],
  "notes": "All 4 assigned W-B wave 1 defects reproduced with clean, honest failing tests (12 distinct failing node ids across parametrizations, plus 6 expected-passing regression-guard/control/happy-path ids, all explicitly documented). No implementation code was touched. Tests committed separately from any fix work per §0.4. Two of the four (BLOCKER-002's placeholder-name detection rule and INC-B-001's trialEndNotifiedAt record contract) required the test-author to choose a concrete, defensible contract where the source finding named a class of fix without prescribing exact mechanics -- both choices are documented in-line in each test file's module docstring and are not binding on the fixer beyond the observable behaviour asserted."
}
```
