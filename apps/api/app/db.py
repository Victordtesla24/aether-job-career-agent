"""Raw psycopg2 access to the Prisma-managed PostgreSQL database (P2-S01).

The schema itself is owned by Prisma (``packages/db/src/schema.prisma``); the
API reads/writes it with plain SQL. Prisma-style URLs carry a ``?schema=``
query parameter that psycopg2 does not understand, so it is translated into a
``search_path`` option here.

The hosted PostgreSQL caps concurrent connections at 25 and kills idle
transactions, so connections are short-lived: acquire, use, release. They are
handed out by a bounded per-process pool (:class:`_ConnectionPool`) instead of
being dialled fresh every time — see ``get_connection`` and the connection
budget documented on ``_default_pool_max``.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def _translate_prisma_url(url: str) -> tuple[str, str | None]:
    """Strip Prisma's ``schema`` query param; return (dsn, schema)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    dsn = urlunparse(parsed._replace(query=query))
    return dsn, schema


def get_database_url() -> str:
    """Resolve the database URL from the environment (test-swappable)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


#: ML-settings-006 / ML-RESUME-001: a NUL byte (0x00) in user-supplied text
#: reaching psycopg2/Postgres shows up as ONE OF TWO distinct exception
#: shapes, both reproduced live against this codebase:
#:
#: 1. ``ValueError`` — raised CLIENT-SIDE by psycopg2 itself, before the SQL
#:    is even sent, when a NUL byte sits directly in a plain string
#:    parameter (e.g. ``UPDATE "User" SET name=%s`` with a raw Python str —
#:    ``PUT /workspaces/settings``). Message: "A string literal cannot
#:    contain NUL (0x00) characters."
#: 2. ``psycopg2.errors.UntranslatableCharacter`` — raised SERVER-SIDE by
#:    Postgres's own JSON parser when a NUL byte is embedded inside a JSON/
#:    JSONB parameter: ``json.dumps`` legally escapes it as a 6-character
#:    JSON escape sequence (backslash, u, 0, 0, 0, 0) — not a literal NUL
#:    byte — which sails past psycopg2's client-side check above, but
#:    Postgres's ``text`` type still cannot represent codepoint U+0000 once
#:    the JSON escape is decoded, so it rejects it as "unsupported Unicode
#:    escape sequence" / "<the escape sequence> cannot be converted to text"
#:    (``POST /resumes``' ``sections`` JSON column).
#:
#: Matched on these specific message substrings only — any OTHER
#: ``ValueError`` or ``UntranslatableCharacter`` (e.g. a genuinely invalid
#: non-NUL Unicode escape) is re-raised untouched, never treated as this case.
_NUL_BYTE_VALUE_ERROR_MARKER = "NUL (0x00)"
_NUL_BYTE_JSON_ESCAPE_MARKER = "\\u0000"

_NUL_BYTE_USER_MESSAGE = (
    "Invalid input: a field contains an unsupported NUL (0x00) character."
)


def _is_nul_byte_failure(exc: BaseException) -> bool:
    if isinstance(exc, ValueError) and _NUL_BYTE_VALUE_ERROR_MARKER in str(exc):
        return True
    if (
        isinstance(exc, psycopg2.errors.UntranslatableCharacter)
        and _NUL_BYTE_JSON_ESCAPE_MARKER in str(exc)
    ):
        return True
    return False


class _NulByteGuardCursor(psycopg2.extensions.cursor):
    """A NUL byte in ANY string parameter makes psycopg2/Postgres raise one
    of the two exception shapes documented above (:func:`_is_nul_byte_failure`)
    synchronously inside ``.execute()``/``.executemany()`` — on a SELECT/WHERE
    lookup exactly as much as an INSERT/UPDATE, and on a plain text column
    exactly as much as a JSON/JSONB one. Uncaught, either propagates out of
    whichever route triggered it as an unhandled 500 with a full traceback —
    reproduced live on at least three independent endpoints
    (``PUT /workspaces/settings``, ``POST /resumes``,
    ``POST /agents/tailor/run``; ML-settings-006 / ML-RESUME-001), because
    none of them (nor anything upstream) guarded against it individually.

    Rather than patching each call site (§13.1 forbids duplicating that
    guard per router/field), this cursor class is installed ONCE as the
    ``cursor_factory`` on every connection ``get_connection()`` yields
    (below) — the single seam every ``cur.execute(...)`` call in this
    codebase already passes through (237+ call sites at last grep). It
    changes nothing for any query that does not hit one of these two exact
    shapes: only those are intercepted and translated into an honest,
    specific 422 (never a 500, never a leaked "ValueError"/"psycopg2"/
    traceback) — every other exception, including any other
    ``ValueError``/``psycopg2.Error`` raised for an unrelated reason
    (e.g. a genuine ``UniqueViolation``, which existing per-router ``except``
    clauses already handle), is re-raised untouched, same object, same
    traceback.

    Raising ``fastapi.HTTPException`` directly from this low-level DB module
    (rather than a bespoke exception a router would need to catch, or a
    handler registered on the ``FastAPI`` app instance) is deliberate: it
    needs no registration anywhere — Starlette/FastAPI already install a
    default handler for ``HTTPException`` on every app instance — so this
    is the only seam that closes the gap application-wide without touching
    ``app/main.py`` (occupied by a concurrent BLOCKER-001 fix at the time of
    this change; editing it risked a collision with unrelated in-flight
    work).
    """

    def execute(self, query: Any, vars: Any = None) -> Any:  # noqa: A002 - matches psycopg2's own signature
        try:
            return super().execute(query, vars)
        except (ValueError, psycopg2.Error) as exc:
            if _is_nul_byte_failure(exc):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, _NUL_BYTE_USER_MESSAGE
                ) from None
            raise

    def executemany(self, query: Any, vars_list: Any) -> Any:
        try:
            return super().executemany(query, vars_list)
        except (ValueError, psycopg2.Error) as exc:
            if _is_nul_byte_failure(exc):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, _NUL_BYTE_USER_MESSAGE
                ) from None
            raise


class PoolExhaustedError(RuntimeError):
    """No pooled connection became available inside the acquire timeout.

    Raised (and translated into an honest HTTP 503 by ``get_connection``) rather
    than waiting forever: S-3's failure mode is a request that hangs holding a
    thread until something upstream times out, which is strictly worse for the
    user than being told the truth immediately.
    """


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer — using %d", name, raw, default)
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number — using %.3f", name, raw, default)
        return default
    return value if value > 0 else default


#: Env var each process uses to declare its own slice of the 25-connection cap.
POOL_MAX_ENV = "AETHER_DB_POOL_MAX"

#: DEFAULT per-process ceiling on OPEN connections. The hosted PostgreSQL caps
#: the whole account at 25 concurrent connections, so every consumer gets an
#: explicit slice (S-3). Every consumer of ``get_connection`` was enumerated
#: before choosing these numbers:
#:
#:   * API (``uvicorn app.main:app``, ONE process, no ``--workers``): sync route
#:     handlers run on anyio's default thread pool (~40 threads), so before this
#:     pool existed up to ~40 simultaneous ``psycopg2.connect`` calls were
#:     possible against a 25-connection account. Slice: **12** (this default).
#:   * arq worker (``app.workers.settings``, ``max_jobs=3`` + 3 cron jobs):
#:     a handful of concurrent jobs, each opening connections one at a time
#:     through repositories. Slice: **4**, set via ``AETHER_DB_POOL_MAX=4`` in
#:     ``start-worker.sh``.
#:   * One-shot scripts (``apps/api/scripts/*.py``), ``psql`` sessions, Prisma
#:     migrations and the pytest suite: short-lived, run by an operator.
#:     Reserve: the remaining **9** (25 - 12 - 4), which is also the headroom
#:     that keeps a stuck API process from starving an operator's psql.
#:
#: A process that needs a different slice sets ``AETHER_DB_POOL_MAX``; nothing
#: here silently grows past the value it is given.
_DEFAULT_POOL_MAX = 12

#: How long ``get_connection`` waits for a free slot before giving up with an
#: honest 503. Bounded — never infinite (see :class:`PoolExhaustedError`).
_DEFAULT_ACQUIRE_TIMEOUT_SECONDS = 5.0

#: Idle connections kept warm between requests. Open-but-unused connections
#: still occupy the account-wide 25-connection cap, so the pool keeps only a
#: small warm set and closes the rest on release; ``_DEFAULT_POOL_MAX`` remains
#: the hard ceiling on connections OPEN AT ONCE.
_DEFAULT_MAX_IDLE = 4

#: An idle pooled connection older than this is closed and re-dialled on
#: acquire rather than trusted. The hosted database kills queries at 5s and
#: idle transactions at 30s, and its proxy can drop an idle session with no
#: notice the client sees until the next statement fails.
_DEFAULT_RECYCLE_SECONDS = 60.0

#: An idle pooled connection older than this is validated with ``SELECT 1``
#: before being handed out (cheap pre-ping). Fresher connections skip the round
#: trip: they were used moments ago, so a mid-flight death is caught by the
#: caller's own statement and the broken connection is discarded on release.
_DEFAULT_PREPING_AFTER_SECONDS = 5.0


def _default_pool_max() -> int:
    return _env_int(POOL_MAX_ENV, _DEFAULT_POOL_MAX)


class _ConnectionPool:
    """A bounded, thread-safe pool of psycopg2 connections for ONE DSN.

    Deliberately hand-rolled rather than ``psycopg2.pool.ThreadedConnectionPool``
    because three behaviours this deployment needs are not available there:

    1. **Bounded waiting.** ``ThreadedConnectionPool.getconn()`` raises
       immediately once ``maxconn`` is reached; here a caller waits up to
       ``acquire_timeout`` for a peer to finish (smoothing the bursty dashboard
       fan-out that motivated S-3) and only then fails — and it always fails
       eventually rather than hanging.
    2. **Idle trimming.** Only ``max_idle`` connections are kept warm; the rest
       are closed on release so idle sockets do not sit on the account-wide
       25-connection cap while another process needs one.
    3. **Recycling / pre-ping.** The hosted database kills 5s queries and 30s
       idle transactions, so a pooled connection can be dead by the time it is
       reused. Stale ones are re-dialled and marginal ones validated with
       ``SELECT 1`` before being handed out, instead of surfacing as a random
       ``OperationalError`` in an unrelated request.
    """

    def __init__(
        self,
        dsn: str,
        options: str | None,
        *,
        max_size: int,
        acquire_timeout: float,
        max_idle: int,
        recycle_seconds: float,
        preping_after_seconds: float,
    ) -> None:
        self.dsn = dsn
        self.options = options
        self.max_size = max_size
        self.acquire_timeout = acquire_timeout
        self.max_idle = max_idle
        self.recycle_seconds = recycle_seconds
        self.preping_after_seconds = preping_after_seconds
        self._cond = threading.Condition(threading.Lock())
        #: (connection, released_at_monotonic), most-recently-released last.
        self._idle: deque[tuple[Any, float]] = deque()
        #: Connections that EXIST right now (idle + leased). Never > max_size.
        self._open = 0
        self._leased = 0

    # -- internals ---------------------------------------------------------
    def _connect(self) -> Any:
        return psycopg2.connect(
            self.dsn, options=self.options, cursor_factory=_NulByteGuardCursor
        )

    @staticmethod
    def _close_quietly(conn: Any) -> None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — closing a dead socket must never raise
            pass

    def _is_usable(self, conn: Any, idle_for: float) -> bool:
        """Whether a pooled connection can be handed out as-is."""
        if conn.closed:
            return False
        if idle_for >= self.recycle_seconds:
            return False
        if idle_for < self.preping_after_seconds:
            return True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.rollback()
        except Exception:  # noqa: BLE001 — a failed ping means "discard it"
            return False
        return True

    # -- public ------------------------------------------------------------
    def acquire(self, timeout: float | None = None) -> Any:
        timeout = self.acquire_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            reuse: Any = None
            with self._cond:
                if self._idle:
                    reuse, released_at = self._idle.pop()
                    self._leased += 1
                elif self._open < self.max_size:
                    self._open += 1
                    self._leased += 1
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not self._cond.wait(remaining):
                        if deadline - time.monotonic() <= 0:
                            raise PoolExhaustedError(
                                f"all {self.max_size} pooled database connections "
                                f"are busy (waited {timeout:.1f}s)"
                            )
                    continue
            # Dialling / validating happens OUTSIDE the lock so a slow TCP
            # handshake never blocks other threads returning connections.
            try:
                if reuse is not None:
                    if self._is_usable(reuse, time.monotonic() - released_at):
                        return reuse
                    self._close_quietly(reuse)
                return self._connect()
            except Exception:
                with self._cond:
                    self._open -= 1
                    self._leased -= 1
                    self._cond.notify()
                raise

    def release(self, conn: Any, *, discard: bool = False) -> None:
        keep = not discard and not conn.closed
        if keep:
            # Mirrors what ``conn.close()`` used to guarantee: nothing a caller
            # left uncommitted is ever visible to the next borrower.
            try:
                status = conn.get_transaction_status()
                if status == psycopg2.extensions.TRANSACTION_STATUS_UNKNOWN:
                    keep = False
                elif status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                    conn.rollback()
            except Exception:  # noqa: BLE001 — un-rollback-able ⇒ not reusable
                keep = False
        with self._cond:
            self._leased -= 1
            if keep and len(self._idle) < self.max_idle:
                self._idle.append((conn, time.monotonic()))
            else:
                self._open -= 1
                keep = False
            self._cond.notify()
        if not keep:
            self._close_quietly(conn)

    def close_all(self) -> None:
        with self._cond:
            idle, self._idle = list(self._idle), deque()
            self._open -= len(idle)
            self._cond.notify_all()
        for conn, _ in idle:
            self._close_quietly(conn)

    def stats(self) -> dict[str, Any]:
        with self._cond:
            return {
                "max": self.max_size,
                "open": self._open,
                "leased": self._leased,
                "idle": len(self._idle),
            }


_pool_lock = threading.Lock()
_pool: _ConnectionPool | None = None
_pool_pid: int | None = None


def _get_pool() -> _ConnectionPool:
    """The process-wide pool for the CURRENT ``DATABASE_URL``.

    Rebuilt (never shared) when the DSN changes — the test-suite swaps in the
    ``aether_test`` schema — or when the pid changes, because a pool inherited
    across ``fork()`` would hand a child a socket its parent is also using.
    """
    global _pool, _pool_pid
    dsn, schema = _translate_prisma_url(get_database_url())
    options = f"-csearch_path={schema}" if schema else None
    pid = os.getpid()
    with _pool_lock:
        current = _pool
        if current is not None and _pool_pid != pid:
            # Inherited across a fork: drop the reference WITHOUT closing, since
            # the sockets belong to the parent process.
            current = None
            _pool = None
        if current is not None and (current.dsn != dsn or current.options != options):
            stale, _pool = current, None
            stale.close_all()
            current = None
        if current is None:
            current = _ConnectionPool(
                dsn,
                options,
                max_size=_default_pool_max(),
                acquire_timeout=_env_float(
                    "AETHER_DB_POOL_ACQUIRE_TIMEOUT_SECONDS",
                    _DEFAULT_ACQUIRE_TIMEOUT_SECONDS,
                ),
                max_idle=_env_int("AETHER_DB_POOL_MAX_IDLE", _DEFAULT_MAX_IDLE),
                recycle_seconds=_env_float(
                    "AETHER_DB_POOL_RECYCLE_SECONDS", _DEFAULT_RECYCLE_SECONDS
                ),
                preping_after_seconds=_env_float(
                    "AETHER_DB_POOL_PREPING_AFTER_SECONDS",
                    _DEFAULT_PREPING_AFTER_SECONDS,
                ),
            )
            _pool, _pool_pid = current, pid
        return current


def pool_stats() -> dict[str, Any]:
    """Live pool counters (``max``/``open``/``leased``/``idle``) for ops+tests."""
    return _get_pool().stats()


def reset_pool() -> None:
    """Close every idle pooled connection and forget the pool.

    Used by tests that change the pool's env knobs; leased connections are left
    to their owners and simply close on release.
    """
    global _pool, _pool_pid
    with _pool_lock:
        stale, _pool, _pool_pid = _pool, None, None
    if stale is not None:
        stale.close_all()


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    """Yield a pooled psycopg2 connection with the right ``search_path``.

    The contract every one of the 650+ call sites already relies on is
    unchanged: a ready-to-use connection with the NUL-byte guard cursor
    installed, work committed explicitly by the caller, anything uncommitted
    discarded on exit. What changed (S-3) is that the connection comes from a
    bounded pool instead of a fresh ``psycopg2.connect`` per use, so this
    process can never hold more than its slice of the hosted 25-connection cap.

    When every slot is busy for longer than the acquire timeout the caller gets
    an honest ``503`` — never an unbounded wait, and never a silent success on
    a connection that does not exist.
    """
    pool = _get_pool()
    try:
        conn = pool.acquire()
    except PoolExhaustedError as exc:
        logger.warning("database pool exhausted: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The service is at capacity right now. Please retry in a moment.",
        ) from exc
    discard = False
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        # The connection itself failed (server hung up, killed query, dropped
        # socket). Never return it to the pool — the next borrower would
        # inherit the breakage.
        discard = True
        raise
    finally:
        pool.release(conn, discard=discard)


def new_id() -> str:
    """Generate a cuid-shaped identifier compatible with Prisma's ids."""
    return "c" + secrets.token_hex(12)


def rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    """Materialize all rows of a cursor as column-name dicts."""
    columns = [col.name for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


#: Guard so the additive ``User`` profile columns are only ensured once per
#: worker process (see ``ensure_user_profile_columns``).
_user_profile_columns_ready = False


def ensure_user_profile_columns() -> None:
    """Idempotently add the additive profile columns to ``User`` on first use.

    ``targetRole``/``location``/``agentConfig``/``username`` were introduced
    after the original Prisma migration and only ALTER-added to the production
    ``aether`` schema. The shared test schema (``aether_test``) predates them,
    so any query that reads these columns would fail there with
    ``UndefinedColumn``.

    ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` is a no-op where the columns
    already exist (production) and safely backfills them everywhere else. The
    ``username`` column is additionally given a nullable UNIQUE index (multiple
    NULLs are allowed by Postgres, so pre-existing users without a username are
    unaffected) via ``CREATE UNIQUE INDEX IF NOT EXISTS``, keeping the whole
    migration additive and backward-compatible. A transaction-scoped advisory
    lock serializes concurrent first-hit callers so the DDL can't race,
    mirroring the pattern used for the agent config tables. ``TRUNCATE`` never
    drops columns, so this survives the test-suite teardown.
    """
    global _user_profile_columns_ready
    if _user_profile_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: even as a no-op, ALTER takes an ACCESS
            # EXCLUSIVE lock, so it stalls behind any concurrent reader and
            # dies on the hosted 5s statement timeout. Only reach for DDL
            # when a column is actually missing.
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'User'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('targetRole', 'location', 'agentConfig',"
                " 'username')"
            )
            row = cur.fetchone()
            if row and row[0] == 4:
                _user_profile_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240712,))
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "targetRole" text')
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "location" text')
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "agentConfig" jsonb'
            )
            cur.execute('ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "username" text')
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "User_username_key"'
                ' ON "User" ("username")'
            )
        conn.commit()
    _user_profile_columns_ready = True


#: Guard so the additive admin/security columns are only ensured once per worker
#: process (see ``ensure_admin_user_columns``).
_admin_user_columns_ready = False


def ensure_admin_user_columns() -> None:
    """Idempotently add the additive admin/security columns to ``User``.

    ``isAdmin`` (privilege gate, GAP-P6-ADMIN-001), ``suspended`` (GAP-P6 §15
    account suspension) and ``lastLoginAt`` (§15 user list) are additive columns.
    They are introduced by lazy DDL (ADR-TR-1) — there is no migration runner —
    so every admin/auth read path calls this first, mirroring
    ``ensure_user_profile_columns``.

    ``ADD COLUMN ... NOT NULL DEFAULT false`` is a metadata-only change on
    PostgreSQL (the constant default is not rewritten across existing rows), so
    it is fast and safe on the production ``User`` table and backfills the shared
    test schema. A transaction-scoped advisory lock serializes concurrent
    first-hit callers so the DDL cannot race; ``TRUNCATE`` never drops columns,
    so this survives the test-suite teardown.
    """
    global _admin_user_columns_ready
    if _admin_user_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTER when both
            # columns already exist (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'User'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('isAdmin', 'suspended', 'lastLoginAt')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
                _admin_user_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240720,))
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "isAdmin" boolean'
                " NOT NULL DEFAULT false"
            )
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "suspended" boolean'
                " NOT NULL DEFAULT false"
            )
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "lastLoginAt" timestamptz'
            )
        conn.commit()
    _admin_user_columns_ready = True


#: Guard so the additive password-reset support column on ``User`` is only
#: ensured once per worker process (see ``ensure_password_reset_columns``).
_password_reset_columns_ready = False


def ensure_password_reset_columns() -> None:
    """Idempotently add the additive ``User."passwordChangedAt"`` column.

    O-4 (self-service password reset). Stamped by
    ``UserRepository.set_password`` on every successful
    ``POST /auth/reset-password``. ``app.middleware.auth.get_current_user``
    compares it against the JWT's ``iat`` claim so a reset invalidates every
    access token minted before it — the only "invalidate sessions" mechanism
    available without a server-side session store, since tokens are otherwise
    verified purely by signature + expiry. Lazy DDL (ADR-TR-1); NULL for every
    pre-existing user reads as "never reset" and is skipped by that comparison,
    so no existing session is affected until its owner actually resets. A
    transaction-scoped advisory lock serializes concurrent first-hit callers;
    ``TRUNCATE`` never drops columns, so this survives the test-suite teardown.
    """
    global _password_reset_columns_ready
    if _password_reset_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'User'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'passwordChangedAt'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _password_reset_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260805,))
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "passwordChangedAt" timestamptz'
            )
        conn.commit()
    _password_reset_columns_ready = True


#: Guard so the additive ``Resume`` approval + original-upload columns are only
#: ensured once per worker process (see ``ensure_resume_columns``).
_resume_columns_ready = False

#: Every additive ``Resume`` column managed by :func:`ensure_resume_columns`.
#: ``formatHash`` is listed because the function's contract is "these columns
#: exist"; it is already created NOT NULL by Prisma, so its ``ADD COLUMN IF NOT
#: EXISTS`` below is a permanent no-op on any real schema — it is kept so the
#: runtime DDL and ``migrations/0027_resume_original_upload.sql`` state exactly
#: the same set of columns the résumé paths depend on.
_RESUME_MANAGED_COLUMNS = (
    "approvalStatus",
    "originalFile",
    "originalFilename",
    "originalContentType",
    "formatHash",
)


def ensure_resume_columns() -> None:
    """Idempotently add the additive ``Resume`` columns on first use.

    ``approvalStatus`` (MV-resume-studio-001) records the human-in-the-loop review
    state of a résumé version — ``pending`` for a freshly tailored child version
    that awaits sign-off, ``approved``/``rejected`` once the linked
    ``ApprovalRequest`` is resolved. It is introduced by lazy DDL (ADR-TR-1 — there
    is no migration runner), so the résumé read/write paths call this first,
    mirroring ``ensure_user_profile_columns``.

    ``ADD COLUMN ... NOT NULL DEFAULT 'approved'`` is a metadata-only change on
    PostgreSQL (the constant default is not rewritten across existing rows), so it
    is fast and safe on the production ``Resume`` table and backfills the shared
    test schema. Defaulting to ``approved`` keeps EVERY pre-existing résumé
    version (the immutable base and all historical tailored versions) usable and
    downloadable exactly as before — backward compatible; only newly tailored
    versions are created ``pending``. A transaction-scoped advisory lock serializes
    concurrent first-hit callers so the DDL cannot race; ``TRUNCATE`` never drops
    columns, so this survives the test-suite teardown.

    ``originalFile``/``originalFilename``/``originalContentType`` (U2a, R-F1)
    hold the EXACT bytes the user uploaded plus their identity, so the baseline
    résumé is a real immutable document and not just extracted text — before
    this, upload bytes were discarded and only ``sections`` survived, which is
    why every real upload could only ever be re-flowed into the generic branded
    template on download. All three are added with NO default: every
    pre-existing row therefore reads NULL, which means exactly "no original
    stored (uploaded before format preservation existed)" — an honest gap that
    ``GET /resumes/{id}/original`` reports as a 404 rather than fabricating a
    file. Nothing is backfilled because the bytes genuinely no longer exist.
    """
    global _resume_columns_ready
    if _resume_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTERs when every
            # managed column already exists (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Resume'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                (list(_RESUME_MANAGED_COLUMNS),),
            )
            row = cur.fetchone()
            if row and row[0] == len(_RESUME_MANAGED_COLUMNS):
                _resume_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240721,))
            cur.execute(
                'ALTER TABLE "Resume" ADD COLUMN IF NOT EXISTS "approvalStatus" text'
                " NOT NULL DEFAULT 'approved'"
            )
            cur.execute('ALTER TABLE "Resume" ADD COLUMN IF NOT EXISTS "formatHash" text')
            cur.execute('ALTER TABLE "Resume" ADD COLUMN IF NOT EXISTS "originalFile" bytea')
            cur.execute(
                'ALTER TABLE "Resume" ADD COLUMN IF NOT EXISTS "originalFilename" text'
            )
            cur.execute(
                'ALTER TABLE "Resume" ADD COLUMN IF NOT EXISTS "originalContentType" text'
            )
        conn.commit()
    _resume_columns_ready = True


#: Guard so the additive ``ApprovalRequest`` execution column is only ensured
#: once per worker process (see ``ensure_approval_columns``).
_approval_columns_ready = False


def ensure_approval_columns() -> None:
    """Idempotently add the additive ``ApprovalRequest`` columns on first use.

    ``executedAt`` (MV-approval-modal-010) is the idempotency marker for the
    ``/approvals/{id}/execute`` side-effect: the endpoint claims an approved
    request by conditionally stamping this column exactly once, so a
    double-submit/retry cannot fire the same real Gmail send twice.

    ``executionCompletedAt`` (CRITICAL-4) is the other half of that claim.
    ``executedAt`` is stamped BEFORE the side-effect runs, so on its own it
    cannot distinguish "the send finished" from "the process died mid-send and
    never got to release the claim" — and nothing reconciled the second case,
    so the row read as executed forever while nothing had been sent. This
    column is stamped only once the side-effect provably returned, making an
    interrupted execution a visible state instead of a silent lie. See
    ``app.repositories.approval.execution_state``.

    ``resolvedByUserId`` / ``resolvedFromIp`` (GOLD-MASTER-V2 §15 Defect 1)
    persist who resolved an approval, and from what client IP, on the row
    itself — independent of ``AdminAuditLog`` or access logs, which rotate.
    Populated by ``ApprovalRepository._resolve()`` alongside the existing
    ``resolvedAt`` stamp.

    Introduced by lazy DDL (ADR-TR-1 — there is no migration runner),
    mirroring ``ensure_resume_columns``.

    ``ADD COLUMN ...`` with no default is a metadata-only change on
    PostgreSQL (existing rows read ``NULL`` = "not set"), so it is fast and
    safe on the production ``ApprovalRequest`` table and backfills the shared test
    schema — fully backward compatible; the ``ApprovalStatus`` enum is untouched. A
    transaction-scoped advisory lock serializes concurrent first-hit callers so the
    DDL cannot race; ``TRUNCATE`` never drops columns, so this survives teardown.
    """
    global _approval_columns_ready
    if _approval_columns_ready:
        return
    _managed_columns = (
        "executedAt",
        "executionCompletedAt",
        "resolvedByUserId",
        "resolvedFromIp",
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTERs when every
            # managed column already exists (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'ApprovalRequest'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                (list(_managed_columns),),
            )
            row = cur.fetchone()
            if row and row[0] == len(_managed_columns):
                _approval_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240725,))
            cur.execute(
                'ALTER TABLE "ApprovalRequest" '
                'ADD COLUMN IF NOT EXISTS "executedAt" timestamptz'
            )
            cur.execute(
                'ALTER TABLE "ApprovalRequest" '
                'ADD COLUMN IF NOT EXISTS "executionCompletedAt" timestamptz'
            )
            cur.execute(
                'ALTER TABLE "ApprovalRequest" '
                'ADD COLUMN IF NOT EXISTS "resolvedByUserId" text'
            )
            cur.execute(
                'ALTER TABLE "ApprovalRequest" '
                'ADD COLUMN IF NOT EXISTS "resolvedFromIp" text'
            )
        conn.commit()
    _approval_columns_ready = True


#: Guard so the additive ``Job`` dedup columns are only ensured once per
#: worker process (see ``ensure_job_dedup_columns``).
_job_dedup_columns_ready = False


def ensure_job_dedup_columns() -> None:
    """Idempotently add the additive ``Job.dedupHash`` and ``Job.contentHash``
    columns on first use.

    ``dedupHash`` (Phase 2A — NULL sourceUrl dedup fix) is a composite hash of
    (userId + title + company + location) that closes the PostgreSQL NULL != NULL
    gap in the ``@@unique([userId, sourceUrl])`` constraint.  Jobs that share
    the same ``dedupHash`` are considered duplicates and are upserted instead of
    inserted.

    ``contentHash`` (Phase 2A — secondary dedup signal) is sha256 of the first
    500 characters of the job description.  It catches near-duplicate postings
    that may have slightly different titles, companies, or locations.

    ``ADD COLUMN ... text`` with no default is a metadata-only change on
    PostgreSQL (existing rows read ``NULL`` = no hash yet computed), so it is
    fast and safe on the production ``Job`` table and backfills the shared test
    schema — fully backward compatible.  A transaction-scoped advisory lock
    serializes concurrent first-hit callers so the DDL cannot race; ``TRUNCATE``
    never drops columns, so this survives teardown.  Introduced by lazy DDL
    (ADR-TR-1 — there is no migration runner), mirroring
    ``ensure_resume_columns``.
    """
    global _job_dedup_columns_ready
    if _job_dedup_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Job'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('dedupHash', 'contentHash')"
            )
            row = cur.fetchone()
            if row and row[0] == 2:
                _job_dedup_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240730,))
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "dedupHash" text'
            )
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "contentHash" text'
            )
        conn.commit()
    _job_dedup_columns_ready = True


#: Guard so the additive ``Job.lastSeenAt`` column is only ensured once per
#: worker process (see ``ensure_job_last_seen_column``).
_job_last_seen_column_ready = False


def ensure_job_last_seen_column() -> None:
    """Idempotently add the additive ``Job.lastSeenAt`` column on first use.

    BLOCKER-006. ``lastSeenAt`` is the wall-clock time a discovery sweep last
    found this listing STILL PUBLISHED at its source. It is written only by
    ``JobRepository.create`` — the single entry point every adapter's results
    flow through — so it means exactly one thing and nothing else.

    It exists because the active feed previously used the POSTING DATE
    (``postedAt``) as a proxy for "this listing is dead", which is invalid for
    the ATS-native boards this product sources from: those APIs publish only
    roles that are still open, so a role first posted 187 days ago and
    returned by the board 40 seconds ago is fully applicable. Using posting
    age hid every such role and emptied a paying user's feed.

    ``updatedAt`` cannot stand in for this: it is also bumped by user actions
    (save toggle, status advance, fit-score writes), so a job the user merely
    saved would look "re-confirmed at source" when nothing of the sort
    happened. ``lastSeenAt`` is written by the sourcing path alone.

    BACKFILL: none, deliberately. ``ADD COLUMN IF NOT EXISTS`` with no DEFAULT
    is metadata-only on PostgreSQL, so every pre-existing row reads NULL.
    NULL means "we have never recorded a sighting", and
    ``active_feed._liveness_date`` falls back to ``updatedAt`` then
    ``createdAt`` for those rows — both are honest lower bounds on when the
    system last had contact with the row, and both are superseded the first
    time the 30-minute sweep re-confirms the listing. Writing a backfill
    UPDATE would instead assert a sighting that never happened.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serializes concurrent first-hit callers
    so the DDL cannot race; ``TRUNCATE`` never drops columns, so the
    process-wide latch survives test teardown. Lazy DDL per ADR-TR-1 (there is
    no migration runner in this repo) — mirrors ``ensure_job_dedup_columns``.

    MUST be called by EVERY path that reads or writes the column before the
    statement that names it — a path that skipped the equivalent call for
    ``contentHash`` raised ``psycopg2.UndefinedColumn`` -> HTTP 500 on first
    use (WIP-BRANCH-AUDIT-2026-07-29 blocker #2).
    """
    global _job_last_seen_column_ready
    if _job_last_seen_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Job'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'lastSeenAt'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _job_last_seen_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260801,))
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "lastSeenAt" timestamptz'
            )
        conn.commit()
    _job_last_seen_column_ready = True


#: Guard so the additive ``StoryEntry`` dedup column is only ensured once per
#: worker process (see ``ensure_story_dedup_column``).
_story_dedup_column_ready = False


def ensure_story_dedup_column() -> None:
    """Idempotently add the additive ``StoryEntry.contentHash`` column on first use.

    ``contentHash`` (G-P4-STORY-DEDUP-004) is a sha256 of
    (userId + title + situation + task + action + result). Stories that share
    the same ``contentHash`` are duplicates; the repository returns the existing
    row instead of inserting another one.

    ``ADD COLUMN IF NOT EXISTS text`` with no default is a metadata-only change
    on PostgreSQL (existing rows read ``NULL`` = no hash yet computed), so it is
    fast, safe on the production table, and backfills the shared test schema.
    A transaction-scoped advisory lock serializes concurrent first-hit callers
    so the DDL cannot race; ``TRUNCATE`` never drops columns, so the
    process-wide latch survives test teardown. Lazy DDL per ADR-TR-1 (there is
    no migration runner in this repo) — mirrors ``ensure_job_dedup_columns``.

    MUST be called by EVERY repository path that reads or writes the column —
    both ``StoryRepository.create`` and ``StoryRepository.update``. An update
    path that skipped it raised ``psycopg2.UndefinedColumn`` -> HTTP 500 on the
    first ``PUT /stories/{id}`` against a schema that had never run the DDL
    (WIP-BRANCH-AUDIT-2026-07-29 blocker #2).
    """
    global _story_dedup_column_ready
    if _story_dedup_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'StoryEntry'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'contentHash'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _story_dedup_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (9380710313,))
            cur.execute(
                'ALTER TABLE "StoryEntry" '
                'ADD COLUMN IF NOT EXISTS "contentHash" text'
            )
        conn.commit()
    _story_dedup_column_ready = True


#: Guard so the additive ``StoryEntry`` archive columns are only ensured once
#: per worker process (see ``ensure_story_archive_columns``).
_story_archive_columns_ready = False


def ensure_story_archive_columns() -> None:
    """Idempotently add the additive ``StoryEntry`` merge-archive columns.

    GMV4-story-004: the bulk paraphrase de-dup sweep
    (``app.services.story_dedup_migration.merge_duplicate_stories``) used to
    ``DELETE`` the losing row of every merge. Story content is user-authored
    career history that cannot be regenerated, and the sweep is driven by a
    deliberately permissive similarity preset — an over-matching heuristic
    wired to an irreversible DELETE. These three columns replace that DELETE
    with a RECOVERABLE archive:

    * ``archivedAt`` (timestamptz) — NULL means LIVE. Set when a row is
      merged away; every live read path filters ``"archivedAt" IS NULL``.
    * ``mergedIntoId`` (text) — the surviving row's id, so an archived row
      always points at where its content went.
    * ``mergeSnapshot`` (jsonb) — the full pre-merge capture the risk
      officer requires: the SURVIVOR's content as it stood *before* being
      overwritten (the only part of a merge that is otherwise destroyed —
      the loser's own columns are left untouched in place), plus the
      similarity signals, thresholds, batch id and executing account that
      produced the decision. This is what makes ``restore_merged_stories``
      able to reverse a merge exactly.

    BACKFILL: none is required, and none is performed — by construction.
    ``ADD COLUMN IF NOT EXISTS`` with no DEFAULT is a metadata-only change on
    PostgreSQL; every pre-existing row therefore reads ``archivedAt = NULL``,
    which is precisely the correct value for a row that has never been merged
    away, and every reader treats NULL as live. Writing a backfill UPDATE
    would rewrite every row to the value it already has.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serializes concurrent first-hit callers
    so the DDL cannot race; ``TRUNCATE`` never drops columns, so the
    process-wide latch survives test teardown. Lazy DDL per ADR-TR-1 (there
    is no migration runner in this repo) — mirrors
    ``ensure_story_dedup_column``.

    MUST be called by EVERY path that reads or writes these columns, before
    the statement that names them — a path that skipped the equivalent call
    for ``contentHash`` raised ``psycopg2.UndefinedColumn`` -> HTTP 500 on
    first use (WIP-BRANCH-AUDIT-2026-07-29 blocker #2).
    """
    global _story_archive_columns_ready
    if _story_archive_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'StoryEntry'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('archivedAt', 'mergedIntoId', 'mergeSnapshot')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
                _story_archive_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (9380710314,))
            cur.execute(
                'ALTER TABLE "StoryEntry" '
                'ADD COLUMN IF NOT EXISTS "archivedAt" timestamptz'
            )
            cur.execute(
                'ALTER TABLE "StoryEntry" '
                'ADD COLUMN IF NOT EXISTS "mergedIntoId" text'
            )
            cur.execute(
                'ALTER TABLE "StoryEntry" '
                'ADD COLUMN IF NOT EXISTS "mergeSnapshot" jsonb'
            )
        conn.commit()
    _story_archive_columns_ready = True


#: Guard so the additive ``StoryEntry.achievementKey`` column + its partial
#: unique index are only ensured once per worker process.
_story_achievement_column_ready = False


def ensure_story_achievement_column() -> None:
    """Idempotently add ``StoryEntry.achievementKey`` and its uniqueness index.

    STORY-BANK-REBUILD-2026-08-02. Audited live: 43 story rows describing ~10
    distinct achievements. The extractor had no stable identity for "which
    achievement is this story about", so every re-run's reworded re-telling
    inserted a new row (the exact sha256 ``contentHash`` is defeated by one
    changed word, and the fuzzy paraphrase preset needs title Jaccard >= 0.70
    while the real duplicates' MEDIAN is 0.333).

    ``achievementKey`` (``app.services.resume_bullets.achievement_key``) is a
    per-user sha256 of the résumé bullet the story is drawn from, so two
    stories about the same achievement share a key however far their prose
    drifts, and dedup becomes an exact lookup instead of a heuristic.

    The PARTIAL UNIQUE INDEX is what makes that a guarantee rather than a
    convention: no code path — not a future router, not a bulk import, not a
    concurrent double-run of the extractor — can create a second LIVE row for
    one achievement. It is deliberately partial on BOTH predicates:

    * ``"achievementKey" IS NOT NULL`` — pre-existing rows and hand-authored
      stories created through ``POST /stories`` carry no key and are exempt;
      the index constrains only source-grounded rows.
    * ``"archivedAt" IS NULL`` — an archived row is a merge/clear loser held
      for recovery (``ensure_story_archive_columns``). It must NOT block a
      fresh live row for the same achievement, otherwise clearing the bank
      and regenerating it would deadlock against its own backups.

    ``ADD COLUMN IF NOT EXISTS text`` with no default is a metadata-only
    change on PostgreSQL; ``CREATE UNIQUE INDEX IF NOT EXISTS`` over an
    all-NULL column builds instantly. A transaction-scoped advisory lock
    serializes concurrent first-hit callers so the DDL cannot race, and
    ``TRUNCATE`` never drops columns or indexes, so the process-wide latch
    survives test teardown. Lazy DDL per ADR-TR-1 — mirrors
    ``ensure_story_dedup_column``.

    MUST be called by every path that reads or writes the column, before the
    statement that names it (skipping it is WIP-BRANCH-AUDIT-2026-07-29
    blocker #2's failure mode: ``UndefinedColumn`` -> HTTP 500 on first use).
    """
    global _story_achievement_column_ready
    if _story_achievement_column_ready:
        return
    # The partial index predicates ``"archivedAt"``, so that column must
    # already exist — ensure it here rather than relying on call ordering.
    ensure_story_archive_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'StoryEntry'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'achievementKey'"
            )
            row = cur.fetchone()
            has_column = bool(row and row[0] == 1)
            if not has_column:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (9380710315,))
                cur.execute(
                    'ALTER TABLE "StoryEntry" '
                    'ADD COLUMN IF NOT EXISTS "achievementKey" text'
                )
            # The index is ensured on EVERY first-hit (not only when the
            # column was just created), so a schema that already has the
            # column from an earlier deploy still acquires the guarantee.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (9380710316,))
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS'
                ' "StoryEntry_userId_achievementKey_live_key"'
                ' ON "StoryEntry" ("userId", "achievementKey")'
                ' WHERE "achievementKey" IS NOT NULL AND "archivedAt" IS NULL'
            )
        conn.commit()
    _story_achievement_column_ready = True


#: Guard so the additive ``Job.coverFailureClearedAt`` column is only ensured
#: once per worker process (see ``ensure_job_cover_suppression_column``).
_job_cover_suppression_column_ready = False


def ensure_job_cover_suppression_column() -> None:
    """Idempotently add the additive ``Job.coverFailureClearedAt`` column.

    ML-W-12: the board-sweep cover-failure backoff (RT-007,
    ``app.workers.board_sweep``) permanently excludes a job from
    ``_next_target`` once it accrues ``max_cover_failures()`` failed
    coverLetter ``AgentRun`` rows inside ``cover_failure_window_hours()`` —
    correct for a job whose letter is genuinely unfabricatable, but with no
    way to clear early. When the failures were actually caused by a pipeline
    bug that has since been fixed and deployed, every job that failed under
    the old broken code stays wedged for the rest of the window: it is
    excluded from selection, so it can never earn the new success that would
    otherwise clear it.

    ``coverFailureClearedAt`` is the additive escape hatch: ops (via
    ``scripts/clear_cover_suppression.py``) stamps ``NOW()`` on a currently-
    suppressed job, and the failure-count queries only count failures AFTER
    this timestamp (or after the job's own last successful coverLetter
    completion, whichever is later) — the historical ``AgentRun`` audit trail
    is never rewritten, only what counts going forward changes.

    ``ADD COLUMN ... timestamptz`` with no default is a metadata-only change
    on PostgreSQL (existing rows read NULL = never cleared), so it is fast and
    safe on the production ``Job`` table and backfills the shared test schema.
    Lazy DDL per ADR-TR-1 (there is no migration runner); mirrors
    ``ensure_job_dedup_columns``.
    """
    global _job_cover_suppression_column_ready
    if _job_cover_suppression_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Job'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'coverFailureClearedAt'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _job_cover_suppression_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240740,))
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "coverFailureClearedAt" timestamptz'
            )
        conn.commit()
    _job_cover_suppression_column_ready = True


#: Name of the partial unique index enforcing "one ACTIVE Application per
#: (userId, jobId)" — see ``ensure_application_unique_active_index``.
APPLICATION_UNIQUE_ACTIVE_INDEX = "Application_user_job_active_key"

#: Statuses that count as an "active" (currently-being-pursued) application
#: for the one-per-job invariant below. Mirrors the RT-004 promotion-guard
#: predicate in ``app.routers.applications`` (``submit_application``,
#: ``move_application``) exactly — 'draft' rows are letter-version history
#: (many allowed per job) and 'rejected'/'withdrawn' are terminal (a user may
#: re-apply after either, so multiple closed rows per job are legitimate).
APPLICATION_ACTIVE_STATUSES = ("submitted", "screening", "interview", "offer")

#: Guard so the additive Application unique-active-per-job index is only
#: ensured once per worker process THIS run has actually created it (see
#: ``ensure_application_unique_active_index``). Deliberately NOT set when
#: creation is skipped for existing violations, so a later call (once ops
#: cleans them up) can still succeed without requiring a worker restart.
_application_unique_active_index_ready = False


def ensure_application_unique_active_index() -> None:
    """Idempotently add a partial UNIQUE index enforcing one ACTIVE
    ``Application`` per (``userId``, ``jobId``) on first use.

    NTH-R10 (wave35-sonnet-review-verdict.json): the RT-004 promotion guards
    in ``app.routers.applications`` (``submit_application``,
    ``move_application``) are check-then-act — each SELECTs for an existing
    active application for the job, then promotes its OWN draft, with no
    atomicity between the two. Two concurrent promotions of two DIFFERENT
    draft rows for the SAME job can both pass the SELECT (each reads before
    the other commits) and both pass their own single-row compare-and-swap
    (different rows, both starting 'draft'), minting two active applications
    for one job — the cross-row version of the bug the per-row CAS closed.
    Only the database itself can really close this, hence the partial
    unique index; the callers additionally catch the resulting
    ``UniqueViolation`` and map it to the identical 409 the check-then-act
    guard already returns, so the client contract is unchanged.

    LIVE EVIDENCE (2026-07-29, read-only probe against the production
    ``aether`` schema, ``uat/reports/evidence/models-live/`` — see the
    ML-W-17 fix commit): 2 (userId, jobId) pairs already violate this
    invariant (21 extra rows total — the same live "11+ cards for one job"
    duplication RT-004's board-dedup was built to tolerate). Creating the
    index unconditionally would raise ``UniqueViolation`` on the very first
    call in production and 500 an unrelated request. So: before attempting
    creation, this checks for existing violations and, if any are found,
    logs an honest WARNING (with the violation count) and returns WITHOUT
    creating the index or failing the request — the existing check-then-act
    409 guard remains the only protection for those jobs until ops runs a
    cleanup (e.g. moving all-but-the-most-advanced duplicate to
    'withdrawn'), at which point a later call in this (or a fresh) worker
    process creates the index for real.

    ``CREATE UNIQUE INDEX IF NOT EXISTS`` is additive (ADR-TR-1 lazy DDL, no
    migration runner in this repo) and a transaction-scoped advisory lock
    serializes concurrent first-hit callers so the DDL cannot race, mirroring
    ``ensure_job_dedup_columns``. ``TRUNCATE`` never drops indexes, so this
    survives test-suite teardown.
    """
    global _application_unique_active_index_ready
    if _application_unique_active_index_ready:
        return
    active_statuses_sql = ",".join(f"'{s}'" for s in APPLICATION_ACTIVE_STATUSES)
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip everything below once the index
            # already exists (production after cleanup, or a warm process).
            cur.execute(
                "SELECT 1 FROM pg_indexes"
                " WHERE schemaname = ANY(current_schemas(false))"
                " AND tablename = 'Application'"
                " AND indexname = %s",
                (APPLICATION_UNIQUE_ACTIVE_INDEX,),
            )
            if cur.fetchone() is not None:
                _application_unique_active_index_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240751,))
            # Re-check inside the lock — a concurrent first-hit caller may
            # have already created it while this one waited.
            cur.execute(
                "SELECT 1 FROM pg_indexes"
                " WHERE schemaname = ANY(current_schemas(false))"
                " AND tablename = 'Application'"
                " AND indexname = %s",
                (APPLICATION_UNIQUE_ACTIVE_INDEX,),
            )
            if cur.fetchone() is not None:
                conn.commit()
                _application_unique_active_index_ready = True
                return
            cur.execute(
                f'SELECT count(*) FROM ('
                f'  SELECT 1 FROM "Application"'
                f'  WHERE "status" IN ({active_statuses_sql})'
                f'  GROUP BY "userId", "jobId" HAVING count(*) > 1'
                f") violations"
            )
            violation_groups = cur.fetchone()[0]
            if violation_groups:
                logger.warning(
                    "ensure_application_unique_active_index: %d (userId, jobId) "
                    "pair(s) already violate the one-active-application-per-job "
                    "invariant -- SKIPPING index creation so this request does "
                    "not fail. The check-then-act 409 guard in "
                    "app.routers.applications remains the only protection for "
                    "those jobs until the duplicates are cleaned up (NTH-R10).",
                    violation_groups,
                )
                conn.commit()
                return
            cur.execute(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "{APPLICATION_UNIQUE_ACTIVE_INDEX}"'
                f' ON "Application" ("userId", "jobId")'
                f'  WHERE "status" IN ({active_statuses_sql})'
            )
        conn.commit()
    _application_unique_active_index_ready = True


#: Guard so the additive ``Job`` apply-recipient columns are only ensured once
#: per worker process (see ``ensure_job_apply_contact_columns``).
_job_apply_contact_columns_ready = False


def ensure_job_apply_contact_columns() -> None:
    """Idempotently add the additive ``Job`` apply-recipient columns (W-SUB).

    Until this landed, ``Job`` carried NO employer/recruiter/apply address of
    any kind, so the "submission" half of the product had literally nowhere to
    send an application — which is why ``POST /approvals/{id}/execute``
    answered ``{"status": "executed"}`` without transmitting anything and 86
    ``Application`` rows read "submitted" to the user while nothing had ever
    left the system.

    * ``applyEmail`` (text) — the recipient an application may be emailed to.
      Written ONLY from real posting data (see
      ``app.services.application_submission.derive_apply_recipient``): today
      the only genuine source in this schema is an address published in the
      posting's own ``description``. NULL means "no genuine recipient is
      known", which makes the job NOT auto-submittable — the honest state, and
      the state of every job in production at the time of writing (a live
      probe found 0 of 66 job descriptions containing a ``mailto:``).
    * ``applyEmailSource`` (text) — provenance of that address
      (``description_mailto`` / ``description_text``), so the UI and any audit
      can say WHERE the address came from rather than asserting it.
    * ``applyContactCheckedAt`` (timestamptz) — when derivation last ran. NULL
      means "never looked", which is DISTINCT from "looked and found nothing"
      (checked + ``applyEmail IS NULL``). Without this column a re-check could
      not tell those apart, and the UI would have to guess.

    BACKFILL: performed by derivation, never by assertion. ``ADD COLUMN IF NOT
    EXISTS`` with no DEFAULT is a metadata-only change on PostgreSQL, so every
    pre-existing row reads NULL = "never checked". The real backfill is
    ``apps/api/scripts/backfill_job_apply_email.py``, which runs the SAME
    derivation over stored descriptions and writes only what it can actually
    find. There is deliberately no heuristic "guess the company's careers
    address" fallback: inventing ``careers@<company>.com`` would be fabricated
    data pointed at a real third party.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serializes concurrent first-hit callers
    so the DDL cannot race; ``TRUNCATE`` never drops columns, so the
    process-wide latch survives test teardown. Lazy DDL per ADR-TR-1 (there is
    no migration runner in this repo) — mirrors ``ensure_job_last_seen_column``.

    MUST be called by EVERY path that reads or writes these columns, before
    the statement that names them.
    """
    global _job_apply_contact_columns_ready
    if _job_apply_contact_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Job'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('applyEmail', 'applyEmailSource',"
                " 'applyContactCheckedAt')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
                _job_apply_contact_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260802,))
            cur.execute('ALTER TABLE "Job" ADD COLUMN IF NOT EXISTS "applyEmail" text')
            cur.execute(
                'ALTER TABLE "Job" ADD COLUMN IF NOT EXISTS "applyEmailSource" text'
            )
            cur.execute(
                'ALTER TABLE "Job" '
                'ADD COLUMN IF NOT EXISTS "applyContactCheckedAt" timestamptz'
            )
        conn.commit()
    _job_apply_contact_columns_ready = True


#: Guard so the additive ``Application`` transmission columns are only ensured
#: once per worker process (see ``ensure_application_transmission_columns``).
_application_transmission_columns_ready = False


def ensure_application_transmission_columns() -> None:
    """Idempotently add the additive ``Application`` transmission columns (W-SUB).

    ``Application.status = 'submitted'`` has always meant "the user (or an
    agent) marked this application as submitted" — it has NEVER meant "Aether
    transmitted it", because nothing in the product could transmit anything.
    These columns are what makes the difference RECORDABLE, so the UI can stop
    telling the user something false without deleting or rewriting a single
    historical row:

    * ``transmittedAt`` (timestamptz) — NULL means Aether never sent this
      application anywhere. That is the CORRECT value for all 86 pre-existing
      'submitted' rows, and it is why no backfill UPDATE is performed: the
      metadata-only ``ADD COLUMN`` already gives every historical row its true
      value. Writing anything else would be the fabrication this work exists
      to remove.
    * ``transmittedTo`` (text) — the exact recipient address the message went
      to.
    * ``transmissionChannel`` (text) — how it left ('gmail').
    * ``transmissionRef`` (text) — the provider's message id, so a claim of
      delivery is checkable against the user's own Sent folder rather than
      being taken on trust.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite, and NOT a new
    ``ApplicationStatus`` enum member (the enum is referenced by every board
    query, the sankey and the stage-transition matrix; the honest distinction
    is a property of the row, not a new kanban column). A transaction-scoped
    advisory lock serializes concurrent first-hit callers so the DDL cannot
    race; ``TRUNCATE`` never drops columns, so the process-wide latch survives
    test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes these columns, before
    the statement that names them.
    """
    global _application_transmission_columns_ready
    if _application_transmission_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('transmittedAt', 'transmittedTo',"
                " 'transmissionChannel', 'transmissionRef')"
            )
            row = cur.fetchone()
            if row and row[0] == 4:
                _application_transmission_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260803,))
            for column, coltype in (
                ("transmittedAt", "timestamptz"),
                ("transmittedTo", "text"),
                ("transmissionChannel", "text"),
                ("transmissionRef", "text"),
            ):
                cur.execute(
                    f'ALTER TABLE "Application" '
                    f'ADD COLUMN IF NOT EXISTS "{column}" {coltype}'
                )
        conn.commit()
    _application_transmission_columns_ready = True


#: Guard so the additive ``Application.applyChannel`` column is only ensured
#: once per worker process (see ``ensure_application_apply_channel_column``).
_application_apply_channel_column_ready = False


def ensure_application_apply_channel_column() -> None:
    """Idempotently add the additive ``Application.applyChannel`` column (U5a).

    ``applyChannel`` (text, nullable) records HOW this application can actually
    be submitted — ``ashby``/``greenhouse``/``lever``/``smartrecruiters``
    (a first-class ATS form), ``email`` (the existing W-SUB Gmail path),
    ``generic`` (a best-effort employer form), ``seek-manual`` (never
    automated — ADR-SEEK-V3) or ``unknown``.

    NULL is the CORRECT, honest value for every pre-existing row: nothing had
    ever resolved a channel for them, so no backfill UPDATE is performed here
    — the metadata-only ``ADD COLUMN`` already gives each historical row its
    true value, and the resolver fills it in the first time it actually looks
    at that posting. Writing a guessed channel into history would be exactly
    the fabrication this project refuses.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serializes concurrent first-hit callers so
    the DDL cannot race; ``TRUNCATE`` never drops columns, so the process-wide
    latch survives test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes this column, before the
    statement that names it.
    """
    global _application_apply_channel_column_ready
    if _application_apply_channel_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'applyChannel'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _application_apply_channel_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260805,))
            cur.execute(
                'ALTER TABLE "Application" '
                'ADD COLUMN IF NOT EXISTS "applyChannel" text'
            )
        conn.commit()
    _application_apply_channel_column_ready = True


#: Guard so the additive ``Application`` manual-step columns are only ensured
#: once per worker process (see ``ensure_application_manual_step_columns``).
_application_manual_step_columns_ready = False


def ensure_application_manual_step_columns() -> None:
    """Idempotently add the additive ``Application`` manual-step columns (U5b).

    The NO-PREPARED-ONLY invariant says an approved application must end up
    either TRANSMITTED or in an HONEST, ACTIONABLE state. These columns are
    that second outcome, recorded on the row so the UI can show the user the
    real obstacle instead of leaving the application silently "prepared":

    * ``manualStepReason`` (text) — machine code: ``unknown_required_question``
      (a required question no stored profile answer can honestly answer),
      ``captcha``, ``login_wall``, ``no_automatable_channel`` …
    * ``manualStepDetail`` (text) — the REAL question text / obstacle copied
      verbatim off the employer's page, so the user reads the actual words
      they need to answer rather than a paraphrase.
    * ``manualStepAt`` (timestamptz) — when the attempt hit the obstacle.

    NULL everywhere is the correct value for every pre-existing row (no
    attempt was ever made against them), so no backfill UPDATE is performed.
    A manual step NEVER writes ``transmittedAt``: the two states are mutually
    exclusive and a manual step means nothing was sent.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serializes concurrent first-hit callers so
    the DDL cannot race; ``TRUNCATE`` never drops columns, so the process-wide
    latch survives test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes these columns, before the
    statement that names them.
    """
    global _application_manual_step_columns_ready
    if _application_manual_step_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('manualStepReason', 'manualStepDetail',"
                " 'manualStepAt')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
                _application_manual_step_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260806,))
            for column, coltype in (
                ("manualStepReason", "text"),
                ("manualStepDetail", "text"),
                ("manualStepAt", "timestamptz"),
            ):
                cur.execute(
                    f'ALTER TABLE "Application" '
                    f'ADD COLUMN IF NOT EXISTS "{column}" {coltype}'
                )
        conn.commit()
    _application_manual_step_columns_ready = True


#: Guard so the additive ``Application`` submission-truth columns are only
#: ensured once per worker process (see
#: ``ensure_application_submission_truth_columns``).
_application_submission_truth_columns_ready = False


def ensure_application_submission_truth_columns() -> None:
    """Idempotently add the additive ``Application`` submission-truth columns (U5d).

    THE ROWS THIS EXISTS FOR (production census 2026-08-14T07:35:45Z,
    ``uat/reports/evidence/agents-uplift/u5d/CENSUS.json``): 346 rows assert
    ``status = 'submitted'`` while **0 of 606 rows in the whole database has
    ever carried a ``transmittedAt``**. Those 346 are claims of a submission
    with no transmission evidence behind them — created before U5d by a
    bookkeeping-only path that said "Submitted your application …" over a write
    that transmitted nothing.

    * ``submissionTruthState`` (text) — an HONEST reclassification of such a
      row (``recorded_transmission_unverified``). NULL means "never
      reclassified", which is the correct value for every row that either
      carries real transmission evidence or was never claimed as submitted.
    * ``submissionTruthAt`` (timestamptz) — when the remediation stamped it,
      so the reclassification is itself auditable.

    ADDITIVE REMEDIATION, deliberately: the backfill that fills these
    (``app.services.submission_truth.backfill_unverified_submissions``) NEVER
    rewrites ``Application.status`` and NEVER deletes a row. ``status`` is the
    user's own tracker data — "I applied to this" is a true statement about
    what the USER did even when Aether transmitted nothing — so the fix is to
    ADD the missing truth beside it, not to overwrite the user's history.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite, and NOT a new
    ``ApplicationStatus`` enum member (the enum is read by every board query,
    the sankey and the stage-transition matrix). A transaction-scoped advisory
    lock serializes concurrent first-hit callers so the DDL cannot race;
    ``TRUNCATE`` never drops columns, so the process-wide latch survives test
    teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes these columns, before the
    statement that names them.
    """
    global _application_submission_truth_columns_ready
    if _application_submission_truth_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('submissionTruthState', 'submissionTruthAt')"
            )
            row = cur.fetchone()
            if row and row[0] == 2:
                _application_submission_truth_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260807,))
            for column, coltype in (
                ("submissionTruthState", "text"),
                ("submissionTruthAt", "timestamptz"),
            ):
                cur.execute(
                    f'ALTER TABLE "Application" '
                    f'ADD COLUMN IF NOT EXISTS "{column}" {coltype}'
                )
        conn.commit()
    _application_submission_truth_columns_ready = True


#: Guard so the additive ``Application.coverLetterQuality`` column is only
#: ensured once per worker process (see ``ensure_cover_letter_quality_columns``).
_cover_letter_quality_columns_ready = False


def ensure_cover_letter_quality_columns() -> None:
    """Idempotently add the additive ``Application.coverLetterQuality`` column
    (W-TAILOR-CONVERGE item 4).

    Cover letters live on the ``Application`` row (``coverLetter`` text) and
    have never carried a quality measurement of any kind — the letter was
    drafted, guarded and stored with nothing recording how good it was, so the
    Studio had no before/after to show and a reload had no score to render.

    ``coverLetterQuality`` (jsonb, NULL) holds the deterministic
    :class:`app.services.cover_letter_quality.CoverLetterQuality` breakdown of
    the SHIPPED letter plus the per-pass history behind it. NULL is the
    CORRECT, honest value for every pre-existing letter: those were generated
    before any scoring existed, so no score for them was ever measured and none
    is invented here — no backfill UPDATE is performed. Recomputing one
    retroactively would also be misleading, since it would score the stored
    text against today's evidence corpus rather than the one the letter was
    written from.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite; the
    metadata-only ``ADD COLUMN`` is fast and safe on the production table. A
    transaction-scoped advisory lock serializes concurrent first-hit callers so
    the DDL cannot race; ``TRUNCATE`` never drops columns, so the process-wide
    latch survives test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes this column, before the
    statement that names it.
    """
    global _cover_letter_quality_columns_ready
    if _cover_letter_quality_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'coverLetterQuality'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _cover_letter_quality_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260804,))
            cur.execute(
                'ALTER TABLE "Application" '
                'ADD COLUMN IF NOT EXISTS "coverLetterQuality" jsonb'
            )
        conn.commit()
    _cover_letter_quality_columns_ready = True


#: Guard so the additive submission-snapshot columns are only ensured once per
#: worker process (see ``ensure_application_submission_snapshot_columns``).
_application_submission_snapshot_columns_ready = False


def ensure_application_submission_snapshot_columns() -> None:
    """Idempotently add the additive ``Application`` submit-time snapshot columns
    (U-AX instrumentation item 1, absorbing the original U4 plan).

    ``Application.status = 'submitted'`` records THAT an application was sent.
    Nothing recorded what was sent, or how good it was at that instant — so a
    résumé scored 71 at tailor time and hand-edited down to 55 before
    submission was indistinguishable from one submitted at 71, and no cohort
    analysis of "did higher-rigor applications convert better?" was possible
    even in principle. These columns freeze the facts AT THE MOMENT OF SUBMIT:

    * ``atsScoreAtSubmission`` (double precision) — the job's real ATS score as
      it stood when the application left.
    * ``tailoredResumeVersionId`` (text) — WHICH résumé version was actually
      submitted (``Resume.id``), not merely the current tailored one.
    * ``dimensionScoresAtSubmission`` (jsonb) — the 10 fit-radar dimensions
      measured by the SAME deterministic engine the Job Discovery panel renders
      (``routers/jobs.py::_build_insights``), so the >80% floor can be checked
      against what was really submitted.
    * ``policyTierAtSubmission`` (text) — the rigor tier the agents were
      operating at, which is what makes "applications under each policy tier"
      a measurable cohort rather than a claim.

    NULL is the CORRECT, honest value for every pre-existing row: none of these
    were measured at those submissions, so NO backfill UPDATE is performed.
    Reconstructing them today would score a historical submission against
    today's résumé and today's engine — a fabricated number wearing a
    historical timestamp.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serialises concurrent first-hit callers so
    the DDL cannot race; ``TRUNCATE`` never drops columns, so the process-wide
    latch survives test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes these columns, before the
    statement that names them.
    """
    global _application_submission_snapshot_columns_ready
    if _application_submission_snapshot_columns_ready:
        return
    columns = (
        ("atsScoreAtSubmission", "double precision"),
        ("tailoredResumeVersionId", "text"),
        ("dimensionScoresAtSubmission", "jsonb"),
        ("policyTierAtSubmission", "text"),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                ([name for name, _type in columns],),
            )
            row = cur.fetchone()
            if row and row[0] == len(columns):
                _application_submission_snapshot_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260805,))
            for column, coltype in columns:
                cur.execute(
                    f'ALTER TABLE "Application" '
                    f'ADD COLUMN IF NOT EXISTS "{column}" {coltype}'
                )
        conn.commit()
    _application_submission_snapshot_columns_ready = True


#: Guard so the additive ``Application.manualStepQuestions`` column is only
#: ensured once per worker process (see
#: ``ensure_application_manual_step_question_column``).
_application_manual_step_question_column_ready = False


def ensure_application_manual_step_question_column() -> None:
    """Idempotently add the additive ``Application.manualStepQuestions`` column
    (U5d-3, ADR-SUB-AUTON-1 Pillar 4a).

    U5b already persists a manual step's REASON and a human-readable DETAIL
    string. That string is enough to TELL the user what blocked the
    application; it is not enough to let them ANSWER it inside Aether, which is
    the whole of Pillar 4a: *"UNKNOWN QUESTION → rendered NATIVELY in the card
    (question text + typed input extracted from the form)"*. Rendering an input
    needs the question's STRUCTURE — its field name, the employer's verbatim
    label, the control kind (text / textarea / select / radio), its options and
    its sensitivity class — and re-deriving that by splitting the detail string
    on "; " would be guesswork about the employer's own form.

    ``manualStepQuestions`` (jsonb, NULL) is that structure, exactly as the
    apply-executor parsed it off the real page. NULL is the CORRECT, honest
    value for every pre-existing row and for every manual step that is not a
    question at all (a CAPTCHA, a login wall, an unresolvable channel) — those
    have no question to render, so nothing is invented for them and NO backfill
    UPDATE is performed. A row blocked by a question BEFORE this column existed
    keeps its detail string and renders the pre-U5d-3 control, which is the
    truthful degradation: we did not capture its structure, so we do not
    pretend to have it.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serialises concurrent first-hit callers so
    the DDL cannot race; ``TRUNCATE`` never drops columns, so the process-wide
    latch survives test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes this column, before the
    statement that names it.
    """
    global _application_manual_step_question_column_ready
    if _application_manual_step_question_column_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'manualStepQuestions'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _application_manual_step_question_column_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260808,))
            cur.execute(
                'ALTER TABLE "Application" '
                'ADD COLUMN IF NOT EXISTS "manualStepQuestions" jsonb'
            )
        conn.commit()
    _application_manual_step_question_column_ready = True


#: Guard so the additive SUB-006 apply-resolution columns are only ensured once
#: per worker process (see ``ensure_application_apply_resolution_columns``).
_application_apply_resolution_columns_ready = False


def ensure_application_apply_resolution_columns() -> None:
    """Idempotently add the additive ``Application`` apply-resolution columns
    (SUB-006-GH-CANONICAL).

    WHY THEY EXIST. 99/512 production applications store the EMPLOYER's own
    ``?gh_jid=`` page as their apply URL, and that page hosts no application
    form at all (live probe 2026-08-17: 200, 700,675 bytes, zero ``<form>``
    elements — ``uat/reports/evidence/models-live/sub-006-gh-canonical/
    live-probe-2026-08-17.json``). The apply engine now resolves such a posting
    to the canonical Greenhouse ``embed/job_app`` form before it opens a
    browser. That means the URL a submission was actually driven against is no
    longer the URL the user sees on the posting — a substitution, and every
    substitution this product makes on a user's behalf is DISCLOSED rather than
    silently performed.

    * ``applyResolvedFrom`` (text) — the posting URL as stored on the Job row.
    * ``applyResolvedUrl`` (text) — the VERIFIED form URL Aether opened
      instead (verified means: fetched, and a real form was found on it).
    * ``applyResolvedAt`` (timestamptz) — when the resolution was made.

    NULL is the correct, honest value for every row whose apply URL was never
    substituted — which is every pre-existing row — so NO backfill is
    performed.

    Additive only — no DROP, no ALTER TYPE, no DEFAULT rewrite. A
    transaction-scoped advisory lock serialises concurrent first-hit callers so
    the DDL cannot race; ``TRUNCATE`` never drops columns, so the process-wide
    latch survives test teardown. Lazy DDL per ADR-TR-1.

    MUST be called by EVERY path that reads or writes these columns, before the
    statement that names them.
    """
    global _application_apply_resolution_columns_ready
    if _application_apply_resolution_columns_ready:
        return
    columns = (
        ("applyResolvedFrom", "text"),
        ("applyResolvedUrl", "text"),
        ("applyResolvedAt", "timestamptz"),
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = ANY(%s)",
                ([name for name, _type in columns],),
            )
            row = cur.fetchone()
            if row and row[0] == len(columns):
                _application_apply_resolution_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260811,))
            for column, coltype in columns:
                cur.execute(
                    f'ALTER TABLE "Application" '
                    f'ADD COLUMN IF NOT EXISTS "{column}" {coltype}'
                )
        conn.commit()
    _application_apply_resolution_columns_ready = True


#: Guard so the additive ADMIN-2.0 user-lifecycle columns are only ensured once
#: per worker process (see ``ensure_user_lifecycle_columns``).
_user_lifecycle_columns_ready = False


def ensure_user_lifecycle_columns() -> None:
    """Idempotently add the additive ADMIN-2.0 lifecycle columns to ``User``.

    * ``deletedAt`` (timestamptz, NULL) — the SOFT-delete stamp behind
      ``DELETE /admin/users/{id}``. A hard delete is not an option here: every
      child table (Job, Resume, Application, AgentRun, Contact, EmailThread,
      StoryEntry, ...) cascades from ``User.id``, so a real delete would destroy
      the work the account produced AND orphan the Stripe/billing history that
      still references the customer. NULL for every pre-existing row means
      "live", so nothing changes for anyone until an admin actually deletes.
    * ``mustChangePassword`` (boolean NOT NULL DEFAULT false) — set when an admin
      CREATES an account with a generated temporary password, cleared by
      ``UserRepository.set_password`` when the user (or an admin) sets a real
      one. The default is ``false``, so every existing account is unaffected.

    ``ADD COLUMN ... NOT NULL DEFAULT false`` is a metadata-only change on
    PostgreSQL (a constant default is not rewritten across existing rows), so it
    is fast and safe on the production ``User`` table. Additive only — no DROP,
    no rename, no ALTER TYPE. Lazy DDL per ADR-TR-1 (there is no migration
    runner); the documentary mirror lives in
    ``apps/api/migrations/0029_admin2.sql``. A transaction-scoped advisory lock
    serialises concurrent first-hit callers so the DDL cannot race, and
    ``TRUNCATE`` never drops columns, so the process-wide latch survives the
    test-suite teardown.

    MUST be called by every path that reads or writes either column, before the
    statement that names it.
    """
    global _user_lifecycle_columns_ready
    if _user_lifecycle_columns_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Lock-free fast path: skip the ACCESS EXCLUSIVE ALTER once both
            # columns exist (production / warm test schema).
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'User'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('deletedAt', 'mustChangePassword')"
            )
            row = cur.fetchone()
            if row and row[0] == 2:
                _user_lifecycle_columns_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420260810,))
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "deletedAt" timestamptz'
            )
            cur.execute(
                'ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "mustChangePassword"'
                " boolean NOT NULL DEFAULT false"
            )
        conn.commit()
    _user_lifecycle_columns_ready = True
