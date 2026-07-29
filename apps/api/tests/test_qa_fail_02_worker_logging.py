"""Regression test for QA-FAIL-02 (worker logging bootstrap).

``docs/delivery/PRODUCTION-HARDENING-RUN-2026-07-29.md`` QA-FAIL-02: arq's
own CLI (``arq/cli.py``) configures ONLY the ``arq`` logger via
``logging.config.dictConfig(default_log_config(verbose))`` — that default
config has no ``root`` key, so the Python root logger stays at ``WARNING``
with no handler in the worker process. Every application
``logger.info(...)`` call outside the ``arq`` namespace was therefore
silently dropped — critically the ``admin-free-fallback`` audit marker in
``app/services/llm_client.py`` — even though arq's own INFO lines still
appeared in ``worker.log`` and made it look healthy. With
``AETHER_ASYNC_GENERATION=true`` nearly all pipeline work runs in this
worker, so ADR-ML-3's "not silent" guarantee for that feature was unmet in
production (0 matches for ``grep admin-free-fallback worker.log`` despite 4
confirmed engagements).

Fix: ``app/workers/logging_config.py`` defines ``LOG_CONFIG``, wired via
``arq ... --custom-log-dict app.workers.logging_config.LOG_CONFIG`` in
``start-worker.sh`` — arq's own equivalent of uvicorn's
``--log-config logging_config.json`` (MV-system-001). ``--custom-log-dict``
REPLACES arq's default config wholesale (arq does not merge configs), so
this dict must simultaneously (a) add an ISO-8601-timestamped INFO handler
to the ROOT logger so application-module loggers are emitted, and (b) keep
arq's OWN logger family single-emission (its own handler, propagate=False)
rather than either going silent or duplicating every arq log line.

Fully hermetic: no DB connection, no network, no live worker process
spawned. Proven by loading the REAL ``LOG_CONFIG`` dict through
``logging.config.dictConfig`` — exactly what arq's CLI does with
``--custom-log-dict`` — and formatting/emitting real ``LogRecord``s through
the resulting handlers, not by asserting on the dict shape alone.

``logging.config.dictConfig`` mutates *global* logging state, so every test
here restores the pre-test state afterwards to avoid bleeding handlers into
unrelated tests later in the same pytest session (same discipline as
``test_mv_system_001_log_timestamps.py``).
"""
from __future__ import annotations

import io
import logging
import logging.config
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
START_WORKER_SH = REPO_ROOT / "start-worker.sh"

ISO8601_UTC_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b")

_SNAPSHOT_LOGGER_NAMES = ["arq", "arq.worker", "arq.jobs", "arq.connections"]


@pytest.fixture()
def log_config() -> dict:
    from app.workers.logging_config import LOG_CONFIG

    return LOG_CONFIG


@pytest.fixture()
def apply_log_config(log_config):
    """Applies the REAL LOG_CONFIG via dictConfig — exactly what arq's
    ``--custom-log-dict`` flag does in ``arq/cli.py`` — redirecting the
    handler's stream to an in-memory buffer so emitted lines can be
    inspected, then restores every touched logger's prior state."""
    root = logging.getLogger()
    snapshot = {None: (list(root.handlers), root.level, root.disabled)}
    for name in _SNAPSHOT_LOGGER_NAMES:
        lg = logging.getLogger(name)
        snapshot[name] = (list(lg.handlers), lg.level, lg.propagate, lg.disabled)

    logging.config.dictConfig(log_config)

    # Redirect whatever handler(s) got attached to root/arq so the test can
    # capture actual emitted output instead of writing to real stderr.
    buf = io.StringIO()
    touched = {root} | {logging.getLogger(n) for n in _SNAPSHOT_LOGGER_NAMES}
    original_streams = []
    for lg in touched:
        for h in lg.handlers:
            if isinstance(h, logging.StreamHandler):
                original_streams.append((h, h.stream))
                h.stream = buf

    try:
        yield buf
    finally:
        for h, stream in original_streams:
            h.stream = stream
        handlers, level, disabled = snapshot[None]
        root.handlers = handlers
        root.level = level
        root.disabled = disabled
        for name in _SNAPSHOT_LOGGER_NAMES:
            lg = logging.getLogger(name)
            handlers, level, propagate, disabled = snapshot[name]
            lg.handlers = handlers
            lg.level = level
            lg.propagate = propagate
            lg.disabled = disabled


def test_log_config_has_root_handler_at_info(log_config):
    """Without an explicit ``root`` entry, application-module loggers
    (``logging.getLogger(__name__)`` in llm_client.py etc., which have no
    handler of their own) propagate to Python's unconfigured "handler of
    last resort" — WARNING only, no timestamp — instead of being emitted."""
    assert "root" in log_config, "no root logger configured — app-module INFO logs stay invisible"
    assert log_config["root"]["level"] == "INFO"
    assert "default" in log_config["root"]["handlers"]


def test_log_config_formatter_carries_iso8601_utc_timestamp(log_config):
    fmt = log_config["formatters"]["default"]["format"]
    assert "%(asctime)s" in fmt
    assert fmt.strip().startswith("%(asctime)sZ"), (
        f"formatter should lead with the UTC-stamped asctime so every "
        f"worker.log line is scopable by time: {fmt!r}"
    )
    assert log_config["formatters"]["default"]["datefmt"] == "%Y-%m-%dT%H:%M:%S"


def test_log_config_keeps_arq_logger_non_propagating(log_config):
    """``arq`` must own its own handler (so it keeps logging) but must NOT
    propagate to root once root also has a handler, or every arq.worker /
    arq.jobs line would print twice."""
    arq_cfg = log_config["loggers"]["arq"]
    assert arq_cfg["propagate"] is False
    assert "default" in arq_cfg["handlers"]
    assert arq_cfg["level"] == "INFO"


def test_admin_free_fallback_style_app_logger_now_emits_with_timestamp(apply_log_config):
    """Simulates the EXACT call shape of the admin-free-fallback audit
    marker (``logging.getLogger(__name__).info(...)`` in
    app/services/llm_client.py, line ~1689) with no handler of its own —
    must now reach the root handler and carry an ISO-8601 UTC timestamp.
    Before the fix this logger's effective level was WARNING (root default),
    so ``.info()`` was a silent no-op — this assertion would fail against
    arq's default (pre-fix) log config."""
    logger = logging.getLogger("app.services.llm_client")
    logger.info(
        "admin-free-fallback: OpenRouter HTTP 402 (insufficient credits) — "
        "extending the model chain with free models [%s] for prompt=%s userId=%s",
        "nvidia/nemotron-3-super-120b-a12b:free", "cover_letter", "c123",
    )
    for h in logger.handlers if logger.handlers else logging.getLogger().handlers:
        h.flush()
    output = apply_log_config.getvalue()
    assert "admin-free-fallback" in output, f"audit marker never reached the log sink: {output!r}"
    assert ISO8601_UTC_RE.search(output), f"no ISO-8601 UTC timestamp in: {output!r}"


def test_arq_worker_logger_emits_exactly_once_not_double_logged(apply_log_config):
    """Regression guard for the double-logging failure mode: once root
    gains a handler, an `arq` child logger (`arq.worker`, real name used by
    the installed arq package) must still be printed exactly once, not once
    via arq's own handler AND again via root's."""
    logging.getLogger("arq.worker").info("UNIQUE-MARKER-a1b2c3 job complete")
    for h in logging.getLogger().handlers + logging.getLogger("arq").handlers:
        h.flush()
    output = apply_log_config.getvalue()
    count = output.count("UNIQUE-MARKER-a1b2c3")
    assert count == 1, f"expected exactly 1 emission of arq's own log line, got {count}: {output!r}"


def test_start_worker_sh_wires_the_custom_log_dict():
    content = START_WORKER_SH.read_text()
    assert "--custom-log-dict app.workers.logging_config.LOG_CONFIG" in content, (
        "start-worker.sh must pass arq --custom-log-dict "
        "app.workers.logging_config.LOG_CONFIG or LOG_CONFIG above is never "
        "actually used in production and worker.log stays silent for "
        "application INFO lines"
    )
