"""U2c / U-STORY-1 ruling E3 — the two cover-letter guard corpora must not fork.

``routers/cover_letters.py`` carried this note in code, filed rather than
silently patched::

    Deliberately NOT widened here: ``career_corpus`` is in the generation
    path's FabricationGuard corpus (cover_letter_agent.py:1548) and still is
    not in this one.

The consequence was real and one-directional: a candidate whose GitHub /
portfolio / LinkedIn evidence proves a system name, employer or metric could
have it survive GENERATION and then be flagged as a fabricated entity the
moment they asked the Studio to REFINE that same letter — the guard rejecting
the candidate's own, already-accepted, evidenced claim.

ML-W26's rule is that the refine path must "mirror the main path's call shape
and evidence semantics exactly (never fork them)". The only way to make that
true by CONSTRUCTION rather than by vigilance is for both paths to call one
assembly, which is what these tests pin.
"""
from __future__ import annotations

import inspect

_ARGS = {
    "resume_text": "Jane Doe. Ran the Kafka ingestion pipeline at Northwind.",
    "job_title": "Backend Engineer",
    "company": "Acme",
    "sanitized_description": "We want someone who cares about distributed systems.",
    "letter_date": "14 August 2026",
    "signer": "Jane Doe",
    "position": "Backend Engineer",
    "career_corpus": "GITHUB: jane/consumer-groups — Kafka consumer group rebalancing.",
    "story_evidence": "STORY: Cut ingestion lag 40% at Northwind.",
    "corpus_evidence": "CORPUS: Portfolio — built the ingestion platform.",
}


class TestTheSharedAssembly:
    def test_the_fabrication_corpus_carries_every_evidence_unit(self) -> None:
        from app.services.cover_letter_evidence import build_guard_corpora

        corpora = build_guard_corpora(**_ARGS)
        for unit in (
            _ARGS["career_corpus"],
            _ARGS["story_evidence"],
            _ARGS["corpus_evidence"],
            _ARGS["resume_text"],
            _ARGS["signer"],
            _ARGS["position"],
            _ARGS["letter_date"],
        ):
            assert unit in corpora.fabrication_corpus, unit

    def test_the_job_description_is_evidence_only_for_the_fabrication_guard(
        self,
    ) -> None:
        """GAP-P6-COV-001 / ML-W23, unchanged: the posting grounds an ENTITY
        (the guard must not flag the role's own vocabulary) but is NEVER
        evidence about the CANDIDATE."""
        from app.services.cover_letter_evidence import build_guard_corpora

        corpora = build_guard_corpora(**_ARGS)
        assert _ARGS["sanitized_description"] in corpora.fabrication_corpus
        assert _ARGS["sanitized_description"] not in corpora.claim_evidence

    def test_the_claim_evidence_is_the_candidates_own_evidence_only(self) -> None:
        from app.services.cover_letter_evidence import build_guard_corpora

        corpora = build_guard_corpora(**_ARGS)
        for unit in (
            _ARGS["resume_text"],
            _ARGS["career_corpus"],
            _ARGS["story_evidence"],
            _ARGS["corpus_evidence"],
            _ARGS["signer"],
            _ARGS["position"],
            _ARGS["company"],
        ):
            assert unit in corpora.claim_evidence, unit

    def test_empty_evidence_units_are_dropped_not_rendered_as_blanks(self) -> None:
        from app.services.cover_letter_evidence import build_guard_corpora

        args = dict(_ARGS)
        args.update(career_corpus="", story_evidence="", corpus_evidence="")
        corpora = build_guard_corpora(**args)
        assert "  " not in corpora.claim_evidence
        assert corpora.claim_evidence.strip() == corpora.claim_evidence


class TestBothPathsUseIt:
    """The structural half of E3: proving the assembly is CORRECT is worthless
    if only one caller uses it. Both must, or the fork returns."""

    def test_the_generation_path_builds_its_corpora_through_the_assembly(
        self,
    ) -> None:
        from app.agents import cover_letter_agent

        source = inspect.getsource(cover_letter_agent.CoverLetterAgent.run)
        assert "build_guard_corpora(" in source, (
            "CoverLetterAgent.run assembles its guard corpora inline again — "
            "the shared assembly is the only thing keeping the two paths honest"
        )

    def test_the_refine_path_builds_its_corpora_through_the_assembly(self) -> None:
        from app.routers import cover_letters

        source = inspect.getsource(cover_letters._refine_cover_letter_body)
        assert "build_guard_corpora(" in source, (
            "the /refine path assembles its guard corpora inline — this is the "
            "exact fork ML-W26 forbids and E3 was filed against"
        )

    def test_career_evidence_reaches_the_refine_paths_fabrication_guard(self) -> None:
        """E3 itself, stated as behaviour: an entity only the candidate's
        ingested career evidence proves must be as acceptable on the refine
        path as it already is on the generation path."""
        from app.services.cover_letter_evidence import build_guard_corpora
        from app.services.fabrication_guard import FabricationGuard

        corpora = build_guard_corpora(**_ARGS)
        letter = (
            "Dear Hiring Team,\n\nAt Northwind I ran the Kafka ingestion "
            "pipeline and handled consumer group rebalancing.\n\nJane Doe"
        )
        assert FabricationGuard().check(letter, corpora.fabrication_corpus) == []
