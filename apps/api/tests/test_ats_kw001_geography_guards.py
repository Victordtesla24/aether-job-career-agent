"""ATS-KW-001 — guard tests for the geography filter in ``ats_engine``.

``test_gm2s15_ats_kw001_location_keyword.py`` proves the DEFECT (the posting's
location is scored as a required résumé keyword). This file guards the FIX
against the two ways a geography filter goes wrong:

* OVER-match — dropping a real skill because its name is also a place
  ("Phoenix" the framework, "Georgia" the typeface, "MS" the vendor prefix),
  or collapsing the required-keyword set to nothing;
* UNDER-match — failing to recognise a location that is stated the way real
  postings state them: a suburb no gazetteer will ever list, an ambiguous
  state abbreviation, a comma chain, an adjective ("Melbourne-based").

The safety argument the fix rests on is the EVERY-OCCURRENCE rule: a token is
geography only if every one of its occurrences in the posting sits inside a
detected geographic span. Tests 1-3 are that rule under attack.

Measured on the probe pair this finding was raised from (JD_PYTHON /
RESUME_MATCHING in ``test_ats_engine.py``, 2026-08-04): ``keyword_match``
94.44 -> 100.0 and ``overall`` 87.74 -> 89.96, with ``semantic_similarity``
(74.9077) and ``experience_gap`` (100.0) BYTE-IDENTICAL — no weight and no
threshold moved; the only change is that a city stopped counting as a skill.
"""
from __future__ import annotations

import pytest

#: "Phoenix" is a US city AND the Elixir web framework; "AZ" is a state
#: abbreviation AND nothing else here. The framework is named in a skills
#: list, i.e. OUTSIDE any geographic span.
JD_HOMONYM_FRAMEWORK = """
Backend Engineer
Location: Phoenix, AZ.
Required skills: Elixir, Phoenix, Ecto, PostgreSQL.
"""

#: "Georgia" is in the geographic vocabulary (a country and a US state) and is
#: also a typeface. The posting states it geographically once and as a design
#: skill once.
JD_HOMONYM_GAZETTEER = """
Brand Designer
Studio located in Atlanta, Georgia.
You will maintain our type system: Georgia, Helvetica and Inter.
"""

#: "MS" is an ambiguous abbreviation the fix classes as WEAK — it may only
#: count as geography inside a location chain. Here it prefixes a real product
#: while "SA" sits in an actual chain.
JD_WEAK_ABBREVIATION = """
Data Engineer
Location: Adelaide, SA.
Required skills: MS SQL Server, SSIS, Power BI.
"""

#: A suburb no gazetteer will ever carry, recognisable ONLY because it shares a
#: comma chain with a city that is. No location label and no carrier phrase, so
#: this isolates chain expansion.
JD_CHAIN_ONLY = """
Warehouse Systems Analyst
Candidates in Truganina, Melbourne, VIC are encouraged to apply.
Required skills: Python, SQL, Kafka.
"""

#: A location carried by prose alone, with a place name outside the vocabulary.
JD_CARRIER_ONLY = """
Platform Engineer
The team is based in Wodonga and you must be able to commute to Yarrawonga.
Required skills: Terraform, Kubernetes, Go.
"""

#: The geographic ADJECTIVE form, which the tokenizer keeps as one hyphenated
#: token ("melbourne-based") and a plain vocabulary lookup would miss.
JD_ADJECTIVE = """
Product Manager
We are a Melbourne-based scale-up.
Required skills: roadmapping, discovery, analytics.
"""

#: A posting with NO skill content at all — every content token is geography.
JD_ALL_GEOGRAPHY = "Melbourne Sydney Brisbane Perth Australia"


@pytest.fixture(scope="module")
def engine():
    from app.services.ats_engine import ATSEngine

    return ATSEngine()


# -- over-match guards -------------------------------------------------------


def test_1_a_framework_named_after_a_city_stays_a_required_keyword(engine):
    """OVER-MATCH GUARD. "Phoenix" appears twice: once inside the ``Location:``
    value and once in a skills list. Because one occurrence is outside every
    geographic span, it must survive as a required keyword — while "az", whose
    only occurrence is inside the location value, must not."""
    keywords = set(engine._extract_keywords(JD_HOMONYM_FRAMEWORK))
    assert "phoenix" in keywords, sorted(keywords)
    assert "elixir" in keywords and "ecto" in keywords, sorted(keywords)
    assert "az" not in keywords, sorted(keywords)


def test_2_chain_expansion_does_not_walk_a_non_geographic_list(engine):
    """OVER-MATCH GUARD on chain expansion. "Georgia, Helvetica and Inter" is a
    comma chain that merely BEGINS with a place name. Expansion must not walk
    it: a chain only expands when it holds two confirmed geographic elements,
    and this one holds exactly one.

    KNOWN LIMITATION, asserted nowhere so that fixing it is not a test
    failure: "georgia" itself IS dropped here. The every-occurrence rule
    protects a homonym only when the geographic evidence is POSITIONAL (a
    label, a carrier phrase, a chain) — a token in the geographic VOCABULARY
    is marked wherever it appears, so for those the protection is the
    curation of the vocabulary, not the rule. This is why city names that are
    also well-known technologies are deliberately absent from that vocabulary
    (test 1 is the case that matters in practice); see
    docs/delivery/ADR-ATS-KW-001-KEYWORD-CONTAMINATION.md."""
    keywords = set(engine._extract_keywords(JD_HOMONYM_GAZETTEER))
    assert "helvetica" in keywords, sorted(keywords)
    assert "inter" in keywords, sorted(keywords)
    assert "atlanta" not in keywords, sorted(keywords)


def test_3_an_ambiguous_abbreviation_outside_a_location_chain_is_not_geography(engine):
    """OVER-MATCH GUARD. "MS" must stay a keyword — it prefixes a product and
    is not in a location chain — while "SA", which shares one with Adelaide,
    must not."""
    keywords = set(engine._extract_keywords(JD_WEAK_ABBREVIATION))
    assert "ms" in keywords, sorted(keywords)
    assert "ssis" in keywords, sorted(keywords)
    assert "sa" not in keywords, sorted(keywords)
    assert "adelaide" not in keywords, sorted(keywords)


def test_4_a_posting_that_is_only_geography_still_yields_keywords(engine):
    """OVER-MATCH GUARD, degenerate case. Filtering must never empty the
    required-keyword set: ``_keyword_match`` returns a flat 0.0 for EVERY
    résumé when there are no keywords, which would be a silent, uniform,
    unexplained zero rather than an honest score."""
    keywords = engine._extract_keywords(JD_ALL_GEOGRAPHY)
    assert keywords, "geography filtering emptied the required-keyword set"


# -- under-match guards ------------------------------------------------------


def test_5_a_suburb_is_recognised_from_its_location_chain_alone(engine):
    """UNDER-MATCH GUARD. "Truganina" is in no vocabulary and has no label or
    carrier phrase in front of it — only a comma chain with Melbourne. The
    real skills in the same posting must be untouched."""
    keywords = set(engine._extract_keywords(JD_CHAIN_ONLY))
    assert "truganina" not in keywords, sorted(keywords)
    assert "melbourne" not in keywords, sorted(keywords)
    assert "vic" not in keywords, sorted(keywords)
    assert {"python", "sql", "kafka"} <= keywords, sorted(keywords)


def test_6_a_place_carried_by_prose_alone_is_recognised(engine):
    """UNDER-MATCH GUARD. "Wodonga"/"Yarrawonga" are in no vocabulary; only the
    carrier phrases "based in" and "commute to" identify them."""
    keywords = set(engine._extract_keywords(JD_CARRIER_ONLY))
    assert "wodonga" not in keywords, sorted(keywords)
    assert "yarrawonga" not in keywords, sorted(keywords)
    assert {"terraform", "kubernetes"} <= keywords, sorted(keywords)


def test_7_the_hyphenated_geographic_adjective_is_recognised(engine):
    """UNDER-MATCH GUARD. ``_TOKEN_RE`` keeps the hyphen, so "Melbourne-based"
    is ONE token and a plain vocabulary lookup misses it."""
    keywords = set(engine._extract_keywords(JD_ADJECTIVE))
    assert not [kw for kw in keywords if kw.startswith("melbourne")], sorted(keywords)
    assert "roadmapping" in keywords, sorted(keywords)


# -- the probe this finding was raised from ---------------------------------


def test_8_the_probe_pair_scores_a_clean_keyword_match(engine):
    """Regression pin on the exact pair GOV-021 cites. Every required skill in
    JD_PYTHON is restated verbatim in RESUME_MATCHING, so ``keyword_match``
    must be a literal 100 and the gap list must be empty. Measured before the
    fix: 94.44 with ``missing_keywords == ['sydney']``."""
    from tests.test_ats_engine import JD_PYTHON, RESUME_MATCHING

    score = engine.score(RESUME_MATCHING, JD_PYTHON)
    assert score.keyword_match == 100.0, (score.keyword_match, score.missing_keywords)
    assert score.missing_keywords == [], score.missing_keywords
    assert "sydney" not in set(engine._extract_keywords(JD_PYTHON))


def test_9_naming_the_city_in_the_resume_changes_nothing_either_way(engine):
    """The other direction of ATS-KW-001: now that location is not a scored
    keyword, a résumé that DOES restate the city must not gain anything from
    it. Together with test 8 this closes the keyword-stuffing incentive —
    writing the city in is worth exactly zero, and leaving it out costs
    exactly zero."""
    from tests.test_ats_engine import JD_PYTHON, RESUME_MATCHING

    without_city = engine.score(RESUME_MATCHING, JD_PYTHON)
    with_city = engine.score(RESUME_MATCHING + "\nBased in Sydney, NSW.", JD_PYTHON)
    assert without_city.keyword_match == with_city.keyword_match == 100.0
    assert without_city.matched_keywords == with_city.matched_keywords


#: The same JD in the shape `resume_tailor` sees it, plus a bullet that
#: genuinely mentions the city because the candidate genuinely worked there.
JD_TAILOR = """
Senior Data Engineer — Melbourne, VIC.
Location: Melbourne. Required skills: Python, Spark, Airflow, SQL.
"""
BULLET_ORIGINAL = "Led the Melbourne data platform team, building Python and Spark pipelines."
BULLET_DROPS_CITY = "Led the data platform team, building Python and Spark pipelines."
BULLET_DROPS_SKILL = "Led the Melbourne data platform team, building reporting pipelines."


def _ats_non_regression_hits(jd: str, original: str, rewrite: str) -> set[str]:
    """The ATS non-regression floor's own expression, verbatim.

    ``resume_tailor._validate`` rejects a rewrite when this is non-empty
    (``jd_terms & set(_content_tokens(original)) - set(_content_tokens(text))``
    — ``-`` binds tighter than ``&``).
    """
    from app.services.ats_engine import _content_tokens
    from app.services.resume_tailor import jd_keyword_terms

    return jd_keyword_terms(jd) & set(_content_tokens(original)) - set(_content_tokens(rewrite))


def test_11_dropping_the_city_from_a_bullet_is_not_an_ats_regression():
    """ATS-KW-001 in its SECOND location. ``resume_tailor``'s non-regression
    floor built its JD-keyword set from the same tokenizer, so a bullet that
    happened to name the city made the floor veto any rewrite that did not
    carry the city forward — blocking a truthful rewrite to defend a keyword
    that is not a skill and (post-fix) does not affect the score either.

    FAILS BEFORE: the floor reports ``{'melbourne'}`` and rejects the rewrite."""
    assert _ats_non_regression_hits(JD_TAILOR, BULLET_ORIGINAL, BULLET_DROPS_CITY) == set()


def test_12_dropping_a_real_skill_is_still_an_ats_regression():
    """Pin, the other direction: the floor must still do its job. A rewrite
    that drops "Python"/"Spark" — terms the original covered and the JD really
    asks for — must still be rejected."""
    hits = _ats_non_regression_hits(JD_TAILOR, BULLET_ORIGINAL, BULLET_DROPS_SKILL)
    assert "python" in hits and "spark" in hits, hits


def test_13_the_location_label_is_found_in_the_production_jd_shape(engine):
    """The JD the engine actually receives is ``fit_evidence.job_evidence_text``
    = ``title + " " + description + " " + requirements`` — ONE line, no newline
    after the title. A line-anchored label regex fires on the multi-line
    postings used in tests and never on the real thing, so this builds the JD
    through the production helper rather than hand-writing a string.

    Also pins the two ways that mid-line matching could go wrong. Both are
    checked by what SURVIVES, since the span is what does the damage:
    "Relocation:" must not be read as the label "location:" (which would open a
    span over "assistance provided"), and a mid-line dash must not open one
    over ordinary prose ("a converted warehouse"). Note "relocation" itself is
    correctly absent from the keywords — it is location vocabulary, never a
    skill — so its own presence cannot be the assertion."""
    from app.services.fit_evidence import job_evidence_text

    job = {
        "title": "Elixir Engineer",
        "description": (
            "Location: Phoenix, AZ. Relocation: assistance provided. "
            "The office - a converted warehouse - is great. "
            "Build with Elixir and Phoenix LiveView."
        ),
        "requirements": ["Elixir", "Oban"],
    }
    keywords = set(engine._extract_keywords(job_evidence_text(job)))
    assert "az" not in keywords, sorted(keywords)
    assert "phoenix" in keywords, sorted(keywords)
    assert {"assistance", "provided"} <= keywords, sorted(keywords)
    assert {"converted", "warehouse"} <= keywords, sorted(keywords)


def test_10_the_fix_moved_no_weight_and_no_threshold(engine):
    """ATS-KW-001 was fixed by removing a non-skill from the keyword set, NOT
    by re-tuning the score. Pinned so a later "make the number nicer" edit to
    the weights, the review threshold or the keyword cap fails loudly here."""
    from app.services import ats_engine as module

    assert (module._WEIGHT_KEYWORD, module._WEIGHT_SEMANTIC, module._WEIGHT_EXPERIENCE) == (
        0.4,
        0.4,
        0.2,
    )
    assert module.REVIEW_THRESHOLD == 60.0
    assert module._MAX_KEYWORDS == 40
    assert module._DEGRADED_SEMANTIC_SCORE == 50.0
