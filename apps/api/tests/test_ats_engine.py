"""ATS scoring-engine tests (P2-S03) — RED first.

Deterministic 0–100 scoring with three components (keyword / semantic /
experience). Acceptance (spec P2-S03): perfect keyword overlap ≥ 90, zero
overlap ≤ 20, monotonically increasing with overlap, deterministic, bounded,
and a <60 review threshold.
"""
import pytest

from app.services.ats_engine import ATSEngine

ENGINE = ATSEngine()


def test_perfect_keyword_overlap_scores_high():
    resume_text = "Python FastAPI PostgreSQL Docker Kubernetes AWS React TypeScript"
    job_desc = "We need Python FastAPI PostgreSQL Docker Kubernetes AWS React TypeScript expert"
    score = ENGINE.score(resume_text=resume_text, job_description=job_desc)
    assert score.overall >= 90, f"Perfect overlap should score >=90, got {score.overall}"


def test_zero_overlap_scores_low():
    resume_text = "Python FastAPI PostgreSQL Docker Kubernetes"
    job_desc = "Java Spring Oracle .NET COBOL Mainframe COBOL"
    score = ENGINE.score(resume_text=resume_text, job_description=job_desc)
    assert score.overall <= 20, f"Zero overlap should score <=20, got {score.overall}"


def test_score_is_monotonic_with_overlap():
    resume_text = "Python FastAPI PostgreSQL Docker Kubernetes AWS React TypeScript Redis"
    base_jd = "Expert needed in {skills}"
    scores = []
    skill_sets = [
        ["Python"],
        ["Python", "FastAPI"],
        ["Python", "FastAPI", "PostgreSQL"],
        ["Python", "FastAPI", "PostgreSQL", "Docker"],
        ["Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes", "AWS", "React", "TypeScript", "Redis"],
    ]
    for skills in skill_sets:
        jd = base_jd.format(skills=", ".join(skills))
        s = ENGINE.score(resume_text=resume_text, job_description=jd)
        scores.append(s.overall)
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], f"Score should increase: {scores}"


def test_score_is_deterministic():
    resume = "Python machine learning data science TensorFlow pandas numpy"
    jd = "Seeking Python data scientist with TensorFlow experience"
    s1 = ENGINE.score(resume_text=resume, job_description=jd)
    s2 = ENGINE.score(resume_text=resume, job_description=jd)
    assert s1.overall == s2.overall


def test_score_components_are_bounded():
    score = ENGINE.score(resume_text="Python developer", job_description="Python engineer")
    assert 0 <= score.overall <= 100
    assert 0 <= score.keyword_match <= 100
    assert 0 <= score.semantic_similarity <= 100
    assert 0 <= score.experience_gap <= 100
    assert isinstance(score.matched_keywords, list)
    assert isinstance(score.missing_keywords, list)


def test_threshold_gating():
    """Scores below 60 must be flagged as requiring human review."""
    score = ENGINE.score(resume_text="Python", job_description="Java .NET Oracle Mainframe COBOL SAP")
    assert score.requires_review == True
    high_score = ENGINE.score(resume_text="Python FastAPI AWS Docker", job_description="Python developer AWS")
    assert high_score.requires_review == False
