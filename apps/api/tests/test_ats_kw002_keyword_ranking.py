"""ATS-KW-002 — the required-keyword set was chosen ALPHABETICALLY and truncated.

``ATSEngine._extract_keywords`` fitted a ``TfidfVectorizer`` on a SINGLE
document. With n=1, sklearn's smoothed IDF is ``ln((1+n)/(1+df)) + 1 =
ln(2/2) + 1 = 1`` for every term present, and L2 normalisation is a positive
scalar that preserves order — so the "TF-IDF weight" was identically the raw
term frequency. Since almost every JD term occurs exactly once, the sort's
``(-weight, term)`` tie-break meant the required-keyword set was chosen in
ALPHABETICAL ORDER and then cut at ``_MAX_KEYWORDS`` (40).

FAIL-BEFORE, measured 2026-08-04 against HEAD f5d7139 on ``JD_LATE_REQUIREMENTS``
below (87 unique content tokens):

    returned: delivery end group platform about accounts advanced afternoon
              against agencies allowance analytics annual arrangements atlassian
              attach attitude author automate barista base before birthday bonus
              book breakfasts budget busy caring catered chain chairs charity
              click closing coffee competitive continuous corporate crew

    requirements scored : 0 of 6   (terraform, sql, python, kubernetes,
                                    observability, warehouse all absent)
    perks tokens scored : 20
    trailing strictly-alphabetical run: 36 of 40, cut off at "crew"

Tests 1, 2, 3, 4, 6, 7 and 11 FAIL at HEAD. Tests 5, 8, 9, 10, 12 and 13 pass
at HEAD and are pinned here as regression guards so the fix cannot satisfy this
file by gutting keyword extraction, moving a weight, or re-breaking ATS-KW-001.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def engine():
    from app.services.ats_engine import ATSEngine

    return ATSEngine()


#: A realistic posting whose every genuine requirement is stated ONCE and sits
#: LATE in the alphabet, behind a perks block full of early-alphabet nouns.
#: This is the ordinary shape of a job ad, not a contrived string: measured over
#: 5750 real production postings, 84.9% of the technology terms present never
#: entered the scored set, "python" being dropped from 1011 of them.
JD_LATE_REQUIREMENTS = """
Staff Platform Engineer

About the role: you will own the build, deployment and observability platform
end to end for a busy engineering group.

What you will do:
- Author infrastructure modules in Terraform and apply them across accounts.
- Write and tune advanced SQL against the analytics warehouse.
- Ship production services in Python and run them on Kubernetes.
- Automate delivery with a continuous integration and delivery chain.

What we offer:
- A competitive base, an annual bonus, generous equity and a book allowance.
- Catered breakfasts, barista coffee, and a games afternoon each fortnight.
- Additional charity days, a birthday day off, and a decent gym discount.
- Flexible arrangements, a caring crew, an inclusive attitude and free fruit.
- Corporate discounts, education budget, headphones, ergonomic chairs, desks.

Atlassian Group Ltd is an equal opportunity employer. Direct applicants only,
no agencies. Click apply and attach a current CV before the closing date.
"""

#: What a human reading that posting would name as its requirements.
LATE_REQUIREMENTS = frozenset(
    {"terraform", "sql", "python", "kubernetes", "observability", "warehouse"}
)

#: Perks / employer-identity / application-mechanics tokens from the same
#: posting. None of them is something a candidate can be assessed on.
LATE_PERKS = frozenset(
    {
        "allowance", "annual", "barista", "birthday", "bonus", "book", "breakfasts",
        "budget", "caring", "catered", "chairs", "charity", "click", "closing",
        "coffee", "competitive", "corporate", "crew", "cv", "days", "desks",
        "discount", "discounts", "education", "equity", "fortnight", "fruit",
        "games", "generous", "gym", "headphones", "agencies", "afternoon",
    }
)


def _trailing_alphabetical_run(keywords: list[str]) -> int:
    """Length of the strictly-ascending alphabetical run at the end of the list."""
    run = 1
    for index in range(len(keywords) - 1, 0, -1):
        if keywords[index - 1] < keywords[index]:
            run += 1
        else:
            break
    return run


def test_1_requirements_stated_late_in_the_alphabet_are_scored(engine):
    """THE DEFECT. Every requirement in this posting is alphabetically after the
    perks vocabulary, so the 40-slot cut fell before all of them.

    FAILS BEFORE: 0 of 6 present; the set stops at "crew"."""
    keywords = set(engine._extract_keywords(JD_LATE_REQUIREMENTS))
    missing = sorted(LATE_REQUIREMENTS - keywords)
    assert not missing, f"requirements never scored: {missing}"


def test_2_the_required_keyword_set_is_not_an_alphabetical_run(engine):
    """The structural claim, independent of any judgement about which words are
    skills: a required-keyword set that is one long alphabetical run was chosen
    by spelling, not by relevance.

    FAILS BEFORE: 36 of the 40 returned keywords are a single ascending run."""
    keywords = engine._extract_keywords(JD_LATE_REQUIREMENTS)
    assert len(keywords) == 40, len(keywords)
    run = _trailing_alphabetical_run(keywords)
    assert run < 10, f"{run} of {len(keywords)} keywords are one alphabetical run: {keywords}"


def test_3_perks_boilerplate_does_not_displace_requirements(engine):
    """The other half of the same slot budget: perks tokens took the room the
    requirements needed.

    FAILS BEFORE: 20 perks tokens occupy scored slots."""
    keywords = set(engine._extract_keywords(JD_LATE_REQUIREMENTS))
    perks = sorted(keywords & LATE_PERKS)
    assert len(perks) <= 6, f"{len(perks)} perks tokens occupy scored slots: {perks}"


#: All-lowercase prose, every content token occurring exactly once and none of
#: them carrying skill evidence — the worst case for ranking, and the case where
#: the old tie-break did all of its damage.
JD_FLAT_PROSE = """
the successful applicant will handle vendor reconciliation, quarterly
forecasting, statutory reporting, inventory valuation, treasury oversight,
budgeting cycles, variance narratives, audit preparation and board packs.
"""


def test_4_ties_are_broken_by_the_posting_not_by_the_alphabet(engine):
    """Item 3 of the finding: an alphabetical tie-break must never again decide
    what a candidate is scored on. Where nothing distinguishes two tokens but
    their position, the posting's OWN ordering decides — job ads front-load what
    matters — and that ordering is unique per token, so the sort key is a TOTAL
    order and no tie can survive to reach a comparison on spelling.

    FAILS BEFORE: the returned list is exactly ``sorted()``."""
    from app.services.ats_engine import _content_tokens

    keywords = engine._extract_keywords(JD_FLAT_PROSE)
    assert keywords != sorted(keywords), keywords

    appearance: list[str] = []
    for token in _content_tokens(JD_FLAT_PROSE):
        if token not in appearance:
            appearance.append(token)
    assert keywords == appearance[: len(keywords)], (keywords, appearance)


def test_5_single_document_idf_is_provably_constant():
    """MECHANISM, not a defect assertion — this passes before and after and
    exists so the root cause cannot be re-litigated from memory.

    Fitting any IDF on ONE document is arithmetically incapable of ranking:
    every present term gets the same weight, so ordering falls entirely to the
    tie-break. This is why the ``TfidfVectorizer`` was removed rather than
    re-parameterised."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    tokens = ["python", "terraform", "sql", "lunches", "catered"]
    vectorizer = TfidfVectorizer(analyzer=lambda _: tokens, lowercase=False)  # noqa: ARG005
    vectorizer.fit_transform(["one document"])
    assert set(vectorizer.idf_) == {1.0}, vectorizer.idf_


#: A non-technical posting. Its requirements are statutory acronyms and one
#: branded tool — no framework names anywhere — so it proves the fix is not a
#: tech-only fix. Modelled on a real production posting (an Accountant role).
JD_ACCOUNTING = """
Accountant

About the role: you will own the month end close for a busy finance team.

What you will do: prepare and lodge GST, FBT and PAYG obligations, run the
fortnightly payroll, complete balance sheet reconciliations, manage cash flow
across several bank accounts and currencies, and own the Expensify expense
platform. You will calculate superannuation and maintain the fixed asset
register while supporting the annual audit.

What we are looking for: a CA or CPA qualification, public practice
experience, and advanced spreadsheet ability.

What we offer: a competitive base, an annual bonus, generous parental leave,
catered breakfasts, a wellbeing allowance, extra superannuation contributions,
a birthday day off, a gym discount and a genuine culture of care.
"""


def test_6_a_non_technical_posting_scores_its_own_domain_terms(engine):
    """The fix must not be a fix for software postings only. Here the evidence
    is all-caps statutory acronyms and one Title-Cased product.

    FAILS BEFORE: the alphabetical cut lands mid-"c" and none of these are in."""
    keywords = set(engine._extract_keywords(JD_ACCOUNTING))
    expected = {"gst", "fbt", "payg", "expensify", "cpa"}
    assert expected <= keywords, sorted(expected - keywords)


def test_11_a_perk_word_that_is_also_the_subject_matter_survives(engine):
    """The safety property that rules out a flat "benefits word" blocklist.

    "superannuation", "payroll" and "compensation" are perks boilerplate in a
    software ad and the literal subject matter of an accounting one. Demotion is
    therefore POSITIONAL and every-occurrence: a token is demoted only when it
    NEVER appears in requirement prose. Here both words appear in the duties, so
    both must be scored even though they also appear under "What we offer".

    FAILS BEFORE: the alphabetical cut drops both."""
    keywords = set(engine._extract_keywords(JD_ACCOUNTING))
    assert {"superannuation", "payroll"} <= keywords, sorted(keywords)


JD_SKILL_LIST = """
Analytics Engineer

About the role: you will own the transformation layer.

Requirements: production experience with Spark, Kafka, Airflow, dbt,
Snowflake and Terraform, plus strong modelling fundamentals.
"""


def test_7_a_lowercase_branded_tool_is_recovered_from_its_skills_list(engine):
    """``dbt`` is lowercase by its own branding, so it carries no shape and no
    capitalisation evidence. It is recovered because it sits in a separator run
    that already holds two evidenced members — the same two-confirmed-elements
    rule ``_geographic_tokens`` uses for location chains.

    FAILS BEFORE only in company: at HEAD this posting is short enough that dbt
    survives, so this test pins the LIST mechanism directly instead."""
    from app.services.ats_engine import (
        _content_tokens,
        _iter_tokens,
        _skill_evidence_tokens,
        _skill_list_neighbours,
    )

    candidates = set(_content_tokens(JD_SKILL_LIST))
    occurrences = [
        (token, start, end)
        for token, start, end in _iter_tokens(JD_SKILL_LIST)
        if token in candidates
    ]
    evidenced = _skill_evidence_tokens(JD_SKILL_LIST, occurrences)
    assert "dbt" not in evidenced, "precondition: dbt carries no evidence of its own"
    joined = _skill_list_neighbours(JD_SKILL_LIST, occurrences, evidenced)
    assert "dbt" in joined, sorted(joined)
    assert "dbt" in set(engine._extract_keywords(JD_SKILL_LIST))


def test_8_a_short_posting_still_yields_every_content_token(engine):
    """Ranking must not become filtering. Below the cap, membership is exactly
    the content tokens (minus ATS-KW-001 geography) — the ranking only decides
    ORDER. Pinned so a later "tighten the ranking" edit cannot quietly start
    deleting requirements."""
    from app.services.ats_engine import _content_tokens, _geographic_tokens

    jd = "Backend Engineer. Required skills: Python, Redis, pytest and Docker."
    expected = set(_content_tokens(jd)) - _geographic_tokens(jd)
    assert set(engine._extract_keywords(jd)) == expected


def test_13_the_number_of_required_keywords_is_unchanged(engine):
    """``keyword_match`` divides by ``len(keywords)``. This fix changes WHICH
    keywords are scored, never HOW MANY, so no score can move because the
    denominator changed size."""
    from app.services.ats_engine import _MAX_KEYWORDS, _content_tokens, _geographic_tokens

    for jd in (JD_LATE_REQUIREMENTS, JD_ACCOUNTING, JD_SKILL_LIST, JD_FLAT_PROSE):
        unique = set(_content_tokens(jd)) - _geographic_tokens(jd)
        assert len(engine._extract_keywords(jd)) == min(_MAX_KEYWORDS, len(unique)), jd[:40]


def test_12_every_returned_keyword_actually_occurs_in_the_posting(engine):
    """No keyword may be invented — the set is a selection from the posting."""
    from app.services.ats_engine import _content_tokens

    for jd in (JD_LATE_REQUIREMENTS, JD_ACCOUNTING, JD_SKILL_LIST, JD_FLAT_PROSE):
        present = set(_content_tokens(jd))
        assert set(engine._extract_keywords(jd)) <= present, jd[:40]


def test_10_the_posting_geography_is_still_excluded(engine):
    """ATS-KW-001 non-regression: the ranking change must not readmit the city."""
    jd = (
        "Senior Data Engineer — Melbourne, VIC, Australia.\n"
        "Location: Melbourne. Required skills: Python, Spark, Airflow, SQL.\n"
    )
    keywords = set(engine._extract_keywords(jd))
    assert not ({"melbourne", "vic", "australia", "location"} & keywords), sorted(keywords)
    assert {"python", "spark", "airflow", "sql"} <= keywords, sorted(keywords)


def test_9_no_weight_threshold_cap_or_formula_moved(engine):
    """ATS-KW-002 was fixed by scoring the RIGHT keywords, not by re-tuning the
    score. Every constant that could be used to flatter the number is pinned,
    including the keyword cap — raising it would keep the noise and merely keep
    more of it."""
    from app.services import ats_engine as module

    assert (module._WEIGHT_KEYWORD, module._WEIGHT_SEMANTIC, module._WEIGHT_EXPERIENCE) == (
        0.4,
        0.4,
        0.2,
    )
    assert module.REVIEW_THRESHOLD == 60.0
    assert module._MAX_KEYWORDS == 40
    assert module._DEGRADED_SEMANTIC_SCORE == 50.0
