"""P2-S03 — deterministic ATS scoring engine (0-100).

RED first: ``app.services.ats_engine`` does not exist yet.
"""
from __future__ import annotations

import pytest

JD_PYTHON = """
Senior Backend Engineer — Sydney.
We are looking for an engineer with 5+ years of experience.
Required skills: Python, PostgreSQL, Redis, Docker, Kubernetes, FastAPI,
AWS, microservices, CI/CD pipelines, and automated testing with pytest.
"""

RESUME_MATCHING = """
Senior Backend Engineer with 7 years of experience.
Expert in Python, PostgreSQL, Redis, Docker, Kubernetes, FastAPI.
Built microservices on AWS with CI/CD pipelines and automated testing with pytest.
"""

RESUME_UNRELATED = """
Pastry chef specialising in laminated doughs, croissants and viennoiserie.
Managed bakery inventory, seasonal menus, supplier relationships and
front-of-house barista training across three patisserie locations.
"""


@pytest.fixture(scope="module")
def engine():
    from app.services.ats_engine import ATSEngine

    return ATSEngine()


def test_perfect_keyword_overlap_scores_high(engine):
    """RESUME_MATCHING restates every required JD_PYTHON skill near-verbatim.
    That is a promise about the ``keyword_match`` component and about which
    terms genuinely get credited — NOT a promise that ``overall`` clears some
    fixed threshold. ``overall = _WEIGHT_KEYWORD*keyword_match +
    _WEIGHT_SEMANTIC*semantic_similarity + _WEIGHT_EXPERIENCE*experience_gap``
    (module docstring), and ``semantic_similarity`` is a genuine
    all-MiniLM-L6-v2 embedding cosine (GMV4-ats-001 removed the old
    token-overlap approximation this test's original ``>= 90`` was calibrated
    against) — it measures how similar two DIFFERENTLY-WORDED texts actually
    read, which "perfect keyword overlap" does not control. Even a literally
    perfect keyword_match=100 and experience_gap=100 only cap ``overall`` at
    ``_WEIGHT_KEYWORD*100 + _WEIGHT_EXPERIENCE*100 + _WEIGHT_SEMANTIC*semantic``
    — asserting a fixed 90 floor on ``overall`` is arithmetically unreachable
    unless semantic >= 75, which resume/JD register differences do not
    guarantee. See docs/delivery/BACKEND-RED-TESTS-2026-08-03.md RULING 1
    (measured: overall=87.74 from keyword_match=94.44,
    semantic_similarity=74.91, experience_gap=100 — genuinely near-perfect,
    capped by an honest semantic score, not a regression).
    """
    from app.services.ats_engine import _WEIGHT_EXPERIENCE, _WEIGHT_KEYWORD, _WEIGHT_SEMANTIC

    score = engine.score(RESUME_MATCHING, JD_PYTHON)

    # 1. keyword_match must be at/near its ceiling: every required skill in
    #    JD_PYTHON appears in RESUME_MATCHING verbatim.
    assert score.keyword_match >= 90, score.keyword_match

    # 2. Whatever the engine still reports missing must be GENUINELY absent
    #    from the résumé text — never a term the résumé actually contains
    #    that the matcher silently failed to credit. That exact failure mode
    #    (a tokenizer fragment like "k+" counted as a keyword, or dropped
    #    incorrectly) is ROOT CAUSE 1 in BACKEND-RED-TESTS-2026-08-03.md, and
    #    this assertion is what would have caught it.
    resume_lower = RESUME_MATCHING.lower()
    for kw in score.missing_keywords:
        assert kw.lower() not in resume_lower, (
            f"{kw!r} reported missing but the resume text actually contains it"
        )

    # 3. experience_gap: RESUME_MATCHING states 7 years against a "5+ years"
    #    requirement, so it must be at its ceiling too.
    assert score.experience_gap == 100, score.experience_gap

    # 4. `overall` floor DERIVED from the scoring weights themselves (read
    #    from the product module, never copied/hardcoded) plus the two
    #    ceiling components just proven above. semantic_similarity is a
    #    genuine embedding cosine for two differently-worded texts about the
    #    same role — bounded below, conservatively, by 50 (well under the
    #    ~75 typically measured for a near-identical skill list, but not an
    #    exact-value pin that would break on harmless embedding-model drift).
    conservative_semantic_floor = 50
    floor = (
        _WEIGHT_KEYWORD * 90
        + _WEIGHT_SEMANTIC * conservative_semantic_floor
        + _WEIGHT_EXPERIENCE * 100
    )
    assert score.overall >= floor, (score.overall, floor)


def test_zero_overlap_scores_low(engine):
    score = engine.score(RESUME_UNRELATED, JD_PYTHON)
    assert score.overall <= 20


def test_score_is_monotonic_with_overlap(engine):
    skills = ["Python", "PostgreSQL", "Redis", "Docker", "Kubernetes", "FastAPI"]
    base = "Backend engineer with 7 years of experience. Skills: "
    previous = -1.0
    for count in range(1, len(skills) + 1):
        resume = base + ", ".join(skills[:count]) + "."
        overall = engine.score(resume, JD_PYTHON).overall
        assert overall >= previous, f"score decreased when adding skill #{count}"
        previous = overall
    # More matching skills must strictly improve on the single-skill resume.
    single = engine.score(base + skills[0] + ".", JD_PYTHON).overall
    assert previous > single


def test_score_is_deterministic(engine):
    scores = [engine.score(RESUME_MATCHING, JD_PYTHON) for _ in range(3)]
    assert scores[0].overall == scores[1].overall == scores[2].overall
    assert scores[0].keyword_match == scores[1].keyword_match
    assert scores[0].matched_keywords == scores[1].matched_keywords


def test_score_components_are_bounded(engine):
    for resume in (RESUME_MATCHING, RESUME_UNRELATED, "short", ""):
        score = engine.score(resume, JD_PYTHON)
        assert 0 <= score.overall <= 100
        assert 0 <= score.keyword_match <= 100
        assert 0 <= score.semantic_similarity <= 100
        assert 0 <= score.experience_gap <= 100
        assert isinstance(score.matched_keywords, list)
        assert isinstance(score.missing_keywords, list)


def test_threshold_gating(engine):
    high = engine.score(RESUME_MATCHING, JD_PYTHON)
    assert high.overall >= 60
    assert high.requires_review is False

    low = engine.score(RESUME_UNRELATED, JD_PYTHON)
    assert low.overall < 60
    assert low.requires_review is True


def test_matched_and_missing_keywords_reflect_texts(engine):
    score = engine.score(RESUME_MATCHING, JD_PYTHON)
    matched_lower = {kw.lower() for kw in score.matched_keywords}
    assert "python" in matched_lower
    # A keyword cannot be both matched and missing.
    assert not matched_lower & {kw.lower() for kw in score.missing_keywords}
