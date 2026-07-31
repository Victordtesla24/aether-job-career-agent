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

from app.agents.cover_letter_agent import _looks_like_placeholder_name

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
