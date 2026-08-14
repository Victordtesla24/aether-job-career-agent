"""Evidence-corpus service — U2c-0's corpus as tailoring evidence (U2b glue).

The U2c-0 slice ingested the candidate's real, provenance-tagged evidence — 377
items drawn from their immutable baseline résumé, their portfolio site and
every public repo on their GitHub account, each carrying its own source URL,
whether the source STATES the claim or the claim is INFERRED from it, a
confidence, and any caveat. This module is the glue between that corpus and the
anti-fabrication machinery the tailoring and cover-letter agents already run.

**The guard is WIDENED, never bypassed.** ``ResumeTailorService`` already
accepts ``evidence_extra`` — free-text candidate evidence that is indexed into
the fabrication corpus alongside the résumé, so a rewrite may surface a JD
keyword the polished résumé text happens to omit but the candidate's own work
genuinely proves. Corpus items enter through exactly that door: a claim the
corpus supports becomes citable, and a claim NOTHING in the résumé or the
corpus supports is still rejected and reverted to the original bullet, by the
same token guard, metric guard, JD-echo guard and entailment pass as before.
No guard is relaxed, disabled or made conditional anywhere in this file.

Two deliberate choices about what is fed to the guard:

* **Claims only — no URLs.** Every stem in ``evidence_extra`` becomes a
  licensed token for the fabrication guard, so folding raw source URLs into it
  would license junk ("https", "web", "app", a repo slug) as if the candidate
  had claimed it. Provenance stays on the stored row and is available for
  citation/UI; the guard sees the claim plus a compact epistemic tag.
* **Bounded and ranked.** The whole corpus in every prompt would blow the
  tailoring model's token and wall-clock budget (the live 503 storm was
  budget exhaustion). Items are ranked — JD relevance first when a job
  description is supplied, then confidence, then stated-over-inferred — and
  truncated to a character budget, so the evidence that reaches the model is
  the evidence that can actually move the score.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence

#: Ordering weights — higher is stronger evidence.
_CONFIDENCE_RANK = {"high": 3, "med": 2, "medium": 2, "low": 1}
_EPISTEMIC_RANK = {"stated": 2, "inferred": 1}

#: Default cap on the corpus text folded into one prompt. Mirrors
#: ``career_data._MAX_TEXT_CHARS``; overridable for experiments without a
#: deploy via ``AETHER_CORPUS_EVIDENCE_MAX_CHARS``.
_DEFAULT_MAX_CHARS = 4000


def _max_chars() -> int:
    try:
        value = int(os.environ.get("AETHER_CORPUS_EVIDENCE_MAX_CHARS", ""))
    except ValueError:
        return _DEFAULT_MAX_CHARS
    return value if value > 0 else _DEFAULT_MAX_CHARS


def _field(item: dict[str, Any], *names: str) -> str:
    """First non-empty value among ``names`` — tolerates both the corpus.json
    spelling (``stated_or_inferred``) and the stored-row spelling
    (``statedOrInferred``)."""
    for name in names:
        value = item.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def corpus_items_to_evidence_text(items: Sequence[dict[str, Any]]) -> str:
    """Render corpus items as the plain evidence text the tailor already takes.

    One item per UNIT, units separated by a blank line — the exact shape
    ``ResumeTailorService`` splits on (``re.split(r"\\n\\s*\\n", ...)``) when it
    scopes evidence to a bullet's context, so a claim about one employer cannot
    silently license vocabulary on an unrelated bullet.

    Each unit is the claim itself plus a compact epistemic tag naming where it
    came from and how strongly, so the model can write honestly (it can see
    that a byte-share-inferred language claim is weaker than a résumé-stated
    one) without any URL text entering the fabrication index.
    """
    units: list[str] = []
    for item in items:
        claim = _field(item, "claim")
        if not claim:
            continue
        source = _field(item, "source") or "evidence"
        epistemic = _field(item, "stated_or_inferred", "statedOrInferred") or "stated"
        confidence = _field(item, "confidence") or "unrated"
        units.append(f"{claim}\n[{source} · {epistemic} · confidence {confidence}]")
    return "\n\n".join(units)


def rank_corpus_items(
    items: Sequence[dict[str, Any]], job_description: str = ""
) -> list[dict[str, Any]]:
    """Corpus items ordered by usefulness for THIS job, strongest first.

    Deterministic (no model call, no randomness): JD-keyword overlap, then
    confidence, then stated-over-inferred, then the item's own id as a stable
    tiebreak. With no job description the ranking degrades to confidence order,
    which is exactly what a JD-free caller (e.g. a corpus preview) wants.
    """
    jd_stems: set[str] = set()
    stem_text = None
    if job_description.strip():
        from app.services.resume_tailor import content_stems, jd_keyword_terms

        stem_text = content_stems
        # Both sides are normalised by the SAME folding/stopword/stemming rules
        # the tailoring guards and ATS keyword sets use — otherwise
        # "provisioning" in the posting and "provision" in a corpus claim look
        # unrelated, and the evidence that could genuinely move the score never
        # reaches the model. Geography is already excluded by
        # ``jd_keyword_terms`` (ATS-KW-001): a city is not evidence of a skill.
        jd_stems = {
            stem for term in jd_keyword_terms(job_description) for stem in content_stems(term)
        }

    def sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
        claim_stems = set(stem_text(_field(item, "claim"))) if stem_text else set()
        overlap = len(jd_stems & claim_stems)
        confidence = _CONFIDENCE_RANK.get(_field(item, "confidence").lower(), 0)
        epistemic = _EPISTEMIC_RANK.get(
            _field(item, "stated_or_inferred", "statedOrInferred").lower(), 0
        )
        return (-overlap, -confidence, -epistemic, _field(item, "id", "itemId"))

    return sorted(items, key=sort_key)


def build_corpus_evidence(
    user_id: str,
    job_description: str = "",
    repo: Any | None = None,
    max_chars: int | None = None,
) -> str:
    """The user's stored corpus as bounded, JD-ranked evidence text.

    Returns ``""`` when the user has no ingested corpus — every guard then
    behaves exactly as it did before this slice, which is the honest degradation
    for an account whose evidence has never been gathered.
    """
    from app.repositories.evidence_corpus import EvidenceCorpusRepository

    repository = repo or EvidenceCorpusRepository()
    items = repository.list_by_user(user_id)
    if not items:
        return ""
    budget = max_chars if max_chars and max_chars > 0 else _max_chars()
    units: list[str] = []
    used = 0
    for item in rank_corpus_items(items, job_description):
        unit = corpus_items_to_evidence_text([item])
        if not unit:
            continue
        cost = len(unit) + (2 if units else 0)
        if used + cost > budget:
            continue
        units.append(unit)
        used += cost
    return "\n\n".join(units)


def load_corpus_file(path: str | Path) -> list[dict[str, Any]]:
    """Parse a U2c-0 ``corpus.json`` snapshot into item dicts.

    Accepts either the snapshot's own top-level list or an ``{"items": [...]}``
    envelope. Raises ``ValueError`` on anything else rather than importing a
    shape we did not verify — a malformed corpus must fail loudly, never
    half-import.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError(
            f"{path} is not a corpus snapshot: expected a list of items "
            f"(or an object with an 'items' list)"
        )
    return items


def import_corpus_file(
    user_id: str,
    path: str | Path,
    replace_sources: Iterable[str] | None = None,
    repo: Any | None = None,
) -> int:
    """Import a corpus snapshot for ``user_id``; returns the rows written.

    ``replace_sources`` drops the user's existing items for those sources first
    (a scheduled refresh replaces a source wholesale, so retracted evidence
    stops being citable). Import is idempotent on the item's own id.
    """
    from app.repositories.evidence_corpus import EvidenceCorpusRepository

    repository = repo or EvidenceCorpusRepository()
    items = load_corpus_file(path)
    if replace_sources:
        repository.delete_sources(user_id, replace_sources)
    return repository.upsert_many(user_id, items)
