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
    score = engine.score(RESUME_MATCHING, JD_PYTHON)
    assert score.overall >= 90


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
