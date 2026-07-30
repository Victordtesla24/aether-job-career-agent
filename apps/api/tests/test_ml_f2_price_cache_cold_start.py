"""F-2 (HIGH, uat/reports/evidence/prod-verify-5a/PROD-VERIFY-5A.json) —
metered runs are over-charged ~2.3x whenever the in-process model-price
cache is cold.

Finding: ``deepseek/deepseek-v4-pro`` is absent from the static
``MODEL_PRICING`` table (apps/api/app/routers/agents.py), so
``_price_for`` falls through to ``llm_client.cached_model_price``, which
reads the in-process ``_MODEL_CATALOG_CACHE``. A freshly restarted API (or a
cold worker) has never fetched the OpenRouter catalog, so that cache is
empty and the bounded flat default (``_DEFAULT_PRICE``) applies. Live A/B
proof (same agent, same model, same 6095 prompt tokens): a cold-cache run
charged $0.006355 (== flat default), a warm-cache run charged $0.002759
(== the real catalog price) — a ~2.3x over-charge against the customer's
USD spend cap, recurring after EVERY deploy/restart until someone happens
to browse the model catalog in that process.

Fix under test (llm_client.py): the last successfully fetched OpenRouter
catalog is persisted to disk (``_persist_model_catalog_to_disk``) and
lazily loaded back (``_load_model_catalog_from_disk``) the first time a
process sees a cold ``cached_model_price`` lookup — so a fresh restart
prices off the REAL last-known catalog instead of the flat default, with NO
network I/O added to the pricing path. Pinned invariant: a cost computed
after a cold start equals the cost computed with a warm catalog for the
same model.

Every test here points ``llm_client._MODEL_PRICE_CACHE_FILE`` at an
isolated ``tmp_path`` file — never the real (env-isolated, see
``conftest.py``) test-session path other suites might also touch — and
resets ``_disk_price_cache_load_attempted`` so each test observes a
genuinely fresh process's first lookup.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.services import llm_client

_MODEL_ID = "deepseek/deepseek-v4-pro"
#: The exact live catalog entry from the F-2 evidence (promptPerM 0.435 /
#: completionPerM 0.87 -> $0.000435 / $0.00087 per 1K tokens).
_REAL_CATALOG_ENTRY = {
    "id": _MODEL_ID, "name": "DeepSeek V4 Pro", "promptPerM": 0.435,
    "completionPerM": 0.87, "contextLength": 128000, "tier": "budget",
    "reasoning": False,
}
_REAL_PRICE = (0.000435, 0.00087)


@pytest.fixture(autouse=True)
def _isolated_disk_cache(monkeypatch, tmp_path):
    """Every test gets its own not-yet-existing cache file and a process
    that has never attempted a disk load — the exact precondition of a
    genuinely fresh restart."""
    cache_file = tmp_path / "model_price_cache.json"
    monkeypatch.setattr(llm_client, "_MODEL_PRICE_CACHE_FILE", cache_file)
    monkeypatch.setattr(llm_client, "_disk_price_cache_load_attempted", False)
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)
    yield
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)


def test_a_genuinely_cold_process_with_no_persisted_cache_still_returns_none(tmp_path):
    """PIN — must pass BEFORE and AFTER this fix: the very first process ever
    (no disk file has been written yet) has nothing to warm from, so it
    honestly reports 'unpriceable' rather than fabricate a number. Never a
    crash on a missing file."""
    assert not llm_client._MODEL_PRICE_CACHE_FILE.exists()
    assert llm_client.cached_model_price(_MODEL_ID) is None


def test_persisting_a_fetched_catalog_writes_a_readable_file():
    """The write half of the fix: a successful catalog fetch must land on
    disk in a format the load half can parse back."""
    llm_client._persist_model_catalog_to_disk(
        "openrouter", time.monotonic(), [_REAL_CATALOG_ENTRY]
    )
    assert llm_client._MODEL_PRICE_CACHE_FILE.exists(), (
        "a successful catalog fetch must persist to disk — got no file at all"
    )
    payload = json.loads(llm_client._MODEL_PRICE_CACHE_FILE.read_text())
    assert payload["provider"] == "openrouter"
    assert payload["models"] == [_REAL_CATALOG_ENTRY]
    assert "fetchedAtUtc" in payload


def test_persist_write_failure_never_raises(monkeypatch):
    """Disk persistence is a best-effort optimisation; a write failure (e.g.
    read-only filesystem) must never break the catalog fetch that
    triggered it — no suppressed-but-surfaced exception either."""
    def _boom(*a, **k):
        raise OSError("simulated read-only filesystem")

    monkeypatch.setattr(Path, "write_text", _boom)
    llm_client._persist_model_catalog_to_disk(
        "openrouter", time.monotonic(), [_REAL_CATALOG_ENTRY]
    )  # must not raise


def test_THE_INVARIANT_cold_start_price_equals_warm_catalog_price():
    """THE F-2 pin. FAILS NOW (before the fix): a cold ``_MODEL_CATALOG_CACHE``
    has nothing to load from disk (no persistence exists yet), so the cold
    lookup returns ``None`` — the caller (``_price_for``) then falls to the
    flat ``_DEFAULT_PRICE``, exactly reproducing the live $0.006355 vs
    $0.002759 divergence. AFTER the fix, a cold process that starts from a
    previously-persisted catalog must resolve the SAME real price as a warm
    one for the identical model.
    """
    # 1) A WARM catalog (the state right after some earlier successful fetch —
    #    e.g. the deploy that happened to browse the catalog once).
    fetched_at = time.monotonic()
    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (fetched_at, [_REAL_CATALOG_ENTRY])
    llm_client._persist_model_catalog_to_disk("openrouter", fetched_at, [_REAL_CATALOG_ENTRY])
    warm_price = llm_client.cached_model_price(_MODEL_ID)
    assert warm_price == pytest.approx(_REAL_PRICE)  # premise: the warm path prices correctly

    # 2) Simulate a COLD RESTART: a brand-new process has an EMPTY in-memory
    #    cache but the SAME persisted disk file survives (that's the whole
    #    point of persisting past a process boundary).
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)
    llm_client._disk_price_cache_load_attempted = False

    cold_price = llm_client.cached_model_price(_MODEL_ID)

    assert cold_price is not None, (
        "a cold process with a PERSISTED catalog on disk must not fall "
        "through to 'unpriceable' — that is exactly the F-2 defect"
    )
    assert cold_price == pytest.approx(_REAL_PRICE), (
        f"cold-start price {cold_price!r} must equal the warm-catalog price "
        f"{_REAL_PRICE!r} for the identical model (F-2 invariant)"
    )
    assert cold_price == warm_price


def test_the_full_seam_via_price_for_matches_the_live_AB_evidence():
    """End-to-end through the ACTUAL production seam named in the finding
    (``apps/api/app/routers/agents.py:107 _price_for`` ->
    ``llm_client.cached_model_price``), read-only (agents.py is untouched,
    out of scope for this fix). Reproduces the exact live A/B: a cold
    process must price ``deepseek/deepseek-v4-pro`` the same as a warm one,
    never the flat $0.001/$0.002 default that produced the $0.006355 over-charge.
    """
    from app.routers.agents import _DEFAULT_PRICE, _price_for

    # Warm the catalog (as if the deploy, or an earlier request in this same
    # process, had already fetched it) and persist it.
    fetched_at = time.monotonic()
    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (fetched_at, [_REAL_CATALOG_ENTRY])
    llm_client._persist_model_catalog_to_disk("openrouter", fetched_at, [_REAL_CATALOG_ENTRY])
    warm = _price_for(_MODEL_ID)
    assert warm == pytest.approx(_REAL_PRICE)

    # Cold restart: fresh in-memory cache, disk survives.
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)
    llm_client._disk_price_cache_load_attempted = False

    cold = _price_for(_MODEL_ID)

    assert cold != _DEFAULT_PRICE, (
        f"the cold-start price must not silently fall back to the flat "
        f"default {_DEFAULT_PRICE!r} — that IS the F-2 over-charge"
    )
    assert cold == pytest.approx(warm)


def test_stale_persisted_catalog_is_honestly_flagged_by_catalog_freshness():
    """The reconstructed disk-loaded entry must age normally: once its real
    (wall-clock) fetch time is older than the TTL, ``catalog_freshness``
    must report it stale — the fix must not fabricate permanent freshness."""
    long_ago_monotonic = time.monotonic() - llm_client._MODEL_CATALOG_TTL - 3600.0
    llm_client._persist_model_catalog_to_disk(
        "openrouter", long_ago_monotonic, [_REAL_CATALOG_ENTRY]
    )
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)
    llm_client._disk_price_cache_load_attempted = False

    price = llm_client.cached_model_price(_MODEL_ID)
    assert price == pytest.approx(_REAL_PRICE)  # still priced correctly...

    _, stale = llm_client.catalog_freshness("openrouter")
    assert stale is True, "a catalog persisted long past the TTL must honestly read stale"


def test_disk_load_is_attempted_at_most_once_per_process():
    """The lazy load only ever fires on the FIRST cold lookup in a process —
    a later in-memory cache clear (e.g. a sibling test suite's autouse
    fixture popping ``_MODEL_CATALOG_CACHE['openrouter']``) must not
    re-trigger a reload mid-session; that would let one test's disk state
    leak into another's 'cold cache' premise."""
    llm_client._persist_model_catalog_to_disk(
        "openrouter", time.monotonic(), [_REAL_CATALOG_ENTRY]
    )
    # First cold lookup: consumes the one-time load attempt.
    first = llm_client.cached_model_price(_MODEL_ID)
    assert first == pytest.approx(_REAL_PRICE)
    assert llm_client._disk_price_cache_load_attempted is True

    # Overwrite the disk file with DIFFERENT data and clear memory again —
    # if the load were repeated, this second id would resolve; it must not.
    other_entry = {**_REAL_CATALOG_ENTRY, "id": "vendor/other", "promptPerM": 9.0,
                    "completionPerM": 18.0}
    llm_client._persist_model_catalog_to_disk(
        "openrouter", time.monotonic(), [other_entry]
    )
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)

    second = llm_client.cached_model_price("vendor/other")
    assert second is None, (
        "the disk load must fire at most once per process — a later cache "
        "clear re-reading disk would leak cross-test/cross-request state"
    )


def test_corrupt_persisted_cache_is_ignored_not_fabricated(tmp_path, monkeypatch):
    """Defensive: a truncated/garbled cache file (e.g. a crash mid-write, or
    a foreign file at that path) must be ignored — never crash the pricing
    path, never invent a price from garbage."""
    llm_client._MODEL_PRICE_CACHE_FILE.write_text("{not valid json::")

    price = llm_client.cached_model_price(_MODEL_ID)  # must not raise
    assert price is None


def test_free_model_suffix_still_prices_zero_with_no_catalog_anywhere():
    """Contrast guard: the fix must not disturb the pre-existing ``:free``
    zero-price convention when there is genuinely nothing (no memory, no
    disk) to consult."""
    assert llm_client.cached_model_price("vendor/some-model:free") == (0.0, 0.0)
