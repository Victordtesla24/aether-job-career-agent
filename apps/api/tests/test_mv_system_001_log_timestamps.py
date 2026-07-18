"""Regression test for MV-system-001 (observability gap).

``docs/delivery/MANUAL-VERIFICATION-GAPS.json`` MV-system-001: journald was
empty for every ``aether-*`` unit *and* ``/var/log/aether/api.log`` /
``web.log`` lines carried no timestamp at all, so window-scoped forensics
("was this 5xx inside the 13:25:40-13:28:00Z test window?") was impossible.

Fix: keep the existing file-based log sink (switching to journald is a
bigger, restart-requiring infra change — see the rationale recorded in
``deploy/aether-api.service.d/logging.conf`` and
``docs/delivery/DEPLOYMENT-RUNBOOK.md``), but make every line carry an
ISO-8601 UTC timestamp:

  * API: ``apps/api/logging_config.json`` (wired via
    ``uvicorn --log-config logging_config.json`` in ``start-api.sh``).
  * Web: ``start-web.sh`` pipes ``next start``'s stdout/stderr through
    ``gawk`` to prefix a timestamp (Next.js has no built-in log-format hook).

Fully hermetic: no DB connection, no network, no live process spawned. The
"config actually parses into real timestamped log lines" claim is proven by
loading the real JSON file through ``logging.config.dictConfig`` and
formatting real `LogRecord`s with the resulting formatter objects — not by
asserting on the JSON shape alone.

``logging.config.dictConfig`` mutates *global* logging state (attaches new
handlers to the root/uvicorn loggers), so every test that calls it restores
the pre-test state via ``_restore_logging_state`` to avoid bleeding handlers
into unrelated tests later in the same pytest session.
"""
from __future__ import annotations

import json
import logging
import logging.config
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DIR = REPO_ROOT / "apps" / "api"
LOGGING_CONFIG_PATH = API_DIR / "logging_config.json"
START_API_SH = REPO_ROOT / "start-api.sh"
START_WEB_SH = REPO_ROOT / "start-web.sh"

# 2026-07-18T18:17:05Z — the exact shape produced by the fixed config,
# confirmed against a real (throwaway-port) uvicorn boot in this fix's
# verification run.
ISO8601_UTC_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b")

_SNAPSHOT_LOGGER_NAMES = ["uvicorn", "uvicorn.error", "uvicorn.access"]


@pytest.fixture()
def logging_config() -> dict:
    assert LOGGING_CONFIG_PATH.is_file(), f"missing {LOGGING_CONFIG_PATH}"
    return json.loads(LOGGING_CONFIG_PATH.read_text())


@pytest.fixture()
def apply_logging_config(logging_config):
    """Applies the REAL logging_config.json via dictConfig (exactly what
    uvicorn's --log-config flag does) and restores every touched logger's
    prior handlers/level/propagate afterwards, so this test can't leak
    global logging state into unrelated tests."""
    root = logging.getLogger()
    snapshot = {
        None: (list(root.handlers), root.level, root.disabled),
    }
    for name in _SNAPSHOT_LOGGER_NAMES:
        lg = logging.getLogger(name)
        snapshot[name] = (list(lg.handlers), lg.level, lg.propagate)

    logging.config.dictConfig(logging_config)
    try:
        yield
    finally:
        handlers, level, disabled = snapshot[None]
        root.handlers = handlers
        root.level = level
        root.disabled = disabled
        for name in _SNAPSHOT_LOGGER_NAMES:
            lg = logging.getLogger(name)
            handlers, level, propagate = snapshot[name]
            lg.handlers = handlers
            lg.level = level
            lg.propagate = propagate


def _format_with(logger_name: str | None, msg: str, args: tuple = ()) -> str:
    """Fetch the formatter actually attached (post-dictConfig) to the given
    logger's first handler and format a synthetic record through it."""
    lg = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    formatter = lg.handlers[0].formatter
    record = logging.LogRecord(
        name=logger_name or "root",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )
    return formatter.format(record)


def test_logging_config_formatters_carry_iso8601_timestamp(logging_config):
    """Both the plain-message and access-log formatters must template
    ``%(asctime)s`` with a UTC ``Z`` suffix, not uvicorn's timestamp-less
    default (``"%(levelprefix)s %(message)s"``)."""
    for name in ("default", "access"):
        fmt = logging_config["formatters"][name]["fmt"]
        assert "%(asctime)s" in fmt, f"formatters.{name}.fmt missing asctime: {fmt!r}"
        assert fmt.strip().startswith("%(asctime)sZ"), (
            f"formatters.{name}.fmt should lead with the UTC-stamped "
            f"asctime so every line is scopable by time: {fmt!r}"
        )
        datefmt = logging_config["formatters"][name]["datefmt"]
        assert datefmt == "%Y-%m-%dT%H:%M:%S", f"formatters.{name}.datefmt: {datefmt!r}"


def test_logging_config_has_root_handler_for_app_module_loggers(logging_config):
    """Application code calls ``logging.getLogger(__name__)`` all over
    ``apps/api/app/**`` (llm_client, discovery adapters, scout_agent, ...)
    with no handler of its own — those propagate to the ROOT logger. Without
    an explicit root handler here, that propagation hits Python's unconfigured
    "handler of last resort" instead, which has no timestamp and would leave
    exactly the kind of application-error line MV-system-001 cared about
    ("39 tracebacks") still undated."""
    assert "root" in logging_config, "no root logger configured — app-module logs won't be timestamped"
    assert "default" in logging_config["root"]["handlers"]


def test_uvicorn_default_formatter_emits_iso8601(apply_logging_config):
    """``uvicorn.error`` has no handler of its own — it propagates to the
    ``uvicorn`` logger, which owns the ``default`` handler/formatter."""
    line = _format_with("uvicorn", "Started server process [1234]")
    assert ISO8601_UTC_RE.search(line), f"no ISO-8601 UTC timestamp in: {line!r}"


def test_uvicorn_access_formatter_emits_iso8601(apply_logging_config):
    line = _format_with(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1:54321", "GET", "/dashboard", "1.1", 200),
    )
    assert ISO8601_UTC_RE.search(line), f"no ISO-8601 UTC timestamp in: {line!r}"


def test_root_propagated_app_logger_emits_iso8601(apply_logging_config):
    """Simulates a plain ``logging.getLogger(__name__)`` call from
    application code (e.g. ``app/services/llm_client.py``) with no handler
    of its own — must still gain a timestamp via the root handler."""
    line = _format_with(None, "simulated app warning")
    assert ISO8601_UTC_RE.search(line), f"no ISO-8601 UTC timestamp in: {line!r}"


def test_start_api_sh_wires_the_log_config():
    content = START_API_SH.read_text()
    assert "--log-config logging_config.json" in content, (
        "start-api.sh must pass uvicorn --log-config logging_config.json "
        "or the ISO-8601 formatters above are never actually used in "
        "production"
    )


def test_start_web_sh_timestamps_every_line_and_preserves_exit_code():
    content = START_WEB_SH.read_text()
    # The timestamping pipe must exist...
    assert "gawk" in content, "start-web.sh no longer pipes through the timestamp stamper"
    assert "strftime" in content and "systime()" in content
    # ...and pipefail must be set BEFORE it, or a pnpm/next crash would be
    # masked by gawk's own (usually zero) exit status, silently defeating
    # aether-web.service's Restart=on-failure.
    pipefail_idx = content.find("set -o pipefail")
    pipe_idx = content.find("pnpm start")
    assert pipefail_idx != -1, "start-web.sh must `set -o pipefail`"
    assert pipe_idx != -1 and pipefail_idx < pipe_idx, (
        "`set -o pipefail` must appear before the `pnpm start | gawk ...` "
        "pipeline, not after"
    )


def test_start_web_sh_no_longer_a_bare_exec_pnpm_start():
    """A bare `exec pnpm start` (no pipe) cannot gain a timestamp prefix —
    guard against a future edit accidentally reverting to it."""
    content = START_WEB_SH.read_text()
    assert re.search(r"^\s*exec\s+pnpm\s+start\s*$", content, re.MULTILINE) is None
