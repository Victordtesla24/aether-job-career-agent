"""ATS scoring engine — deterministic 0-100 resume/JD fit score (P2-S03).

Components (weights):
- ``keyword_match``     (40%) — TF-IDF keyword extraction from the JD; the
  score is the coverage of those keywords in the resume.
- ``semantic_similarity`` (40%) — sentence-transformers (all-MiniLM-L6-v2)
  cosine similarity when the model is installed *and* already cached locally;
  otherwise a deterministic content-token-overlap fallback. No network I/O
  ever happens at scoring time.
- ``experience_gap``    (20%) — years-of-experience parsed from both texts
  with a simple regex; 100 means the resume meets/exceeds the requirement.

``overall = 0.4*keyword_match + 0.4*semantic_similarity + 0.2*experience_gap``
clamped to [0, 100]. Scores below the review threshold (60) set
``requires_review=True`` so a human gates low-fit applications.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

#: Local cache dir for embedding models — never download during scoring.
MODEL_CACHE_DIR = os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", "/tmp/aether_models")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

#: Overall score below which a human must review the match.
REVIEW_THRESHOLD = 60.0

_WEIGHT_KEYWORD = 0.4
_WEIGHT_SEMANTIC = 0.4
_WEIGHT_EXPERIENCE = 0.2

#: Max number of JD keywords considered for the coverage score.
_MAX_KEYWORDS = 40

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]*")
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)

#: English stopwords + recruiting boilerplate that says nothing about fit.
_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does for from had has
    have he her his how i if in into is it its me my not of on or our she so
    than that the their them then there these they this those to was we were
    what when where which who will with would you your
    ability able across additional all also any applicant applicants apply
    are aspects backed based being benefits best both bring bringing build
    building candidate candidates career company culture day dedicated
    degree environment etc excellent experience experienced familiar
    familiarity great grow growing help highly ideal ideally including join
    knowledge like looking love new offer opportunities opportunity per plus
    position preferred proven range red required requirements responsibilities
    role salary seeking skills solid stack strong success successful suitable
    team teams the understanding us via want we well work working world years
    accommodation accommodations disability disabilities veteran veterans
    gender orientation sexual religion religious ethnicity nationality marital
    pregnancy harassment discrimination diversity inclusion inclusive belonging
    regardless
    """.split()
)

#: A single maximal run of digits — used to spot machine-gibberish tokens.
_DIGIT_RUN_RE = re.compile(r"\d+")


def _is_noise_token(token: str) -> bool:
    """Structural non-skill garbage that must never surface as a skill (MV-job-discovery-001).

    Live postings leak URL/domain fragments and machine gibberish (e.g.
    anti-scrape honeypot codes) verbatim into their text; neither is a plausible
    skill:

    * URL / multi-segment domain fragments — ``cdn.openai.com`` (2+ dots) or a
      token carrying a ``http``/``www`` marker. Real tech keeps a single dot
      (``node.js``, ``asp.net``), so it is preserved.
    * Machine gibberish — real skills carry at most a short version suffix with
      one digit group (``python3``, ``log4j``, ``oauth2``, ``i18n``) or, rarely,
      two in a compact token (``log4j2``). An encoded token (base64 honeypot
      ``rmja4ljeymi44ljex``) betrays itself with three+ digit runs, or two runs
      inside a long (>= 12 char) token — never a real skill.
    """
    if token.count(".") >= 2 or "www" in token or "http" in token:
        return True
    digit_runs = len(_DIGIT_RUN_RE.findall(token))
    if digit_runs >= 3 or (digit_runs >= 2 and len(token) >= 12):
        return True
    return False


@dataclass(frozen=True)
class ATSScore:
    """Deterministic breakdown of a resume-vs-JD ATS evaluation."""

    overall: float
    keyword_match: float
    semantic_similarity: float
    #: Experience component score: 100 = requirement met, 0 = fully unmet.
    experience_gap: float
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    requires_review: bool = True


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _content_tokens(text: str) -> list[str]:
    """Lowercased tokens with stopwords/boilerplate/garbage removed (order kept)."""
    tokens = [t.lower().rstrip(".,-") for t in _TOKEN_RE.findall(text)]
    return [
        t
        for t in tokens
        if len(t) >= 2 and t not in _STOPWORDS and not _is_noise_token(t)
    ]


@lru_cache(maxsize=1)
def _load_embedding_model():
    """Return a cached sentence-transformers model, or None.

    The model is used only when the package is installed AND the weights are
    already on disk — scoring must never trigger a download (CI/offline).
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    cache = os.environ.get("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)
    if not os.path.isdir(cache) or not os.listdir(cache):
        return None
    try:
        return SentenceTransformer(EMBEDDING_MODEL, cache_folder=cache)
    except Exception:  # pragma: no cover — corrupted cache etc.
        return None


class ATSEngine:
    """Scores a resume against a job description. Stateless and deterministic."""

    def score(self, resume_text: str, job_description: str) -> ATSScore:
        keyword_match, matched, missing = self._keyword_match(resume_text, job_description)
        semantic = self._semantic_similarity(resume_text, job_description)
        experience = self._experience_score(resume_text, job_description)

        overall = _clamp(
            _WEIGHT_KEYWORD * keyword_match
            + _WEIGHT_SEMANTIC * semantic
            + _WEIGHT_EXPERIENCE * experience
        )
        return ATSScore(
            overall=round(overall, 2),
            keyword_match=round(keyword_match, 2),
            semantic_similarity=round(semantic, 2),
            experience_gap=round(experience, 2),
            matched_keywords=matched,
            missing_keywords=missing,
            requires_review=overall < REVIEW_THRESHOLD,
        )

    # -- components ----------------------------------------------------------

    def _keyword_match(
        self, resume_text: str, job_description: str
    ) -> tuple[float, list[str], list[str]]:
        """Coverage of the JD's TF-IDF-ranked keywords inside the resume."""
        keywords = self._extract_keywords(job_description)
        if not keywords:
            return 0.0, [], []
        resume_tokens = set(_content_tokens(resume_text))
        matched = [kw for kw in keywords if kw in resume_tokens]
        missing = [kw for kw in keywords if kw not in resume_tokens]
        return _clamp(100.0 * len(matched) / len(keywords)), matched, missing

    def _extract_keywords(self, job_description: str) -> list[str]:
        """Top JD terms ranked by TF-IDF weight (deterministic tie-break)."""
        tokens = _content_tokens(job_description)
        if not tokens:
            return []
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            vectorizer = TfidfVectorizer(
                analyzer=lambda _: tokens, lowercase=False  # noqa: ARG005
            )
            matrix = vectorizer.fit_transform([job_description])
            weights = matrix.toarray()[0]
            terms = vectorizer.get_feature_names_out()
            ranked = sorted(zip(terms, weights), key=lambda tw: (-tw[1], tw[0]))
            return [term for term, _ in ranked[:_MAX_KEYWORDS]]
        except ImportError:  # pragma: no cover — sklearn is a hard dep, belt-and-braces
            seen: dict[str, None] = {}
            for token in tokens:
                seen.setdefault(token, None)
            return list(seen)[:_MAX_KEYWORDS]

    def _semantic_similarity(self, resume_text: str, job_description: str) -> float:
        model = _load_embedding_model()
        if model is not None:
            embeddings = model.encode([resume_text, job_description], convert_to_numpy=True)
            a, b = embeddings[0], embeddings[1]
            denom = (a @ a) ** 0.5 * (b @ b) ** 0.5
            if denom == 0:
                return 0.0
            return _clamp(100.0 * float(a @ b) / float(denom))
        # Deterministic fallback: content-token overlap relative to the JD.
        jd_tokens = set(_content_tokens(job_description))
        resume_tokens = set(_content_tokens(resume_text))
        if not jd_tokens:
            return 0.0
        return _clamp(100.0 * len(jd_tokens & resume_tokens) / len(jd_tokens))

    def _experience_score(self, resume_text: str, job_description: str) -> float:
        """100 if the resume meets the JD's years requirement, pro-rated below."""
        required = self._max_years(job_description)
        if required is None or required == 0:
            return 100.0  # no explicit requirement — neutral
        have = self._max_years(resume_text)
        if have is None:
            return 0.0  # requirement stated, resume shows nothing
        if have >= required:
            return 100.0
        return _clamp(100.0 * have / required)

    @staticmethod
    def _max_years(text: str) -> int | None:
        matches = [int(m.group(1)) for m in _YEARS_RE.finditer(text)]
        return max(matches) if matches else None
