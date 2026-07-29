"""ARQ worker logging bootstrap (QA-FAIL-02).

arq's own CLI (``arq.cli:cli``) configures ONLY the ``arq`` logger:
``logging.config.dictConfig(default_log_config(verbose))`` — see the
installed package's ``arq/cli.py`` / ``arq/logs.py``. That default config
has no ``root`` key, so the Python root logger is left at the interpreter
default (``WARNING``, no handler). Every application ``logger.info(...)``
call outside the ``arq`` namespace is therefore silently dropped in the
worker process — including the ``admin-free-fallback`` audit marker in
``app/services/llm_client.py`` (line ~1689) and the scout/board-sweep INFO
lines. arq's own INFO lines still appear (they go through arq's own
handler), which makes ``/var/log/aether/worker.log`` look healthy while the
application-level audit trail is actually missing. With
``AETHER_ASYNC_GENERATION=true`` nearly all pipeline work runs in this
worker process, so this made ADR-ML-3's "not silent" guarantee for the
admin-free-fallback feature unmet in production (0 matches for
``grep admin-free-fallback /var/log/aether/worker.log`` despite 4 confirmed
engagements).

Fix: pass this module's ``LOG_CONFIG`` to arq's own log-config CLI flag —
``arq ... --custom-log-dict app.workers.logging_config.LOG_CONFIG`` (see
``start-worker.sh``) — the same idea ``start-api.sh`` already applies to
uvicorn via ``--log-config logging_config.json`` (MV-system-001), just
using arq's own hook for it instead of a JSON file (arq's ``--custom-log-dict``
takes a dotted import path to a dict, not a file path).

arq does not MERGE ``--custom-log-dict`` with its default config — it
REPLACES it wholesale (``arq/cli.py``: ``log_config = import_string(...)
if custom_log_dict else default_log_config(verbose)`` then a single
``dictConfig(log_config)`` call). So this dict must cover both halves:

* ``root`` — INFO + a timestamped handler, so application-module loggers
  (``logging.getLogger(__name__)`` in llm_client.py etc., which have no
  handler of their own and propagate straight to root) are finally emitted.
* ``arq`` — kept at INFO with its OWN handler, and explicitly
  ``propagate: False``. Without that, arq's child loggers
  (``arq.worker``, ``arq.jobs``, ``arq.connections``, ...) would propagate
  up through ``arq`` to the newly-handled root logger too, and every arq
  line would be printed TWICE (once via ``arq``'s handler, once via root's).
  ``propagate: False`` stops the climb at ``arq`` itself, so arq's own
  logging keeps working exactly as before — one line per event, not zero,
  not two.

Timestamp format matches ``apps/api/logging_config.json`` (MV-system-001):
production host clock is confirmed UTC (``timedatectl``: ``Etc/UTC``), so
the literal ``Z`` suffix is accurate.
"""
from __future__ import annotations

from typing import Any

LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)sZ %(levelname)-8s %(name)s: %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "arq": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["default"],
        "level": "INFO",
    },
}
