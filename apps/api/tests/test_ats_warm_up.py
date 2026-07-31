"""GOLD-MASTER-V4, §22 STEP 2 (SECOND ROUND) — adversarial-review FAIL on
GMV4-ats-001 (W-HF): ``warm_up_semantic_model()`` / ``_load_embedding_model()``
(``apps/api/app/services/ats_engine.py``) are the load-bearing startup path
that decides whether the ATS engine's 40%-weighted semantic component gets a
genuine embedding at all — and had ZERO direct unit test coverage before this
file (``test_ats_engine_semantic.py`` monkeypatches ``_load_embedding_model``
away entirely rather than exercising it; ``main.py``'s
``_warm_up_ats_semantic_model`` wrapper is untested too).

All four tests here are hermetic: ``sentence_transformers.SentenceTransformer``
is replaced via a ``sys.modules`` stub (never the real package's network
path), and ``SENTENCE_TRANSFORMERS_HOME`` is pointed at a fresh ``tmp_path``
per test so no test can read or corrupt the shared ``/tmp/aether_models``
cache used by the running app.
"""
from __future__ import annotations

import os
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    """Never let a real developer/CI HF_TOKEN leak in, and always clear the
    process-wide ``@lru_cache(maxsize=1)`` memoising ``_load_embedding_model``
    both before and after each test — otherwise one test's resolved model (or
    ``None``) silently poisons every test that runs after it in the same
    pytest process, independent of that test's own fixture state."""
    import app.services.ats_engine as ats_engine

    monkeypatch.delenv("HF_TOKEN", raising=False)
    ats_engine._load_embedding_model.cache_clear()
    yield
    ats_engine._load_embedding_model.cache_clear()


def _install_fake_sentence_transformers(monkeypatch, cls) -> None:
    """Inject a fake ``sentence_transformers`` module into ``sys.modules`` so
    ``from sentence_transformers import SentenceTransformer`` resolves to
    ``cls`` regardless of whether the real package happens to be installed —
    keeps these tests hermetic and independent of the runtime environment."""
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = cls
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)


# ---------------------------------------------------------------------------
# 1 — an absent cache must actually be downloaded into, not just checked
# ---------------------------------------------------------------------------


def test_warm_up_downloads_and_caches_model_when_absent(monkeypatch, tmp_path):
    """When the cache dir is EMPTY (model never downloaded), warm-up must
    attempt the download (construct ``SentenceTransformer(EMBEDDING_MODEL,
    cache_folder=<configured dir>)`` WITHOUT ``local_files_only=True``, since
    that would make an empty cache un-downloadable) and, after a successful
    download, the model must be visible to a fresh, independent call to
    ``_load_embedding_model()`` — i.e. the on-disk cache-population must
    actually be what ``warm_up_semantic_model`` reports, not a stale
    ``lru_cache``-memoised guess from before the download ran."""
    import app.services.ats_engine as ats_engine

    cache_dir = tmp_path / "empty_cache"
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(cache_dir))

    calls: list[dict] = []

    class _FakeST:
        def __init__(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            # Simulate a real download actually landing files on disk — the
            # entire point of calling this during warm-up.
            (cache_dir / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir(
                parents=True, exist_ok=True
            )

    _install_fake_sentence_transformers(monkeypatch, _FakeST)

    path = ats_engine.warm_up_semantic_model()

    assert calls, "warm_up_semantic_model() never attempted to construct SentenceTransformer for an empty cache"
    assert calls[0]["kwargs"].get("cache_folder") == str(cache_dir), calls
    assert calls[0]["kwargs"].get("local_files_only") is not True, (
        "the warm-up download call must allow network access; passing "
        f"local_files_only=True here can never populate an empty cache: {calls[0]}"
    )
    assert os.path.isdir(cache_dir) and os.listdir(cache_dir), (
        "warm_up_semantic_model() must leave the model cache populated on disk after a successful download"
    )
    assert path == "local", (
        f"expected the freshly-downloaded model to resolve to path='local', got {path!r} — "
        "warm_up_semantic_model's own reported path must reflect the disk state it just created, "
        "not a stale pre-download _load_embedding_model() memoisation"
    )

    # An INDEPENDENT direct call (simulating a request that arrives after
    # warm-up completed) must also see the now-cached model — proving the
    # cache-clear inside warm_up_semantic_model() actually un-poisons the
    # module-global lru_cache for every later caller, not just its own
    # single internal re-check.
    model_after = ats_engine._load_embedding_model()
    assert model_after is not None, (
        "a fresh call to _load_embedding_model() after a successful warm-up download still "
        "returns None — the lru_cache was left poisoned by an earlier (pre-download) resolution"
    )


# ---------------------------------------------------------------------------
# 2 — must never raise into the caller (own docstring's explicit promise)
# ---------------------------------------------------------------------------


def test_warm_up_is_non_blocking_and_never_raises_into_startup(monkeypatch, tmp_path):
    """``warm_up_semantic_model``'s own docstring promises: 'Never raises: a
    failed/slow/offline download must not crash the caller.' But that
    guarantee is only implemented around the DOWNLOAD half of the function
    (the ``try/except ImportError / except Exception`` block). The
    PATH-RESOLUTION half that runs unconditionally afterward —
    ``_load_embedding_model.cache_clear()`` then ``_load_embedding_model()``
    — calls ``os.listdir(cache)`` with NO exception handling around it
    (``ats_engine.py``'s ``_load_embedding_model``, the ``os.listdir`` guard
    clause). A cache directory that exists but cannot be listed (permission
    error, a transient FS/NFS issue, a race where it is removed between the
    ``isdir`` and ``listdir`` calls) makes that unguarded call raise straight
    out of ``warm_up_semantic_model`` — breaking its own contract and, per
    the module's own §5.2 design intent, risking exactly the app-startup
    crash this function exists to prevent."""
    import app.services.ats_engine as ats_engine

    cache_dir = tmp_path / "unlistable_cache"
    cache_dir.mkdir()
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(cache_dir))

    class _FakeST:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003 — download no-op
            pass

    _install_fake_sentence_transformers(monkeypatch, _FakeST)

    real_listdir = os.listdir

    def _boom_listdir(path):
        if os.path.abspath(str(path)) == os.path.abspath(str(cache_dir)):
            raise PermissionError(f"simulated permission failure listing {path}")
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", _boom_listdir)

    try:
        path = ats_engine.warm_up_semantic_model()
    except Exception as exc:  # noqa: BLE001 — this is exactly what must never happen
        pytest.fail(
            f"warm_up_semantic_model() raised {exc.__class__.__name__}: {exc!r} — its own "
            "docstring promises it never raises into the caller, but the path-resolution "
            "half (os.listdir(cache) inside _load_embedding_model) is unguarded"
        )
    assert path in ("local", "hf_api", "degraded")


# ---------------------------------------------------------------------------
# 3 — local_files_only=True is load-bearing for the "no network at scoring
#     time" property; a caller reusing the SAME cache dir across two
#     independent load attempts must never trigger a second download
# ---------------------------------------------------------------------------


def test_load_embedding_model_uses_local_files_only(monkeypatch, tmp_path):
    """Per the function's own docstring: 'without [local_files_only=True],
    sentence-transformers still makes a Hub freshness-check network call on
    construction even when every file is already cached' — so a warmed cache
    must make ``_load_embedding_model()`` resolve WITHOUT ever constructing a
    ``SentenceTransformer`` that omits ``local_files_only=True``, no matter
    how many times it is called (memoised or not). This test drives the
    ACTUAL construction call (not just reading source) and additionally
    proves the guarantee survives a cold ``lru_cache`` re-resolution
    (``.cache_clear()`` then call again) — the scenario that matters in
    production, since ``warm_up_semantic_model`` clears this exact cache on
    every startup."""
    import app.services.ats_engine as ats_engine

    cache_dir = tmp_path / "warm_cache"
    cache_dir.mkdir()
    (cache_dir / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir()
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(cache_dir))

    calls: list[dict] = []

    class _FakeST:
        def __init__(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})

    _install_fake_sentence_transformers(monkeypatch, _FakeST)

    ats_engine._load_embedding_model.cache_clear()
    first = ats_engine._load_embedding_model()
    ats_engine._load_embedding_model.cache_clear()
    second = ats_engine._load_embedding_model()

    assert first is not None and second is not None, "warmed cache must resolve to a loaded model both times"
    assert len(calls) == 2, f"expected exactly 2 SentenceTransformer constructions (one per cache_clear), got {len(calls)}"
    for i, call in enumerate(calls):
        assert call["kwargs"].get("local_files_only") is True, (
            f"construction #{i} against an already-warmed cache omitted local_files_only=True "
            f"— every real invocation of sentence-transformers can make a live Hub network call "
            f"at scoring time even with a fully warm cache: {call}"
        )


# ---------------------------------------------------------------------------
# 4 — cold cache + no HF_TOKEN must degrade honestly, never crash the caller
# ---------------------------------------------------------------------------


def test_cold_cache_degrades_honestly_rather_than_crashing(monkeypatch, tmp_path):
    """No local cache AND no ``HF_TOKEN`` — the engine's own contract
    (ats_engine.py's HONEST DEGRADATION) is that scoring degrades rather than
    the process crashing. This test pins that ``warm_up_semantic_model()``
    itself resolves this exact combination to ``"degraded"`` — not
    ``"local"`` (nothing is cached) and not ``"hf_api"`` (no token) — AND
    that a subsequent real ``ATSEngine.score()`` call under this same
    environment returns ``semantic_path == "degraded"`` rather than raising
    ``SemanticScoringUnavailableError`` out to the caller (the honest
    fallback ``ATSEngine.score()`` is documented to perform, but which
    ``warm_up_semantic_model`` never independently verifies actually holds
    for the SAME cold-cache state it just resolved)."""
    import app.services.ats_engine as ats_engine

    cache_dir = tmp_path / "never_downloaded"
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(cache_dir))
    monkeypatch.delenv("HF_TOKEN", raising=False)

    class _FakeST:
        def __init__(self, *args, **kwargs):
            raise OSError("simulated offline: could not reach huggingface.co")

    _install_fake_sentence_transformers(monkeypatch, _FakeST)

    try:
        path = ats_engine.warm_up_semantic_model()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"warm_up_semantic_model() raised {exc.__class__.__name__}: {exc!r} on a cold, offline cache")

    assert path == "degraded", f"cold cache + no HF_TOKEN + offline download must resolve to 'degraded', got {path!r}"

    engine = ats_engine.ATSEngine()
    try:
        score = engine.score("Backend engineer with Python.", "Looking for a backend engineer.")
    except ats_engine.SemanticScoringUnavailableError as exc:
        pytest.fail(
            f"ATSEngine.score() raised {exc!r} straight out to the caller under the exact cold-cache/"
            "no-token state warm_up_semantic_model() just resolved to 'degraded' for — the honest "
            "degradation path must produce a flagged result, never an uncaught exception"
        )
    assert score.semantic_path == "degraded", score
