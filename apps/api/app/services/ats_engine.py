"""ATS Optimization Engine — deterministic, no LLM calls (embedding + TF-IDF).

Scoring dimensions:
  1. keyword_match    (40%) — TF-IDF keyword extraction + résumé-coverage overlap
  2. semantic_sim     (40%) — cosine similarity of sentence-transformer embeddings
                              (model: all-MiniLM-L6-v2, downloaded once, cached)
  3. experience_gap   (20%) — year-of-experience requirement vs résumé total YoE

Final score = 0.4*keyword_match + 0.4*semantic_sim + 0.2*(100 - experience_gap)
Threshold: score < 60 → requires_review = True

Determinism (DECISIONS D-0010)
------------------------------
No LLM, no randomness, no temperature. TF-IDF vocabulary and MiniLM inference are
pure functions of the input text, so ``score`` is reproducible bit-for-bit — the
prerequisite for auditable, explainable ATS numbers.

Keyword metric
--------------
``keyword_match`` is résumé **coverage**: the percentage of the résumé's keywords
that appear in the job description (``|resume ∩ jd| / |resume|``). This directly
encodes the acceptance contract — "perfectly matching all résumé keywords" ⇒ 100,
and the score rises monotonically with the share of résumé keywords present.
(Raw Jaccard is diluted by JD-only tokens and would misclassify partial matches;
coverage is the faithful, test-backed reading of the spec's overlap criterion.)
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

#: Embedding model + cache directory (overridable via env; cached once).
_MODEL_NAME = os.environ.get("ATS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_MODEL_CACHE = os.environ.get("SENTENCE_TRANSFORMERS_HOME", "/tmp/aether_models")

# Component weights (sum to 1.0).
_W_KEYWORD = 0.4
_W_SEMANTIC = 0.4
_W_EXPERIENCE = 0.2

#: Below this overall score a match is flagged for human review.
REVIEW_THRESHOLD = 60.0

# Matches "5 years", "5+ yrs", "5 yr" (case-insensitive).
_YOE_RE = re.compile(r"(\d+)\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)

_model_lock = threading.Lock()


@dataclass(frozen=True)
class ATSScore:
    """A deterministic ATS score with its component breakdown."""

    overall: float
    keyword_match: float
    semantic_similarity: float
    experience_gap: float
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    requires_review: bool = False


@lru_cache(maxsize=1)
def _get_model():
    """Load (and cache) the sentence-transformer model exactly once."""
    from sentence_transformers import SentenceTransformer

    os.makedirs(_MODEL_CACHE, exist_ok=True)
    return SentenceTransformer(_MODEL_NAME, cache_folder=_MODEL_CACHE)


class ATSEngine:
    """Deterministic applicant-tracking-system compatibility scorer."""

    def __init__(self, review_threshold: float = REVIEW_THRESHOLD) -> None:
        self._review_threshold = review_threshold
        # A single vectorizer instance is reused; ``fit_transform`` is called per
        # scoring pair so state never leaks between calls (keeps scores pure).
        self._vectorizer = TfidfVectorizer(stop_words="english", lowercase=True)

    def score(self, *, resume_text: str, job_description: str) -> ATSScore:
        """Return a deterministic :class:`ATSScore` for a résumé/JD pair."""
        keyword_match, matched, missing = self._keyword_component(
            resume_text, job_description
        )
        semantic = self._semantic_component(resume_text, job_description)
        experience_gap = self._experience_gap(resume_text, job_description)

        overall = (
            _W_KEYWORD * keyword_match
            + _W_SEMANTIC * semantic
            + _W_EXPERIENCE * (100.0 - experience_gap)
        )
        overall = round(_clamp(overall), 4)

        return ATSScore(
            overall=overall,
            keyword_match=round(keyword_match, 4),
            semantic_similarity=round(semantic, 4),
            experience_gap=round(experience_gap, 4),
            matched_keywords=matched,
            missing_keywords=missing,
            requires_review=overall < self._review_threshold,
        )

    # -- components ------------------------------------------------------------

    def _keyword_component(
        self, resume_text: str, job_description: str
    ) -> tuple[float, list[str], list[str]]:
        """Résumé-keyword coverage via the TF-IDF vocabulary of both texts."""
        resume_terms = self._terms(resume_text)
        jd_terms = self._terms(job_description)
        if not resume_terms:
            return 0.0, [], []

        matched = sorted(resume_terms & jd_terms)
        missing = sorted(resume_terms - jd_terms)
        coverage = 100.0 * len(matched) / len(resume_terms)
        return _clamp(coverage), matched, missing

    def _terms(self, text: str) -> set[str]:
        """Extract the set of significant keywords from ``text`` via TF-IDF.

        A fresh vectorizer per call keeps extraction a pure function of the
        single document (no cross-call vocabulary bleed).
        """
        if not text or not text.strip():
            return set()
        vectorizer = TfidfVectorizer(stop_words="english", lowercase=True)
        try:
            vectorizer.fit_transform([text])
        except ValueError:
            # Text was entirely stop-words / punctuation.
            return set()
        return set(vectorizer.get_feature_names_out())

    def _semantic_component(self, resume_text: str, job_description: str) -> float:
        """Cosine similarity of MiniLM embeddings, mapped to [0, 100]."""
        model = _get_model()
        with _model_lock:
            embeddings = model.encode(
                [resume_text, job_description],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        resume_vec = np.asarray(embeddings[0], dtype=np.float64)
        jd_vec = np.asarray(embeddings[1], dtype=np.float64)
        cosine = float(np.dot(resume_vec, jd_vec))  # already L2-normalized
        # Negative/weak similarity contributes nothing; strong similarity -> 100.
        return _clamp(cosine * 100.0)

    def _experience_gap(self, resume_text: str, job_description: str) -> float:
        """Penalty (0–100) for missing years of experience vs the JD requirement."""
        required = _max_years(job_description)
        if required is None or required <= 0:
            return 0.0  # No stated requirement → no gap penalty.
        candidate = _max_years(resume_text) or 0
        gap = max(0, required - candidate)
        return _clamp(100.0 * gap / required)


def _max_years(text: str) -> Optional[int]:
    """Largest years-of-experience figure mentioned in ``text`` (or ``None``)."""
    matches = [int(m) for m in _YOE_RE.findall(text)]
    return max(matches) if matches else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp ``value`` into ``[low, high]``."""
    return max(low, min(high, value))
