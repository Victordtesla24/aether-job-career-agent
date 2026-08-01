"""ATS scoring engine — deterministic 0-100 resume/JD fit score (P2-S03).

Components (weights):
- ``keyword_match``     (40%) — TF-IDF keyword extraction from the JD; the
  score is the coverage of those keywords in the resume.
- ``semantic_similarity`` (40%) — GMV4-ats-001: a genuine embedding-model
  cosine similarity, resolved through THREE paths in strict priority order
  (see :meth:`ATSEngine._semantic_similarity_detailed`):
    1. LOCAL — sentence-transformers ``all-MiniLM-L6-v2`` loaded from the
       on-disk model cache (``MODEL_CACHE_DIR``). No network I/O at scoring
       time.
    2. HF INFERENCE API — used only when the local model is unavailable AND
       ``HF_TOKEN`` is set; calls the hosted sentence-similarity endpoint.
    3. HONEST DEGRADATION — when neither path is available, the engine
       raises :class:`SemanticScoringUnavailableError` rather than silently
       substituting a token-overlap approximation dressed up as a semantic
       score. :meth:`ATSEngine.score` catches this and marks
       ``ATSScore.semantic_path == "degraded"`` so callers/the UI can be
       truthful about it — it NEVER returns the old token-overlap number
       labelled as a semantic score.
  ``ATSScore.semantic_path`` records which path actually produced the
  number: ``"local"``, ``"hf_api"``, or ``"degraded"``.
- ``experience_gap``    (20%) — years-of-experience parsed from both texts
  with a simple regex; 100 means the resume meets/exceeds the requirement.

``overall = 0.4*keyword_match + 0.4*semantic_similarity + 0.2*experience_gap``
clamped to [0, 100]. Scores below the review threshold (60) set
``requires_review=True`` so a human gates low-fit applications.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

_logger = logging.getLogger(__name__)

#: Local cache dir for embedding models — never download during scoring.
MODEL_CACHE_DIR = os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", "/tmp/aether_models")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

#: HF Inference API endpoint for the same model (§5.2 secondary path). The
#: request shape is fixed by spec: {"inputs": {"source_sentence", "sentences"}}.
_HF_API_URL = (
    "https://api-inference.huggingface.co/models/"
    "sentence-transformers/all-MiniLM-L6-v2"
)
_HF_API_TIMEOUT_SECONDS = 15.0

#: Neutral placeholder used ONLY for the ``semantic_similarity`` (0-100)
#: field when scoring is genuinely unavailable (``semantic_path ==
#: "degraded"``). It is not a measurement — callers/UI MUST check
#: ``semantic_path`` before presenting this number as a real score; it is
#: deliberately never equal to what the removed token-overlap fallback would
#: have silently produced (§5.2 HONEST DEGRADATION).
_DEGRADED_SEMANTIC_SCORE = 50.0

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
    #: Which path actually produced ``semantic_similarity``: "local"
    #: (sentence-transformers), "hf_api" (HF Inference API), or "degraded"
    #: (neither available — ``semantic_similarity`` is a neutral placeholder,
    #: NOT a real measurement; see GMV4-ats-001). The REAL ``ATSEngine.score``
    #: below ALWAYS sets this explicitly to one of those three values — it
    #: never relies on the default. ``"untracked"`` is a DISTINCT sentinel
    #: reserved for callers/test doubles that construct an ``ATSScore``
    #: without tracking provenance at all (this dimension is out of scope for
    #: them) — never conflated with ``"degraded"`` (round-3 note: this used
    #: to default to bare ``None``, which is a weaker signal than a named
    #: string on a ``str`` field).
    #:
    #: GMV4-ats-002 round 3: consumers MUST use a WHITELIST, not a blacklist —
    #: trust the score only when ``semantic_path in ("local", "hf_api")``.
    #: Treat "degraded", "untracked", any unrecognised/future value, and a
    #: field that is simply absent from a payload as equally NOT a genuine
    #: measurement. A blacklist (``== "degraded"``) fails OPEN on exactly the
    #: values this sentinel exists to catch. The one deliberate exception is
    #: ``tailoring_loop.py``'s own per-iteration convergence check, which
    #: intentionally keeps the narrower ``== "degraded"`` test — see its
    #: comment for why.
    semantic_path: str = "untracked"


class SemanticScoringUnavailableError(Exception):
    """Raised when neither the local embedding model nor the HF Inference API
    can produce a genuine semantic-similarity score (GMV4-ats-001, §5.2).

    Callers MUST NOT catch this and silently substitute a token-overlap (or
    any other) approximation dressed up as a semantic score. The honest
    response is to mark the result degraded — see ``ATSEngine.score``, which
    sets ``ATSScore.semantic_path = "degraded"`` on this exception.
    """


@dataclass(frozen=True)
class _SemanticSimilarityResult:
    """A genuine semantic-similarity measurement with provenance.

    ``value`` is cosine similarity (local) or the HF Inference API's
    sentence-similarity score, clamped to [0, 1]. ``path`` is ``"local"`` or
    ``"hf_api"`` — never ``"degraded"``; a degraded condition raises
    :class:`SemanticScoringUnavailableError` instead of constructing one of
    these, so a placeholder value can never be mistaken for a measurement.
    """

    value: float
    path: str


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
    ``local_files_only=True`` is load-bearing for that guarantee: without it,
    sentence-transformers still makes a Hub freshness-check network call on
    construction even when every file is already cached (GMV4-ats-001).
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    cache = os.environ.get("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)
    try:
        cache_populated = os.path.isdir(cache) and bool(os.listdir(cache))
    except OSError as exc:
        # GMV4-ats-002: a cache dir that exists but cannot be listed
        # (permission error, transient FS/NFS issue, a remove-between-
        # isdir-and-listdir race) must degrade honestly, not raise into
        # warm_up_semantic_model's "never raises into startup" contract.
        _logger.warning("ATS embedding cache dir %s could not be listed: %s", cache, exc)
        cache_populated = False
    if not cache_populated:
        return None
    try:
        return SentenceTransformer(EMBEDDING_MODEL, cache_folder=cache, local_files_only=True)
    except Exception:  # pragma: no cover — corrupted cache etc.
        return None


def warm_up_semantic_model() -> str:
    """App-startup warm-up (§5.2 step 2): prime the local embedding-model
    cache and report which semantic-scoring path is ACTUALLY active.

    Attempts to load/cache ``all-MiniLM-L6-v2`` via sentence-transformers
    (which downloads into ``MODEL_CACHE_DIR`` only if not already cached —
    a no-op HTTP-wise once the weights are on disk). Never raises: a
    failed/slow/offline download must not crash the caller. Intended to run
    off the request path (see ``app.main``'s background-thread call) so it
    can never block application startup or the healthcheck.

    Returns the resolved active path — "local", "hf_api", or "degraded" —
    and logs it (at WARNING so operators cannot miss a degraded state),
    together with whether ``HF_TOKEN`` is configured (never its value).
    """
    try:
        from sentence_transformers import SentenceTransformer

        cache = os.environ.get("SENTENCE_TRANSFORMERS_HOME", MODEL_CACHE_DIR)
        os.makedirs(cache, exist_ok=True)
        SentenceTransformer(EMBEDDING_MODEL, cache_folder=cache)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — best-effort warm-up only
        _logger.warning("ATS semantic model warm-up download failed: %s", exc)

    # The cache dir may have just been populated for the first time — drop
    # any earlier (possibly None) memoised result so the next real scoring
    # call re-resolves against the now-current disk state.
    _load_embedding_model.cache_clear()
    model = _load_embedding_model()
    if model is not None:
        path = "local"
    elif os.environ.get("HF_TOKEN", "").strip():
        path = "hf_api"
    else:
        path = "degraded"
    _logger.warning(
        "ATS semantic scoring active path=%s (HF_TOKEN=%s)",
        path,
        "<set>" if os.environ.get("HF_TOKEN", "").strip() else "<absent>",
    )
    return path


class ATSEngine:
    """Scores a resume against a job description. Stateless and deterministic."""

    def score(self, resume_text: str, job_description: str) -> ATSScore:
        keyword_match, matched, missing = self._keyword_match(resume_text, job_description)
        try:
            detailed = self._semantic_similarity_detailed(resume_text, job_description)
            semantic = _clamp(detailed.value * 100.0)
            semantic_path = detailed.path
        except SemanticScoringUnavailableError as exc:
            # HONEST DEGRADATION (§5.2 step 1): never silently substitute the
            # old token-overlap approximation. ``semantic_path="degraded"``
            # is the truthful signal the caller/UI must check before
            # presenting ``semantic_similarity`` as a real score.
            _logger.warning("ATS semantic scoring degraded: %s", exc)
            semantic = _DEGRADED_SEMANTIC_SCORE
            semantic_path = "degraded"
        experience = self._experience_score(resume_text, job_description)

        overall = _clamp(
            _WEIGHT_KEYWORD * keyword_match
            + _WEIGHT_SEMANTIC * semantic
            + _WEIGHT_EXPERIENCE * experience
        )
        return ATSScore(
            overall=round(overall, 2),
            keyword_match=round(keyword_match, 2),
            # Rounded to 4dp (not 2dp like the other components): a genuine
            # embedding cosine similarity is a precise real measurement, and
            # 2dp rounding can lose > 1e-3 of it (GMV4-ats-001 test E pins a
            # 1e-3 tolerance against the unrounded value) — 4dp keeps display
            # precision sane while never discarding meaningful signal.
            semantic_similarity=round(semantic, 4),
            experience_gap=round(experience, 2),
            matched_keywords=matched,
            missing_keywords=missing,
            requires_review=overall < REVIEW_THRESHOLD,
            semantic_path=semantic_path,
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
        """0-100 semantic-similarity score, built on
        :meth:`_semantic_similarity_detailed` (the single source of truth).

        Raises :class:`SemanticScoringUnavailableError` when neither a local
        nor HF-hosted embedding model is available. This method never
        substitutes a token-overlap approximation — a caller that needs an
        honest degraded fallback (like :meth:`score`) must catch this itself.
        """
        detailed = self._semantic_similarity_detailed(resume_text, job_description)
        return _clamp(detailed.value * 100.0)

    def _semantic_similarity_detailed(
        self, resume_text: str, job_description: str
    ) -> _SemanticSimilarityResult:
        """Genuine [0, 1] semantic similarity + which path produced it.

        Priority order (§5.2):
          1. LOCAL — ``_load_embedding_model()`` (sentence-transformers,
             already cached on disk; no network I/O).
          2. HF INFERENCE API — only when the local model is unavailable;
             requires ``HF_TOKEN`` in the environment.
        Raises :class:`SemanticScoringUnavailableError` when neither path can
        produce a genuine score — never returns a token-overlap number.
        """
        model = _load_embedding_model()
        if model is not None:
            embeddings = model.encode([resume_text, job_description], convert_to_numpy=True)
            a, b = embeddings[0], embeddings[1]
            denom = (a @ a) ** 0.5 * (b @ b) ** 0.5
            value = 0.0 if denom == 0 else float(a @ b) / float(denom)
            return _SemanticSimilarityResult(value=max(0.0, min(1.0, value)), path="local")

        values = self._call_hf_inference_api(job_description, [resume_text])
        return _SemanticSimilarityResult(value=values[0], path="hf_api")

    def _call_hf_inference_api(self, source_sentence: str, sentences: list[str]) -> list[float]:
        """POST to the HF Inference API sentence-similarity endpoint (§5.2).

        Payload shape is fixed by spec:
        ``{"inputs": {"source_sentence": ..., "sentences": [...]}}``.
        ``HF_TOKEN`` is read from the environment at call time (never
        hardcoded, never logged). Any missing token or non-2xx response
        raises :class:`SemanticScoringUnavailableError` — never falls
        through to a token-overlap approximation.
        """
        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            raise SemanticScoringUnavailableError(
                "HF Inference API unavailable: HF_TOKEN=<absent>"
            )
        try:
            response = httpx.post(
                _HF_API_URL,
                json={"inputs": {"source_sentence": source_sentence, "sentences": sentences}},
                headers={"Authorization": f"Bearer {token}"},
                timeout=_HF_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SemanticScoringUnavailableError(
                f"HF Inference API returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SemanticScoringUnavailableError(
                f"HF Inference API request failed: {exc.__class__.__name__}: {exc}"
            ) from exc

        try:
            raw = response.json()
        except ValueError as exc:
            raise SemanticScoringUnavailableError(
                "HF Inference API returned a non-JSON response"
            ) from exc
        if not isinstance(raw, list) or not raw:
            raise SemanticScoringUnavailableError(
                f"HF Inference API returned an unexpected response shape: {raw!r}"
            )
        return [max(0.0, min(1.0, float(v))) for v in raw]

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
