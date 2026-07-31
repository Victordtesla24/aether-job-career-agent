"""GOLD-MASTER-V2 §15 — the BLOCKER-002 placeholder-signer guard
(``_looks_like_placeholder_name``, ``apps/api/app/agents/cover_letter_agent.py``)
has FALSE POSITIVES that refuse real people's names.

Root cause (pre-fix): the guard matched the case-insensitive substrings
"probe"/"test" ANYWHERE in the name, plus the substring "gap-", plus an 8+
digit run. Substring-anywhere matching means any real surname that merely
CONTAINS "test" or "probe" as part of a longer word is refused — e.g.
"Tester", "Testa", "Testard" all contain "test"; "Probert" contains "probe"
(its first five letters). These are real English/Italian/French surnames.
A prior agent "fixed" its own failing test by renaming a fixture from the
real-name-shaped "MV Tester" to "Morgan Ellis" (commit 1b655ec) instead of
fixing the guard — that masked this defect. This module proves the false
positives red BEFORE the fix and green after, and proves the true positives
stay caught in both directions (the whole point: tightening a guard must not
just widen it into a no-op).

This is a pure unit-level test against the function itself (no DB / HTTP) —
deterministic and independent of the shared ``aether_test`` schema.
"""
from __future__ import annotations

import pytest

from app.agents.cover_letter_agent import (
    _looks_like_placeholder_name,
    stored_letter_has_placeholder_signer,
    stored_signoff_name,
)

#: Real human names the OLD substring-anywhere rule wrongly refused (or, for
#: the last three, names chosen from the same "real people whose surnames
#: happen to look test-ish" family named in the finding -- see the honest
#: per-case breakdown in the evidence artifact for which of these were
#: ACTUALLY red under the old rule vs. already-green regression guards).
REAL_NAMES_MUST_BE_ACCEPTED = [
    "MV Tester",  # the exact fixture a prior agent renamed away from (1b655ec)
    "Sarah Probert",  # "Probert" starts with "probe"
    "Marco Testa",  # "Testa" contains "test"
    "Anna Probst",  # German/English surname
    "Yuki Demos",  # Greek-origin surname
    "Lars Samplonius",  # Dutch surname
    "Jean-Baptiste Testard",  # double-barrelled given name + "test"-containing surname
    "田中健一",  # non-Latin-script (Japanese kanji) real name -- Tanaka Ken'ichi
]

#: Genuine test-artefact / placeholder identities that MUST stay refused.
#: Taken verbatim from the production contamination incident and the sibling
#: guard-rule test file (tests/test_wb1_blocker002_placeholder_signer_name.py).
TEST_ARTEFACT_NAMES_MUST_BE_REFUSED = [
    "GAP-P7-DEF-B Probe 1785452243543",  # exact production-contaminated string
    "probe_user_20260731093000",  # snake_case + timestamp identifier
    "QA Probe",  # internal QA fixture identity
    "QA Test Runner 445566778899",  # internal QA fixture identity + digit run
]


@pytest.mark.parametrize("name", REAL_NAMES_MUST_BE_ACCEPTED)
def test_real_human_name_is_not_flagged_as_placeholder(name):
    """A real human name must never trip the placeholder-signer guard --
    refusing it means a paying customer cannot generate a cover letter at
    all. This is the false-positive guard GOLD-MASTER-V2 §15 requires."""
    assert not _looks_like_placeholder_name(name), (
        f"{name!r} is a real human name and must NOT be flagged as a "
        "placeholder/test-probe identity -- an over-broad guard that "
        "refuses real names is a WORSE defect than the one it prevents."
    )


@pytest.mark.parametrize("name", TEST_ARTEFACT_NAMES_MUST_BE_REFUSED)
def test_test_artefact_identity_is_still_flagged_as_placeholder(name):
    """Tightening the guard's discrimination must not turn it into a no-op:
    every genuine test-probe/placeholder identity named in the BLOCKER-002
    finding and its sibling test file must stay refused."""
    assert _looks_like_placeholder_name(name), (
        f"{name!r} is a test-artefact/placeholder identity (from the "
        "BLOCKER-002 production incident or the QA fixture namespace) and "
        "must STILL be flagged -- relaxing the false-positive guard must "
        "not also relax the true-positive detection it exists to provide."
    )


# ===========================================================================
# BLOCKER-002 leak paths (d1/d2): the guard now runs over a STORED letter
# body — MODEL-GENERATED PROSE, not just a profile field. Scoping it to the
# SIGN-OFF LINE ONLY is what keeps the false-positive surface the same size
# as before; a naive whole-body scan would refuse a paying user their own
# letter because the PROSE says "led testing" or quotes an 8-digit figure.
#
# Evidence for the shape being parsed:
# uat/reports/evidence/gold-master-v2/waves/blocker002-remediation-plan.md
# §1.4 -- all 8 production rows carry the fixture as a single trailing
# sign-off line, "…\n\nSincerely,\n<fixture>\n", never in prose, with NO
# stored letterhead block.
# ===========================================================================

_LETTER_HEAD = (
    "31 July 2026\n\n"
    "Hiring Team\nGrafana Labs\nRe: Senior Product Manager\n\n"
    "Dear Hiring Team at Grafana Labs,\n\n"
)

#: Prose that deliberately trips EVERY signal the name rule looks for --
#: a bare "test" token, a bare "gap" token, and an 8+ digit run -- while
#: being entirely legitimate letter content. Scoping to the sign-off line is
#: the ONLY thing standing between this letter and a wrongful refusal.
_HAZARDOUS_PROSE = (
    "I led testing for three squads and closed the capability gap between "
    "platform and product. In one gap analysis I ran a test of the ingestion "
    "pipeline that processed 12345678 events without a single dropped record, "
    "and the test suite I built still gates every release."
)


def _letter(signer: str, *, closing: str = "Sincerely,", prose: str = _HAZARDOUS_PROSE) -> str:
    """A full §10.2-shaped letter (exactly what ``compose_letter`` emits)."""
    return f"{_LETTER_HEAD}{prose}\n\n{closing}\n{signer}\n"


REAL_SIGNOFFS_MUST_BE_ACCEPTED = [
    _letter("Jordan Rivera"),
    _letter("MV Tester"),  # a real person named Tester, signing their own letter
    _letter("Sarah Probert"),
    _letter("Jean-Baptiste Testard", closing="Kind regards,"),
    _letter("Marco Testa", closing="Best regards,"),
    _letter("田中健一"),
    # Sign-off carried INLINE on the closing line rather than the next line.
    _LETTER_HEAD + _HAZARDOUS_PROSE + "\n\nSincerely, Jordan Rivera\n",
]


@pytest.mark.parametrize("letter", REAL_SIGNOFFS_MUST_BE_ACCEPTED)
def test_clean_stored_letter_is_not_refused(letter):
    """A letter signed by a real human must NEVER be refused -- even when its
    PROSE contains "test"/"gap" as ordinary words and an 8-digit figure.
    Refusing here denies a paying user their own letter."""
    assert not stored_letter_has_placeholder_signer(letter), (
        "a legitimate stored letter was flagged as placeholder-signed; "
        f"the extracted sign-off was {stored_signoff_name(letter)!r}"
    )


#: BOTH production fixture variants (§1.2 of the remediation plan -- keying
#: anything to a single literal would miss 3 of the 8 rows), in the exact
#: stored shape plus the closing/inline variations a hand-edited letter can
#: take.
CONTAMINATED_LETTERS_MUST_BE_REFUSED = [
    _letter("GAP-P7-DEF-B Probe 1785452243543"),
    _letter("GAP-P7-DEF-B Probe 1784823962960"),
    _letter("GAP-P7-DEF-B Probe 1785452243543", closing="Kind regards,"),
    _letter("QA Probe"),
    _letter("probe_user_20260731093000"),
    _LETTER_HEAD + _HAZARDOUS_PROSE + "\n\nSincerely, GAP-P7-DEF-B Probe 1784823962960\n",
]


@pytest.mark.parametrize("letter", CONTAMINATED_LETTERS_MUST_BE_REFUSED)
def test_contaminated_stored_letter_is_refused(letter):
    assert stored_letter_has_placeholder_signer(letter), (
        "a stored letter whose SIGN-OFF is a test-artefact identity must be "
        f"refused; the extracted sign-off was {stored_signoff_name(letter)!r}"
    )


def test_only_the_signoff_line_is_inspected_never_the_prose():
    """The scoping decision, asserted directly: the extracted identity is the
    sign-off line and nothing else. A whole-body scan would return prose."""
    letter = _letter("Jordan Rivera")
    assert stored_signoff_name(letter) == "Jordan Rivera"
    assert "test" in letter.lower() and "gap" in letter.lower(), (
        "fixture must actually contain the hazardous prose tokens, else this "
        "test proves nothing"
    )


def test_prose_line_opening_with_a_closing_word_is_not_read_as_a_signer():
    """A body line that happens to open with a closing word ("Best, …") is
    prose, not a sign-off: it is a sentence, not a name line. Reading it as an
    identity would re-introduce the prose false positives the scoping exists
    to prevent."""
    letter = (
        _LETTER_HEAD
        + "Best, I want to add that our test suite passed and the gap closed.\n"
    )
    assert stored_signoff_name(letter) == ""
    assert not stored_letter_has_placeholder_signer(letter)


def test_letter_with_no_signoff_yields_no_signer():
    """Honest scoping boundary: a body with no closing block has no sign-off
    to inspect, so the guard abstains rather than guessing at the last prose
    line (documented residual false-negative -- generation-time guards cover
    the write path)."""
    letter = _LETTER_HEAD + _HAZARDOUS_PROSE + "\n"
    assert stored_signoff_name(letter) == ""
    assert not stored_letter_has_placeholder_signer(letter)


def test_empty_and_missing_bodies_are_safe():
    for value in ("", "   \n\n", None):
        assert stored_signoff_name(value or "") == ""
        assert not stored_letter_has_placeholder_signer(value or "")
