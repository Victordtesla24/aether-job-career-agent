"""GOLD-MASTER-V4 GMV4-ats-001 (BLOCKER, workstream HF §5) — failing tests for
the ATS engine's semantic-similarity component.

THE DEFECT: ``app.services.ats_engine.ATSEngine._semantic_similarity`` is
documented (and marketed to users) as a sentence-transformers
(all-MiniLM-L6-v2) cosine-similarity score — 40% of the overall ATS score.
On production, ``sentence-transformers`` is not importable and no model is
cached, so ``_load_embedding_model()`` always returns ``None`` and the code
silently falls through to a deterministic content-token-overlap
approximation (ats_engine.py:208-213) with NO indication to the caller or
the user that the number shown is not a genuine semantic score. Silent
quality degradation on a user-reachable path is a §0.5 zero-tolerance
violation.

RED first: every symbol this file needs beyond the current
``ATSEngine``/``ATSScore`` does not exist yet.

=== PINNED CONTRACT for the implementer (exact names — match these or these
tests will legitimately still fail after the fix lands) ===

Three scoring paths in strict priority order, all normalized to [0, 1]
before being multiplied by 100 for the existing ``ATSScore.semantic_similarity``
(0-100) field:

1. LOCAL — ``all-MiniLM-L6-v2`` loaded from the model cache dir via the
   existing ``_load_embedding_model()``. No network I/O, no credential.
2. HF INFERENCE API — used only when the local model is unavailable. POSTs
   to the sentence-similarity endpoint for
   ``sentence-transformers/all-MiniLM-L6-v2`` (URL must contain
   ``api-inference.huggingface.co`` and ``all-MiniLM-L6-v2``) using
   ``HF_TOKEN`` read from the environment at call time (never hardcoded).
   Request body (§5.2, exact shape):
       {"inputs": {"source_sentence": <job_description>, "sentences": [<resume_text>]}}
   Response body: ``[float]`` — parsed and clamped to [0, 1].
   Non-2xx (401/429/500/...) or a missing ``HF_TOKEN`` must NEVER fall
   through to token-overlap; it is a scoring-unavailable condition.
3. HONEST DEGRADATION — when neither LOCAL nor HF_API is available, the
   engine must not silently substitute token-overlap dressed up as a
   semantic score.

New symbols required in ``app.services.ats_engine``:

  * ``SemanticScoringUnavailableError(Exception)`` — raised by the two
    methods below when no genuine (local or HF) scoring path succeeds.
  * ``ATSEngine._semantic_similarity_detailed(resume_text, job_description)
    -> <result with .value: float in [0,1] and .path: str in {"local","hf_api"}>``
    — raises ``SemanticScoringUnavailableError`` when neither path works.
    This is the single source of truth the 0-100 ``_semantic_similarity``
    wrapper and ``.score()`` must both build on.
  * ``ATSEngine._call_hf_inference_api(source_sentence: str, sentences: list[str])
    -> list[float]`` — performs the HF POST per the shape above; returns the
    parsed+clamped response; raises ``SemanticScoringUnavailableError`` on
    any non-2xx response.
  * ``ATSScore.semantic_path: str`` — one of ``"local"``, ``"hf_api"``,
    ``"degraded"`` — so startup logging and the UI warning can be truthful
    about which path actually produced the number shown to the user. When
    ``"degraded"``, ``.score()`` must not present a token-overlap number as
    the semantic score (never silently equal to what the old fallback would
    compute).

Outbound HF HTTP is ALWAYS mocked here (``monkeypatch.setattr(httpx, "post", ...)``
on the module-level ``httpx`` object, matching the convention already used in
``tests/test_ml_catalog_fix1.py``) — these tests never touch the network.
"""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

# A JD/resume pair that is SEMANTICALLY very similar (both describe shipping
# containerised backend services) but shares ZERO literal content tokens —
# verified against the engine's own ``_content_tokens`` tokenizer:
#   jd_tokens     = {containerised, microservice, skilled, engineer, deployment, backend}
#   resume_tokens = {dockerised, built, services, shipped, kubernetes}
#   overlap       = {}  (0.0 of the JD's tokens)
# A genuine embedding model scores this pair high; token-overlap scores it 0.
PARAPHRASE_JD = "seeking a backend engineer skilled in containerised microservice deployment"
PARAPHRASE_RESUME = "built and shipped Dockerised services on Kubernetes"


@pytest.fixture(scope="module")
def engine():
    from app.services.ats_engine import ATSEngine

    return ATSEngine()


@pytest.fixture(autouse=True)
def _no_ambient_hf_token(monkeypatch):
    """Never let a real developer/CI HF_TOKEN leak into this hermetic suite."""
    monkeypatch.delenv("HF_TOKEN", raising=False)


class _StubEmbeddingModel:
    """Deterministic fake sentence-transformers model — fixed vectors keyed
    by exact input text, so the test controls the cosine similarity exactly
    without depending on a real (uninstalled) model."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def encode(self, texts, convert_to_numpy=True):  # noqa: ARG002 — match real signature
        return np.array([self._vectors[t] for t in texts])


def _cosine(a: list[float], b: list[float]) -> float:
    a_arr, b_arr = np.array(a), np.array(b)
    denom = (a_arr @ a_arr) ** 0.5 * (b_arr @ b_arr) ** 0.5
    return float(a_arr @ b_arr) / float(denom)


class _FakeHFResponse:
    """Stands in for whatever ``httpx.post(...)`` returns."""

    def __init__(self, status_code: int, json_body):
        self.status_code = status_code
        self._json_body = json_body
        self.text = json.dumps(json_body)

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request(
                "POST", "https://api-inference.huggingface.co/models/x"
            )
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=self
            )


# ---------------------------------------------------------------------------
# A — local model path used when available; no HF network call
# ---------------------------------------------------------------------------


def test_semantic_similarity_uses_local_model_when_available(engine, monkeypatch):
    resume, jd = "Backend engineer with Docker experience.", "Looking for a backend engineer."
    vectors = {resume: [1.0, 0.0], jd: [0.6, 0.8]}
    expected = _cosine(vectors[resume], vectors[jd])  # 0.6, not hardcoded twice

    from app.services import ats_engine

    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: _StubEmbeddingModel(vectors))

    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append((a, k)) or (_ for _ in ()).throw(
        AssertionError("HF network call made even though the local model was available")
    ))

    result = engine._semantic_similarity_detailed(resume, jd)

    assert result.path == "local", f"expected local path, got {result.path!r}"
    assert result.value == pytest.approx(expected, abs=1e-6)
    assert calls == [], "no HF HTTP call should have happened"


# ---------------------------------------------------------------------------
# B — HF Inference API path used when local unavailable; exact payload shape
# ---------------------------------------------------------------------------


def test_semantic_similarity_uses_hf_inference_api_when_local_unavailable(engine, monkeypatch):
    from app.services import ats_engine

    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: None)

    token = "hf_test_token_do_not_use_ABC123"
    monkeypatch.setenv("HF_TOKEN", token)

    resume, jd = "Backend engineer with Docker experience.", "Looking for a backend engineer."
    captured = {}

    def _fake_post(url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers", {})
        return _FakeHFResponse(200, [0.77])

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = engine._semantic_similarity_detailed(resume, jd)

    assert result.path == "hf_api", f"expected hf_api path, got {result.path!r}"
    assert result.value == pytest.approx(0.77)

    assert "api-inference.huggingface.co" in captured.get("url", ""), captured
    assert "all-MiniLM-L6-v2" in captured.get("url", ""), captured

    body = captured.get("json") or {}
    assert body.get("inputs", {}).get("source_sentence") == jd, (
        f"§5.2 payload shape violated — expected inputs.source_sentence == JD text, got {body!r}"
    )
    assert body.get("inputs", {}).get("sentences") == [resume], (
        f"§5.2 payload shape violated — expected inputs.sentences == [resume_text], got {body!r}"
    )

    auth = captured.get("headers", {}).get("Authorization", "")
    assert auth == f"Bearer {token}", (
        f"Authorization header must reference the HF_TOKEN env value, got {auth!r}"
    )


# ---------------------------------------------------------------------------
# C — HF response parsing + clamping
# ---------------------------------------------------------------------------


def test_hf_inference_response_parsed_and_clamped(engine, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_do_not_use_ABC123")

    cases = [
        ([0.9123], 0.9123),
        ([1.4], 1.0),
        ([-0.2], 0.0),
    ]
    for raw, expected in cases:
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHFResponse(200, raw))
        values = engine._call_hf_inference_api("jd text", ["resume text"])
        assert values == pytest.approx([expected]), f"input {raw} should clamp/parse to {[expected]}, got {values}"


# ---------------------------------------------------------------------------
# D — HF error must NOT silently fall through to token overlap (anti-fallback)
# ---------------------------------------------------------------------------


def test_hf_inference_error_does_not_return_silent_token_overlap(engine, monkeypatch):
    from app.services import ats_engine

    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: None)
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_do_not_use_ABC123")

    resume, jd = PARAPHRASE_RESUME, PARAPHRASE_JD

    # Independently compute what the OLD silent token-overlap fallback would
    # have produced for this exact pair, so we can prove the engine does not
    # quietly hand that number back dressed up as "semantic".
    jd_tokens = set(ats_engine._content_tokens(jd))
    resume_tokens = set(ats_engine._content_tokens(resume))
    token_overlap_pct = 100.0 * len(jd_tokens & resume_tokens) / len(jd_tokens)
    assert token_overlap_pct == 0.0, "test fixture assumption broke — pair must have 0 token overlap"

    for status in (401, 429, 500):
        monkeypatch.setattr(
            httpx, "post", lambda *a, **k: _FakeHFResponse(status, {"error": "simulated failure"})
        )
        with pytest.raises(ats_engine.SemanticScoringUnavailableError):
            engine._call_hf_inference_api(jd, [resume])
        with pytest.raises(ats_engine.SemanticScoringUnavailableError):
            engine._semantic_similarity_detailed(resume, jd)

    # And the integration surface: the top-level score must mark this
    # explicitly degraded, never present token-overlap as a real number.
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHFResponse(500, {"error": "boom"}))
    score = engine.score(resume, jd)
    assert score.semantic_path == "degraded", (
        f"expected degraded semantic_path on HF failure with no local model, got {score.semantic_path!r}"
    )
    assert score.semantic_similarity != pytest.approx(token_overlap_pct), (
        "degraded score must not silently equal the token-overlap fallback value"
    )


# ---------------------------------------------------------------------------
# E — genuinely semantic, not token overlap, for a low-literal-overlap paraphrase
# ---------------------------------------------------------------------------


def test_semantic_score_is_not_token_overlap_for_paraphrase_pair(engine, monkeypatch):
    from app.services import ats_engine

    resume, jd = PARAPHRASE_RESUME, PARAPHRASE_JD

    # Confirm (again, locally to this test) that literal overlap is ~0 —
    # this is the whole point of the test.
    jd_tokens = set(ats_engine._content_tokens(jd))
    resume_tokens = set(ats_engine._content_tokens(resume))
    overlap_fraction = len(jd_tokens & resume_tokens) / len(jd_tokens)
    assert overlap_fraction < 0.1

    # Deterministic "genuine" embeddings with a distinctive, non-round cosine
    # similarity — value is computed from the vectors below, never hardcoded
    # separately, so an implementation that just returns a constant fails.
    vectors = {resume: [1.0, 0.0, 0.0], jd: [0.83, 0.5580020469, 0.0]}
    expected = _cosine(vectors[resume], vectors[jd])
    assert expected == pytest.approx(0.83, abs=1e-3)

    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: _StubEmbeddingModel(vectors))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("local model available — must not call HF")
    ))

    result = engine._semantic_similarity_detailed(resume, jd)
    assert result.value == pytest.approx(expected, abs=1e-6)
    assert result.value > 0.5, "a genuine embedding model must score this paraphrase pair as similar"

    score = engine.score(resume, jd)
    assert score.semantic_similarity == pytest.approx(expected * 100.0, abs=1e-3)
    assert score.semantic_similarity > 50.0
    # The old silent fallback would have scored this pair's semantic
    # component at 0 (zero literal token overlap) — the genuine path must
    # diverge sharply from that.
    assert score.semantic_similarity != pytest.approx(0.0)


# ---------------------------------------------------------------------------
# F — engine reports which path actually produced the score
# ---------------------------------------------------------------------------


def test_engine_reports_active_scoring_path(engine, monkeypatch):
    from app.services import ats_engine

    resume, jd = "Backend engineer with Docker experience.", "Looking for a backend engineer."

    # local available
    vectors = {resume: [1.0, 0.0], jd: [0.5, 0.8660254]}
    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: _StubEmbeddingModel(vectors))
    assert engine.score(resume, jd).semantic_path == "local"

    # local unavailable, HF available
    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: None)
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_do_not_use_ABC123")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeHFResponse(200, [0.6]))
    assert engine.score(resume, jd).semantic_path == "hf_api"

    # neither available (no token at all)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not call HF without a token")
        )
    )
    assert engine.score(resume, jd).semantic_path == "degraded"


# ---------------------------------------------------------------------------
# G — zero-regression guard: 40% semantic weight + other components unaffected
# ---------------------------------------------------------------------------


def test_ats_total_score_composition_unchanged(engine, monkeypatch):
    from app.services import ats_engine

    resume = "Senior Backend Engineer with 7 years of experience in Python and AWS."
    jd = "Senior Backend Engineer — 5+ years required. Python, AWS."

    vectors = {resume: [1.0, 0.0], jd: [0.9, 0.4358899]}
    monkeypatch.setattr(ats_engine, "_load_embedding_model", lambda: _StubEmbeddingModel(vectors))

    score = engine.score(resume, jd)

    # Independently recompute keyword/experience via the engine's own
    # existing (unchanged) sub-methods for this exact pair.
    keyword_match, _, _ = engine._keyword_match(resume, jd)
    experience = engine._experience_score(resume, jd)

    expected_overall = max(
        0.0,
        min(
            100.0,
            0.4 * keyword_match + 0.4 * score.semantic_similarity + 0.2 * experience,
        ),
    )
    assert score.overall == pytest.approx(round(expected_overall, 2), abs=0.01)
    assert score.keyword_match == pytest.approx(round(keyword_match, 2), abs=0.01)
    assert score.experience_gap == pytest.approx(round(experience, 2), abs=0.01)
    # New field — pins that the refactor introducing HF/degraded paths keeps
    # reporting which path was actually used, even in the ordinary/local case.
    assert score.semantic_path == "local"
