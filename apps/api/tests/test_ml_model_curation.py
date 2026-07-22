"""ML-model-001/002 — catalog curation denylist (ADR-ML-4, MODELS-LIVE §7 step 2).

FIX-1's live OpenRouter catalog surfaces every model OpenRouter's ``/models``
endpoint lists — including a handful the §3.4 live run sweep PROVED
permanently unable to serve a chat completion for this key: some 404
"no endpoint found for id" on every attempt, others are structurally
non-chat (apply/diff/completion-only endpoints, or a long-running
background "deep research" tool) rather than a transient upstream hiccup.

ADR-ML-4 (docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md — binding ruling
text carried verbatim in the test-author dispatch; not yet committed to
that doc by the concurrently-running investigation/blueprint agents at the
time these tests were authored) rules: a maintained EXACT-ID denylist in
``_curate_openrouter_models`` excludes ONLY the 5 ids PROVEN permanently
broken, seeded from the §3.4 run sweep:

  no-endpoint 404:        allenai/olmo-3-32b-think, inflection/inflection-3-pi
  structurally non-chat:  relace/relace-apply-3, morph/morph-v3-fast,
                           openai/o3-deep-research

TRANSIENT-failing models (rate-limited, timeout, transient-malformed — e.g.
deepseek/deepseek-v4-pro, moonshotai/kimi-k3) MUST NOT be filtered: the
catalog stays honest about what's live, it just stops offering the small set
PROVEN dead rather than degrading UX for models that merely had a bad moment
during the sweep.

These tests are written BEFORE the denylist exists (TDD, §7 step 2). They
FAIL today because ``_curate_openrouter_models`` has no exclusion at all —
every id in ``raw`` (proven-broken or not) passes straight through.
"""
from __future__ import annotations

import pytest

from app.services.llm_client import _curate_openrouter_models

# The 5 ids ADR-ML-4 requires excluded, seeded from the §3.4 run-sweep evidence.
_DENYLISTED_IDS = [
    "allenai/olmo-3-32b-think",
    "inflection/inflection-3-pi",
    "relace/relace-apply-3",
    "morph/morph-v3-fast",
    "openai/o3-deep-research",
]


def _raw_row(model_id: str, **overrides) -> dict:
    row = {
        "id": model_id,
        "name": overrides.pop("name", model_id),
        "pricing": overrides.pop(
            "pricing", {"prompt": "0.000001", "completion": "0.000002"}
        ),
        "context_length": overrides.pop("context_length", 8000),
    }
    row.update(overrides)
    return row


def _full_raw_catalog() -> list[dict]:
    """A raw OpenRouter ``/models`` payload mixing the 5 proven-broken ids
    with normal / transient-failing / free / anthropic-via-openrouter models
    — i.e. what curation actually has to sort through in production."""
    return [
        # --- proven permanently broken (ADR-ML-4 denylist target) ---
        _raw_row("allenai/olmo-3-32b-think"),  # no-endpoint 404
        _raw_row("inflection/inflection-3-pi"),  # no-endpoint 404
        _raw_row(
            "relace/relace-apply-3",  # structurally non-chat (apply/diff tool)
            supported_parameters=["max_tokens"],
        ),
        _raw_row(
            "morph/morph-v3-fast",  # structurally non-chat (apply/diff tool)
            supported_parameters=["max_tokens"],
        ),
        _raw_row(
            "openai/o3-deep-research",  # structurally non-chat (background tool)
            supported_parameters=["max_tokens", "tools"],
        ),
        # --- transient-failing today — MUST stay (over-filtering guard) ---
        _raw_row(
            "deepseek/deepseek-v4-pro",
            pricing={"prompt": "0.0000015", "completion": "0.000003"},
        ),
        _raw_row(
            "moonshotai/kimi-k3",
            pricing={"prompt": "0.0000005", "completion": "0.0000015"},
        ),
        # --- anthropic-via-openrouter, NO 'temperature' in supported_parameters:
        # proves the fix is not a dishonest temperature-capability filter ---
        _raw_row(
            "anthropic/claude-sonnet-5",
            pricing={"prompt": "0.000003", "completion": "0.000015"},
            supported_parameters=["max_tokens", "tools", "top_p"],
        ),
        # --- free model ---
        _raw_row("openrouter/free-model-x", pricing={"prompt": "0", "completion": "0"}),
    ]


# ---------------------------------------------------------------------------
# 1. The 5 proven-broken ids must NOT survive curation.
# ---------------------------------------------------------------------------


def test_curation_excludes_proven_broken_models():
    """fail-before: today ``_curate_openrouter_models`` has no denylist, so
    all 5 proven-broken ids (404 no-endpoint / structurally non-chat, per the
    §3.4 live run sweep) pass straight through untouched and get offered to
    users, who then hit the exact §3.4.4-adjacent dead-end this phase is
    trying to close."""
    out = _curate_openrouter_models(_full_raw_catalog())
    ids = {m["id"] for m in out}
    leaked = ids & set(_DENYLISTED_IDS)
    assert not leaked, f"denylisted model(s) leaked through curation: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# 2. Over-filtering guard: transient / anthropic-honest / free models stay.
# ---------------------------------------------------------------------------


def test_curation_keeps_transient_and_honest_models():
    """Guard against a too-broad fix: the denylist must be a short EXACT
    list, not a heuristic that also swallows transient-failing models or
    (worse) filters on capability signals like a missing 'temperature'
    support entry. A transient-failing model, an Anthropic-via-OpenRouter
    model lacking 'temperature' in supported_parameters, and a free model
    must all survive."""
    out = _curate_openrouter_models(_full_raw_catalog())
    ids = {m["id"] for m in out}
    assert "deepseek/deepseek-v4-pro" in ids, "transient-failing model must NOT be filtered"
    assert "moonshotai/kimi-k3" in ids, "transient-failing model must NOT be filtered"
    assert "anthropic/claude-sonnet-5" in ids, (
        "an honest chat model lacking 'temperature' in supported_parameters "
        "must not be dropped — that would be a dishonest capability filter, "
        "not the proven-broken-id denylist ADR-ML-4 authorizes"
    )
    assert "openrouter/free-model-x" in ids, "free model must survive curation"


# ---------------------------------------------------------------------------
# 3. Denylist matches EXACT ids only — no substring/collateral filtering.
# ---------------------------------------------------------------------------


def test_denylist_is_exact_id_not_substring():
    """A hypothetical model whose id merely CONTAINS a denylisted id as a
    substring (e.g. a future 'morph/morph-v3-fast-turbo') must NOT be
    filtered — pins that the denylist check is an exact-match set lookup,
    not a substring/prefix test, so a real future model can never become
    collateral damage of the curation fix."""
    raw = _full_raw_catalog() + [_raw_row("morph/morph-v3-fast-turbo")]
    out = _curate_openrouter_models(raw)
    ids = {m["id"] for m in out}
    assert "morph/morph-v3-fast-turbo" in ids, (
        "a non-denylisted id containing a denylisted id as a substring "
        "must not be collaterally filtered"
    )
    assert "morph/morph-v3-fast" not in ids  # the real denylisted id is still excluded


# ---------------------------------------------------------------------------
# 4. Regression pin: existing negative-pricing skip + field projection.
# ---------------------------------------------------------------------------


def test_curation_still_skips_negative_pricing_and_projects_fields():
    """The new denylist must not disturb the pre-existing behaviour pinned by
    test_gap_model_choice.py::test_curation_projects_prices_skips_sentinels_and_sorts:
    negative/dynamic-priced sentinel rows are still skipped, and every
    surviving row still projects to exactly the picker's field shape."""
    raw = _full_raw_catalog() + [
        {"id": "vendor/dynamic-auto", "pricing": {"prompt": "-1", "completion": "-1"}},
    ]
    out = _curate_openrouter_models(raw)
    ids = {m["id"] for m in out}
    assert "vendor/dynamic-auto" not in ids  # negative-price sentinel still skipped

    row = next(m for m in out if m["id"] == "deepseek/deepseek-v4-pro")
    assert set(row.keys()) == {
        "id",
        "name",
        "promptPerM",
        "completionPerM",
        "contextLength",
        "tier",
        "reasoning",
    }


# ---------------------------------------------------------------------------
# 5. Integration: the live endpoint stops offering a denylisted id, and
#    saving one via PUT /agents/config/{key} now 422s (ML-catalog-004's
#    existing catalog-membership check reacts automatically once curation
#    stops offering the id).
# ---------------------------------------------------------------------------


def test_denylisted_model_not_offered_and_rejected_on_save(client, auth_headers, monkeypatch):
    from app.services import llm_client as llm

    llm._MODEL_CATALOG_CACHE.pop("openrouter", None)

    class _Cred:
        secret = "sk-test-ml-model"
        base_url = "https://openrouter.ai/api/v1"

    monkeypatch.setattr(llm, "resolve_user_credential", lambda *a, **k: _Cred())

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": _full_raw_catalog()}

    def _fake_get(url, headers=None, timeout=None):
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "get", _fake_get)

    r = client.get("/agents/providers/openrouter/models", headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = {m["id"] for m in r.json()["models"]}
    leaked = ids & set(_DENYLISTED_IDS)
    assert not leaked, f"denylisted model(s) offered by the live endpoint: {sorted(leaked)}"
    # sanity: the endpoint isn't just returning an empty/broken catalog
    assert "deepseek/deepseek-v4-pro" in ids

    put = client.put(
        "/agents/config/jobDiscovery",
        json={"model": "allenai/olmo-3-32b-think"},
        headers=auth_headers,
    )
    assert put.status_code == 422, (
        "a denylisted id, no longer in the live catalog, must be rejected by "
        f"the existing ML-catalog-004 catalog-membership save-validation check; got {put.status_code}: {put.text}"
    )
