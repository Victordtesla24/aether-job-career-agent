"""BLOCKER-001 (GOLD-MASTER-V2 §15 step 2) — failing tests for the APPROVED
remediation described in ``docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md``
(the risk-officer's BINDING ruling).

REWRITE HISTORY: the previous version of this module asserted the REFUSED
draft's behaviour — a production boot ABORTING (``pytest.raises(RuntimeError)``
/ ``AdminCredentialSecurityError``) whenever the configured
``AETHER_ADMIN_PASSWORD_HASH`` was weak, malformed, or self-cancelling. The
risk-officer ruled that disposition unacceptable (ADR §2: "The draft fix
converts a confidentiality breach into a total availability loss" — a
crash-loop under ``Restart=on-failure``/``RestartSec=5``) and REFUSED it,
approving instead a **de-privilege, not de-boot** disposition (ADR §3, R1/R2,
R3-in-de-privilege-form): refuse the *grant*, force ``isAdmin=false`` on the
configured row, leave ``passwordHash`` untouched, log loudly, and keep
serving. Condition **C5** explicitly requires this file's weak-hash test to
be rewritten to assert that disposition instead of a raise — "Leaving it
asserting a raise would pin the outage behavior into the suite."

Every test below therefore asserts the APPROVED behaviour. Test-authorship
only (§0.4 separation of duties) — no fix is implemented here.

CONCURRENT-COMMIT NOTE (material to how "fails today" is read below): partway
through authoring this file, a fix landed on ``main`` as commit
``7f82105`` ("fix(BLOCKER-001): close admin over-permission..."), authored by
another agent working the same finding in parallel. It is NOT the REFUSED
draft described above — it already implements the de-privilege-not-de-boot
disposition for R1/R2 (conditions C1/C2/C4) plus an additional, ADR-exceeding
compensating control (``weak_operator_credential_refused`` — fail-closed at
login for the reserved ``admin`` username identifier specifically). Re-running
this suite against that commit therefore shows a MIX of results, each
recorded honestly per-test below:
* tests A.1 (boot doesn't abort) and A.4 (CRITICAL diagnostic) now PASS —
  commit 7f82105 satisfies C1 and C4.
* tests A.2+A.3 (explicit de-privilege), B (malformed-hash de-privilege), C
  (self-cancel disposition) and D (commit/raise ordering) still FAIL — commit
  7f82105 does NOT satisfy C3, does NOT convert R3 to de-privilege form (its
  own ``app/main.py`` docstring documents this as a deliberate choice that
  contradicts the ADR's explicit ruling), and does NOT address C6's ordering
  requirement. The C3 gap was verified LIVE-EXPLOITABLE during this session
  (not merely a DB-column check): a row with a pre-existing ``isAdmin=true``
  from a simulated prior boot (ADR F5) logs in successfully via the
  operator's EMAIL (not the ``admin`` username, so the commit's compensating
  auth-layer control does not cover it) with the literal weak password
  ``admin123``, and reaches ``GET /admin/users`` with a 200. See
  ``TESTS-FAIL-BEFORE.md`` for the full per-test accounting including this
  reproduction.
See git history for the original REFUSED pre-fix draft this file first
targeted (working tree contents prior to commit 7f82105).

Binding inputs read in full before writing this file:
* ``docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md`` — conditions C1-C6.
* ``uat/reports/evidence/gold-master-v2/blocker001/AUTH-CODE-MAP.md`` — exact
  file:line map of every code path exercised below.

Secrets discipline: the only password-shaped literals below are (a) denylist
entries, used exclusively as REJECTION-test input, per this module's brief
("permitted ONLY as a rejection/denylist test input, never as a stored
credential") and (b) a locally-generated strong test password that is not a
production credential and never leaves this process.
"""
from __future__ import annotations

import inspect
import re
import uuid
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import create_app
from app.repositories.admin import (
    AdminCredentialSecurityError,
    AdminRotationConfigError,
    _SEED_ADMIN_EMAIL,
    _ensure_admin_schema,
    _reset_admin_ready_for_tests,
    apply_admin_rotation,
)
from app.repositories.user import UserRepository
from app.security import hash_password

# --------------------------------------------------------------------------- #
# Shared fixtures / helpers
# --------------------------------------------------------------------------- #

#: Known-weak passwords (ADR §1 F2, §3 R1). Rejection-test input ONLY — never
#: stored as a real credential anywhere in this file.
_WEAK_ADMIN_PASSWORDS = ["admin123", "admin", "password", "changeme"]

#: Malformed / non-bcrypt "hash" values an operator could paste by mistake
#: while performing the very rotation this defect asks them to perform (ADR
#: §3 R2). None of these start with a bcrypt prefix ($2a$/$2b$/$2x$/$2y$).
_MALFORMED_ADMIN_HASHES = [
    "not-a-bcrypt-hash-at-all",
    "$1$abcdefgh$abcdefghijklmnopqrstuv",  # md5-crypt shaped, not bcrypt
]

#: A strong, unique, NOT-denylisted password used only to prove the healthy
#: path still works (condition E / operator step O5 self-restore). Generated
#: for this test file; not a real credential.
_STRONG_ADMIN_PASSWORD = "Xk9$mQ2vL8pR!wZ4nB7qT1"


def _read_admin_row(user_id: str) -> Optional[dict[str, Any]]:
    """Direct DB read of the admin-relevant columns for one user id."""
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","email","username","isAdmin","passwordHash" '
                'FROM "User" WHERE "id"=%s',
                (user_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "username": row[2],
        "isAdmin": row[3],
        "passwordHash": row[4],
    }


def _read_admin_row_by_email(email: str) -> Optional[dict[str, Any]]:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","email","username","isAdmin","passwordHash" '
                'FROM "User" WHERE lower("email")=lower(%s)',
                (email,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "username": row[2],
        "isAdmin": row[3],
        "passwordHash": row[4],
    }


def _build_app_under_production(monkeypatch: pytest.MonkeyPatch):
    """Construct a fresh app with ``AETHER_ENV=production``, WITHOUT tripping
    the two UNRELATED production guards (``_guard_production_replay_mode`` /
    ``_guard_production_discovery_fixtures``) that ``tests/conftest.py``'s
    baseline env (``AETHER_LLM_MODE=replay``, ``AETHER_DISCOVERY_FIXTURE_DIR``
    set) would otherwise trip on ANY production app construction.

    Without this, every "boot succeeds" assertion below would fail for a
    reason that has nothing to do with BLOCKER-001 — so this isolates the
    admin-rotation lifespan step as the ONLY production-sensitive thing left.
    """
    monkeypatch.setenv("AETHER_LLM_MODE", "live")
    monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)
    monkeypatch.setenv("AETHER_ENV", "production")
    return create_app()


def _assert_boot_succeeds(app) -> None:
    """Enter the app's lifespan (as uvicorn would) and confirm it serves.

    ANY exception escaping ``TestClient.__enter__`` here is a boot failure —
    exactly the crash-loop the ADR's decisive finding (§2) describes
    (``Restart=on-failure``/``RestartSec=5``: "production down, hard, with no
    self-recovery"). We deliberately catch broadly: the point of this
    assertion is "did startup succeed at all", not "which exception type".
    """
    try:
        with TestClient(app) as booted:
            health = booted.get("/health")
    except Exception as exc:  # noqa: BLE001 — any startup exception is C1/R1-R3 violation
        pytest.fail(
            "C1/R1-R3 VIOLATION: app startup raised "
            f"{type(exc).__name__}: {exc} — production would crash-loop "
            "(ADR-BLOCKER-001 §2 decisive finding)."
        )
    assert health.status_code == 200, (
        f"app booted but did not serve /health: {health.status_code} {health.text}"
    )


# --------------------------------------------------------------------------- #
# A — weak-credential disposition (R1, conditions C1/C2/C3/C4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("weak_password", _WEAK_ADMIN_PASSWORDS)
def test_weak_credential_does_not_abort_boot(monkeypatch, weak_password):
    """A.1 — ADR §3 R1, condition C1.

    Production + a denylisted ``AETHER_ADMIN_PASSWORD_HASH`` MUST NOT raise
    out of ``apply_admin_rotation()`` and MUST NOT abort application startup.

    STATUS (see module docstring's CONCURRENT-COMMIT NOTE): PASSES against
    commit 7f82105 — ``app.main._lifespan`` now catches
    ``AdminCredentialSecurityError`` non-fatally (logs CRITICAL, keeps
    serving) instead of re-raising it. Retained as a regression pin: it FAILED
    against the originally-assigned REFUSED draft (which re-raised and
    aborted ``TestClient(create_app())`` startup), and must keep passing so a
    future edit cannot silently reintroduce that crash-loop.
    """
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password(weak_password))
    app = _build_app_under_production(monkeypatch)
    _assert_boot_succeeds(app)


def test_weak_credential_forces_explicit_deprivilege_without_touching_password_hash(
    client, monkeypatch
):
    """A.2 + A.3 — ADR §3 R1, conditions C2/C3.

    C3 is explicit that *skipping* the grant is a no-op against production,
    because F5 proved the row is already ``isAdmin=true`` from a previous
    boot — so the precondition below deliberately starts the row at
    ``isAdmin=true`` (simulating F5) and requires an EXPLICIT flip to
    ``false``, not merely "we didn't set it". C2 requires ``passwordHash`` be
    byte-identical before/after — rotation must never touch it (that is what
    would lock the owner out and break cron, per the ADR's R1 table).

    STATUS (see module docstring's CONCURRENT-COMMIT NOTE): FAILS against
    commit 7f82105 too, but for a DIFFERENT reason than the originally-assigned
    REFUSED draft. That draft raised before touching any row (a "no-op"
    failure). Commit 7f82105 no longer raises fatally, and DOES run its own
    hardening steps (reclaim the reserved username, demote the SEED
    ``admin@aether.local`` row) — but it still never issues an explicit
    ``UPDATE ... SET "isAdmin"=false`` for the CONFIGURED operator row itself
    when refusing the grant; it only skips step 3 (the grant). A row that
    already carries ``isAdmin=true`` from a prior boot (this test's
    precondition, modelling ADR F5) is therefore left untouched — exactly the
    C3 failure mode named in the ADR by number ("the single most likely way
    to get R1 wrong"). CONFIRMED LIVE-EXPLOITABLE in this session (not just a
    DB-column check): with this exact precondition, ``POST /auth/login``
    using the operator's EMAIL (not the reserved ``admin`` username, so
    commit 7f82105's compensating ``weak_operator_credential_refused`` login
    guard — which only checks the ``admin`` identifier — does not apply) and
    the literal password ``admin123`` returns HTTP 200, ``GET /auth/me``
    shows ``isAdmin: true``, and ``GET /admin/users`` returns 200.
    """
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    weak_hash = hash_password("admin123")
    operator = UserRepository().create(env_email, weak_hash)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (operator["id"],))
        conn.commit()

    before = _read_admin_row(operator["id"])
    assert before["isAdmin"] is True, "test precondition setup failed"
    assert before["passwordHash"] == weak_hash, "test precondition setup failed"

    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", weak_hash)
    monkeypatch.setenv("AETHER_ENV", "production")
    _reset_admin_ready_for_tests()

    try:
        apply_admin_rotation()
    except (AdminCredentialSecurityError, AdminRotationConfigError):
        pass  # C1 is asserted elsewhere; this test only checks the DB state.

    after = _read_admin_row(operator["id"])
    assert after is not None
    assert after["isAdmin"] is False, (
        "C3 VIOLATION: configured admin row started isAdmin=true and did NOT "
        f"end isAdmin=false after rotation with a denylisted password — "
        f"before={before!r} after={after!r}. Merely skipping the grant is a "
        "no-op against a row already privileged from a previous boot (ADR §3 "
        "R1 condition C3)."
    )
    assert after["passwordHash"] == weak_hash, (
        "C2 VIOLATION: passwordHash was modified during de-privilege — "
        f"before={before['passwordHash'][:8]}... "
        f"after={after['passwordHash'][:8] if after['passwordHash'] else None}..."
    )


def test_weak_credential_logs_critical_diagnostic_naming_env_var_only(
    client, monkeypatch, capsys
):
    """A.4 — ADR §3 R1, condition C4.

    Once the guard stops raising (C1), an uncaught exception's traceback can
    no longer serve as the operator's only signal that their configured admin
    credential was rejected — the code MUST print a CRITICAL-severity
    diagnostic that names the ``AETHER_ADMIN_PASSWORD_HASH`` env var. The raw
    hash value must never appear in it (naming the matched denylist entry
    itself is explicitly permitted by C4, since denylist entries are public
    by construction — only the live hash/password value is a secret).

    STATUS (see module docstring's CONCURRENT-COMMIT NOTE): PASSES against
    commit 7f82105 — it prints a
    "CRITICAL: DEGRADED ADMIN CREDENTIAL — ..." banner (via both
    ``logging.critical`` and ``stderr``) that names
    ``AETHER_ADMIN_PASSWORD_HASH`` and never the raw hash value. Retained as a
    regression pin: it FAILED against the originally-assigned REFUSED draft
    (which raised immediately with NO stderr print at all in the production
    branch), and must keep passing so the operator never loses this signal.
    """
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    weak_hash = hash_password("admin123")
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", weak_hash)
    monkeypatch.setenv("AETHER_ENV", "production")
    _reset_admin_ready_for_tests()

    try:
        apply_admin_rotation()
    except (AdminCredentialSecurityError, AdminRotationConfigError):
        pass  # C1 is asserted elsewhere; this test only checks the diagnostic.

    diagnostic = capsys.readouterr().err
    assert "AETHER_ADMIN_PASSWORD_HASH" in diagnostic, (
        "C4 VIOLATION: no diagnostic names the AETHER_ADMIN_PASSWORD_HASH env "
        f"var. Captured stderr: {diagnostic!r}"
    )
    assert re.search(r"CRITICAL", diagnostic), (
        "A.4 VIOLATION: diagnostic is not CRITICAL-severity. Captured "
        f"stderr: {diagnostic!r}"
    )
    assert weak_hash not in diagnostic, (
        "C4 VIOLATION: the raw AETHER_ADMIN_PASSWORD_HASH value leaked into "
        f"the diagnostic. Captured stderr: {diagnostic!r}"
    )


# --------------------------------------------------------------------------- #
# B — malformed (non-bcrypt) hash: same treatment (R2, conditions C1-C4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("malformed_hash", _MALFORMED_ADMIN_HASHES)
def test_malformed_hash_does_not_abort_boot_and_deprivileges(monkeypatch, malformed_hash):
    """B — ADR §3 R2 ("same treatment" as R1; conditions C1-C4 apply
    identically). A malformed/non-bcrypt ``AETHER_ADMIN_PASSWORD_HASH`` — the
    exact mistake an operator makes while pasting a plaintext password into
    the hash variable during the very rotation this defect asks them to
    perform — must NOT abort boot, and must force the configured row to
    ``isAdmin=false`` rather than leaving it (or a prior boot's grant)
    privileged.

    STATUS (see module docstring's CONCURRENT-COMMIT NOTE): the BOOT-SUCCEEDS
    half now PASSES against commit 7f82105 (same C1 fix as item A). The
    DE-PRIVILEGE half still FAILS for the identical C3 gap as item A.2/A.3 —
    the malformed-hash branch also only skips the grant rather than issuing an
    explicit ``isAdmin=false`` UPDATE, so a row already privileged from a
    prior boot is left untouched.
    """
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    operator = UserRepository().create(env_email, hash_password(_STRONG_ADMIN_PASSWORD))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (operator["id"],))
        conn.commit()

    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", malformed_hash)
    app = _build_app_under_production(monkeypatch)
    _assert_boot_succeeds(app)

    row = _read_admin_row(operator["id"])
    assert row is not None and row["isAdmin"] is False, (
        "R2/C3 VIOLATION: malformed-hash config did not de-privilege the "
        f"configured admin row (already isAdmin=true from a previous boot): "
        f"{row!r}"
    )


# --------------------------------------------------------------------------- #
# C — self-cancel config (R3, approved only in de-privilege form)
# --------------------------------------------------------------------------- #


def test_self_cancel_config_deprivileges_instead_of_raising(monkeypatch):
    """C — ADR §3 R3: "REFUSED as currently written; APPROVED in de-privilege
    form." When ``AETHER_ADMIN_EMAIL`` names the seeded demo address (so the
    §14.7 demote/regrant pair would self-cancel and leave the demo identity
    privileged), the approved disposition is IDENTICAL to R1/R2: de-privilege
    + continue booting, never a raise.

    This test deliberately uses ``AETHER_ENV=production`` (not merely "any
    non-production environment") because the ADR's own critique of the
    current draft is that this guard "raises unconditionally — not gated on
    ``_is_production()``" (§3 R3) — i.e. it currently crashes EVEN OUTSIDE
    production. Proving the fix under ``AETHER_ENV=production`` specifically
    is the case that matters most (a real deploy), and is not weaker than the
    unconditional case: if production doesn't crash-loop, the fix cannot be
    relying on an ``_is_production()`` gate that merely relocates the crash
    to a non-production environment instead of removing it.

    A STRONG, well-formed password hash is used so this test isolates the
    self-cancel condition specifically, independent of the weak/malformed
    dispositions covered by A/B.

    STATUS (see module docstring's CONCURRENT-COMMIT NOTE): STILL FAILS
    against commit 7f82105, unchanged from the originally-assigned REFUSED
    draft on this specific path: ``apply_admin_rotation()``'s step 0 still
    raises ``AdminRotationConfigError`` unconditionally when
    ``AETHER_ADMIN_EMAIL`` equals the seeded demo email, and
    ``app.main._lifespan`` still re-raises it, aborting boot. This is not an
    oversight — commit 7f82105's own ``app/main.py::_lifespan`` docstring
    explicitly argues for keeping this one fatal ("This IS a deliberate
    deploy-time misconfiguration... it propagates and aborts boot"),
    reasoning by analogy to ``_guard_production_replay_mode``. That reasoning
    directly contradicts the BINDING ADR ruling (§3 R3: "REFUSED as currently
    written... A guard that turns a config typo into a total outage is not
    acceptable in a service with Restart=on-failure" / "Must be converted to:
    refuse the grant, force isAdmin=false, log, continue"). This test
    therefore currently pins a real, documented divergence from the binding
    ruling, not a test bug.
    """
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", _SEED_ADMIN_EMAIL)
    monkeypatch.setenv(
        "AETHER_ADMIN_PASSWORD_HASH", hash_password(_STRONG_ADMIN_PASSWORD)
    )
    app = _build_app_under_production(monkeypatch)
    _assert_boot_succeeds(app)

    row = _read_admin_row_by_email(_SEED_ADMIN_EMAIL)
    assert row is None or row["isAdmin"] is False, (
        "R3 VIOLATION: self-cancelling AETHER_ADMIN_EMAIL config left the "
        f"seeded demo identity isAdmin=true instead of de-privileged: {row!r}"
    )


# --------------------------------------------------------------------------- #
# D — ordering: the grant commit must never be followed by a raise (§2.1, C6)
# --------------------------------------------------------------------------- #


def test_no_raise_statement_follows_a_database_commit_in_apply_admin_rotation():
    """D — ADR §2.1 ("a second, independent defect in the same draft") and
    condition C6: "the post-condition at admin.py:833-839 must be evaluated
    before the commit."

    Ordering invariant, independent of exception type or which condition
    triggers it: ``apply_admin_rotation()`` must never execute a database
    ``conn.commit()`` and THEN, later in the same function, execute a
    ``raise`` — a raise after a commit means the privilege the function just
    persisted is reported to the caller as a FAILURE. ``app.main._lifespan``
    treats that raise as "refuse to boot", but the write is already durable —
    the worst of both outcomes: the database is left in the vulnerable state
    AND the API refuses to serve traffic (ADR §2.1: "the privilege is already
    persisted AND the app refuses to boot").

    This is a WHITE-BOX structural test, not a black-box behavioural one, and
    that is a deliberate, documented choice: the one condition that would
    reach this exact ordering bug through legitimate external configuration
    (``AETHER_ADMIN_EMAIL`` colliding with the seeded identity) is ALREADY
    intercepted earlier by the unconditional step-0 self-cancel check (see
    the sibling test for that check, item C) — so the buggy ordering is not
    reachable through any external input this test file can construct today.
    Condition C6 requires it fixed anyway, as defence against a future edit
    to either email predicate — the current draft's OWN comment
    (``admin.py`` around the post-condition) names this exact risk
    ("if it ever happens anyway (e.g. a future edit to either predicate)").
    A structural assertion on the function's source is therefore the smallest
    honest way to pin this property in the suite, and is written generically
    (ANY commit followed by ANY raise, not tied to a specific exception type
    or variable name) so it does not presume how the fix restructures the
    code — only that it must not leave a raise after a commit.

    STATUS (see module docstring's CONCURRENT-COMMIT NOTE): STILL FAILS
    against commit 7f82105, unchanged: ``apply_admin_rotation()`` still
    commits the operator-admin grant transaction and only THEN evaluates
    ``if admin_id in demoted_ids: raise AdminRotationConfigError(...)`` — a
    ``raise`` statement that textually and execution-order-wise follows that
    commit. C6 was not addressed by this commit.
    """
    source = inspect.getsource(apply_admin_rotation)
    lines = source.splitlines()

    commit_line_idxs = [i for i, ln in enumerate(lines) if re.search(r"\bconn\.commit\(\)", ln)]
    raise_line_idxs = [i for i, ln in enumerate(lines) if re.match(r"\s*raise\b", ln)]

    assert commit_line_idxs, (
        "sanity check failed: apply_admin_rotation() must commit its writes "
        "somewhere — this test cannot evaluate ordering without at least one "
        "conn.commit() in the source."
    )

    last_commit_idx = max(commit_line_idxs)
    offending = [i for i in raise_line_idxs if i > last_commit_idx]

    assert not offending, (
        "D VIOLATION (ADR §2.1 / condition C6): apply_admin_rotation() "
        f"contains a `raise` statement at source-line offset(s) {offending} "
        f"AFTER its last `conn.commit()` at offset {last_commit_idx} — a code "
        "path exists where privilege is durably written to the database and "
        "the caller is then told the operation failed. Evaluate every "
        "post-condition BEFORE committing, not after.\n"
        "--- offending lines ---\n"
        + "\n".join(f"{i}: {lines[i]}" for i in offending)
    )


# --------------------------------------------------------------------------- #
# E — healthy-credential regression (operator self-restore, O5)
# --------------------------------------------------------------------------- #


def test_healthy_credential_still_grants_admin_and_boot_succeeds(monkeypatch):
    """E — regression pin. Proves R1's de-privilege disposition does not
    regress the HAPPY path: once the operator rotates to a STRONG,
    well-formed, non-denylisted hash (operator step O5), rotation must still
    grant ``isAdmin=true`` to the configured operator, and application boot
    must succeed. This is what lets the R1 de-privilege reverse itself
    automatically on the next boot after the operator rotates — the ADR's
    stated recovery path (§3 R1 "What could go wrong": "the rotation runs on
    every app construction, so a restart fixes it").

    Included as an explicit regression guard so a future tightening of the
    weak/malformed/self-cancel guards cannot silently break the non-degraded
    path along with fixing the degraded ones. PASSES against both the
    originally-assigned REFUSED draft and commit 7f82105 (the guard only
    activates on weak/malformed/self-cancel inputs) — listed here for
    completeness of the acceptance matrix rather than as a new defect
    reproduction.
    """
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    strong_hash = hash_password(_STRONG_ADMIN_PASSWORD)
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", strong_hash)
    app = _build_app_under_production(monkeypatch)
    _assert_boot_succeeds(app)

    row = _read_admin_row_by_email(env_email)
    assert row is not None and row["isAdmin"] is True, (
        f"E VIOLATION: healthy, strong credential did not grant isAdmin=true "
        f"— {row!r}"
    )
    assert row["passwordHash"] == strong_hash


# --------------------------------------------------------------------------- #
# F — non-admin authorization regression (must stay green)
# --------------------------------------------------------------------------- #

#: Every AdminUser-gated route (AUTH-CODE-MAP.md §6). Mutation routes use a
#: syntactically-plausible but nonexistent user id — AdminUser is a
#: ``Depends()`` resolved BEFORE the handler body, so a non-admin gets 403
#: before the id is ever looked up (confirmed: app/routers/admin.py, every
#: handler takes ``AdminUser`` as its first parameter).
_ADMIN_ROUTES: list[tuple[str, str]] = [
    ("GET", "/admin/health"),
    ("GET", "/admin/users"),
    ("GET", "/admin/users/does-not-exist"),
    ("GET", "/admin/spend"),
    ("GET", "/admin/settings"),
    ("POST", "/admin/settings"),
    ("POST", "/admin/users/does-not-exist/spend-cap"),
    ("POST", "/admin/users/does-not-exist/suspend"),
    ("POST", "/admin/users/does-not-exist/unsuspend"),
]


def test_non_admin_gets_403_on_every_admin_route_pin(client, auth_headers):
    """F — regression pin, NOT a BLOCKER-001 defect reproduction. A genuine
    non-admin (freshly registered via the ``auth_headers`` fixture — not
    reached through any demo-identifier or weak-credential path) must
    receive 403 from every ``AdminUser``-gated route, and must never see
    another user's data through them.

    This is deliberately EXPECTED TO PASS against current code — the
    ``AdminUser`` gate itself (``app/middleware/auth.py:61-70``) is already
    correctly implemented for genuine non-admins; BLOCKER-001 was never about
    this gate being broken, it was about the *demo identifier* resolving to
    a privileged row that then walked through this (correctly-enforced)
    gate. Documented honestly per this task's standing instruction not to
    invent a gap where none exists — do not count this test toward "all
    tests fail before the fix".
    """
    for method, path in _ADMIN_ROUTES:
        resp = client.request(method, path, headers=auth_headers, json={})
        assert resp.status_code == 403, f"{method} {path}: {resp.status_code} {resp.text}"
