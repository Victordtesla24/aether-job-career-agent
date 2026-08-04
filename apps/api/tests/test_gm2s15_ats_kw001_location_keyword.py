"""GOLD-MASTER-V2 §15 STEP 2 — ATS-KW-001: the job's LOCATION is scored as a
required résumé keyword.

REPAIR NOTE (2026-08-04, §15 step 2 repair pass): the previous version of
this file exercised ONLY city/state/country tokens (Melbourne, VIC,
Australia). Between that version and this one, a geography filter
(``_geographic_tokens``, ats_engine.py:466-551) was added to the engine and
now correctly strips place names from the required-keyword set — so tests
1/2/4 as originally written now PASS. That is a genuine partial fix, but it
does **not** cover the live-confirmed trigger: production evidence
(`uat/reports/evidence/gold-master-v2/wc/TAILORING-EFFICACY-PROBE.md` §7)
shows the defect firing on job ``ced2ed2e5e5a46d9bfa04f625`` (Kinetic,
"Technical Product Owner - Workday") via the **literal common English word
"location"** appearing in ordinary JD prose ("...Melbourne location with
true flexibility...") — not via a city name. That run's real
``gapKeywords``/``unreachableKeywords`` contained the bare token
``location``, which no honest résumé bullet can ever contain as a skill, so
it is a **permanent, unclosable miss** for every candidate on that posting
and ~3% of a 60-job live sample generally (§7 of the probe doc).

WHY THE EXISTING GEOGRAPHY FILTER DOES NOT CATCH IT: ``_geographic_tokens``
marks a token as geography only via (1) an explicit "Location:" LABEL line
(``_GEO_LABEL_RE``, ats_engine.py:391-396 — requires a real ``:``/``-``
separator after the word, and its own docstring says the word "location" in
prose "never opens a span"), (2) a closed set of prose CARRIERS ("based in
X", "located in X", ats_engine.py:400-410), or (3) a match against the
place-name vocabulary (``_GEO_STRONG_TOKENS`` / ``_GEO_PHRASES`` /
``_GEO_WEAK_TOKENS``). The word "location" itself is not a place name and is
not preceded by a label/carrier in ordinary prose like "Melbourne location
with true flexibility" (the city noun "Melbourne" modifies "location"; there
is no "Location:" or "based in" trigger), so it is never marked geographic —
it survives ``_content_tokens`` (it is not in ``_STOPWORDS`` either,
ats_engine.py:77-97) and is ranked as an ordinary content token by the
TF-IDF extractor, same as a real skill.

Reproduced locally against current code (2026-08-04, this file's fail-before
run) using a JD modelled on the live Kinetic posting: for a JD containing
the sentence "Melbourne location with true flexibility for the right
candidate", ``_extract_keywords`` includes the bare token ``location``
(measured keyword set includes it alongside ``melbourne`` being correctly
absent), and a résumé restating every required skill verbatim scores
``missing_keywords`` containing ``location`` — an unclosable, structurally
unfair miss.

Fail-before (current code, as of 2026-08-04): tests 6 and 7 below (the new
"bare word location" tests) FAIL. Tests 1-5 (city/state/country geography,
added by the earlier partial fix) and test 8 (genuine missing skill still
flagged, added by this repair) already PASS — pinned here as regression
guards so the eventual fix for the "location" word cannot satisfy this file
by gutting keyword scoring generally or by re-breaking the city-name fix.
"""
from __future__ import annotations

import pytest

#: A JD that states the same three geography tokens three times — the
#: realistic shape PROD-UAT-2026-08-03 / ATS-KW-001 describes (title line,
#: "Location:" line, "must be based in" line) — plus a tight, unambiguous
#: skills list so the only tokens at stake are geography vs. genuine skills.
JD_LOCATION = """
Senior Data Engineer — Melbourne, VIC, Australia.
Location: Melbourne. Applicants must be based in Melbourne, VIC.
Required skills: Python, Spark, Snowflake, dbt, Airflow, SQL.
5+ years of experience required.
"""

#: Restates every required skill verbatim; never mentions the city/state/
#: country at all. A genuinely "perfect content match" on everything the JD
#: actually needs from a candidate.
RESUME_PERFECT_NO_CITY = """
Senior Data Engineer with 6 years of experience.
Skilled in Python, Spark, Snowflake, dbt, Airflow, and SQL.
"""

#: Identical skill content to RESUME_PERFECT_NO_CITY, with one sentence
#: appended that repeats the JD's geography tokens. Isolates the effect of
#: the city mention alone — nothing about job-relevant content changes.
RESUME_PERFECT_WITH_CITY = RESUME_PERFECT_NO_CITY + " Based in Melbourne, VIC, Australia."

#: Drops two genuine required skills (Airflow, dbt) but DOES restate the
#: city — the control for "the fix must not gut real keyword scoring": a
#: résumé that mentions the city but is missing real skills must still be
#: flagged for those skills.
RESUME_MISSING_REAL_SKILLS_STATES_CITY = """
Senior Data Engineer with 6 years of experience, based in Melbourne, VIC.
Skilled in Python, Spark, Snowflake, and SQL.
"""

#: Every geography token this JD actually contains, lowercased to match the
#: engine's token normalisation (``_content_tokens`` lowercases everything).
LOCATION_TOKENS = {"melbourne", "vic", "australia"}

#: The JD's genuinely-required skill tokens — the ones a keyword-match score
#: exists to check for in the first place.
REQUIRED_SKILL_TOKENS = {"python", "spark", "snowflake", "dbt", "airflow", "sql"}


@pytest.fixture(scope="module")
def engine():
    from app.services.ats_engine import ATSEngine

    return ATSEngine()


def test_1_location_tokens_must_not_enter_the_required_keyword_set(engine):
    """Root cause, city/state/country flavour. ``_extract_keywords`` must not
    surface pure geography as a "required keyword" at all — a city is not a
    skill.

    PASSES TODAY (2026-08-04 repair pass): ``_geographic_tokens``
    (ats_engine.py:466-551) was added since this file's original version and
    now strips ``{"melbourne", "vic", "australia"}`` from the required-keyword
    set correctly. Kept as a regression pin — see test_6/test_7 below for the
    live-confirmed trigger this file originally missed (the bare word
    "location").
    """
    keywords = set(engine._extract_keywords(JD_LOCATION))
    leaked = LOCATION_TOKENS & keywords
    assert not leaked, (
        f"location tokens {leaked} were extracted as required résumé "
        f"keywords from a JD (ATS-KW-001); full keyword set={sorted(keywords)}"
    )


def test_2_missing_keyword_list_a_user_sees_contains_no_pure_geography(engine):
    """The user-facing gap list, city/state/country flavour. A candidate who
    is a perfect skill match but never repeats the city must not see the city
    listed as something they are "missing".

    PASSES TODAY (2026-08-04 repair pass): ``_geographic_tokens`` correctly
    excludes ``melbourne``/``vic``/``australia`` from ``missing_keywords``.
    Kept as a regression pin — see test_6/test_7 for the bare word
    "location", which this test does not cover.
    """
    score = engine.score(RESUME_PERFECT_NO_CITY, JD_LOCATION)
    geography_in_gap = LOCATION_TOKENS & set(score.missing_keywords)
    assert not geography_in_gap, (
        f"missing_keywords surfaced pure geography as a resume gap: "
        f"{geography_in_gap}; full missing set={sorted(score.missing_keywords)}"
    )


def test_3_genuine_skill_keywords_are_still_extracted_and_scored(engine):
    """Pin: the fix must not gut keyword scoring generally — real skills stay
    required keywords. Passes today AND must keep passing after the fix."""
    keywords = set(engine._extract_keywords(JD_LOCATION))
    assert REQUIRED_SKILL_TOKENS <= keywords, (
        f"genuine skill tokens dropped out of the required-keyword set: "
        f"{REQUIRED_SKILL_TOKENS - keywords}"
    )


def test_4_keyword_match_is_unaffected_by_restating_the_city(engine):
    """THE load-bearing assertion. Two résumés with byte-for-byte identical
    job-relevant (skill) content, differing ONLY by one sentence that repeats
    the JD's city/state/country, must score identically on keyword_match —
    because location is not a scored keyword at all once fixed. This cannot
    be satisfied by a rename or by only touching ``missing_keywords`` cosmetically;
    it requires the location tokens to be excluded from the coverage
    denominator/numerator entirely.

    PASSES TODAY (2026-08-04 repair pass): ``_geographic_tokens`` excludes
    "Melbourne, VIC, Australia" from the coverage denominator entirely, so
    both résumés score identically. Kept as a regression pin.
    """
    no_city = engine.score(RESUME_PERFECT_NO_CITY, JD_LOCATION)
    with_city = engine.score(RESUME_PERFECT_WITH_CITY, JD_LOCATION)
    assert no_city.keyword_match == with_city.keyword_match, (
        "keyword_match changed purely because the résumé repeated the job's "
        f"city/state/country: no_city={no_city.keyword_match} "
        f"with_city={with_city.keyword_match} — location is being scored as "
        f"a required keyword (ATS-KW-001)"
    )


def test_5_a_genuinely_missing_skill_is_still_flagged_regardless_of_city(engine):
    """Pin, the other direction: a résumé that DOES restate the city but is
    missing real required skills must still show those skills as missing —
    the fix must not accidentally exempt anything the city sentence touches.
    Passes today AND must keep passing after the fix."""
    score = engine.score(RESUME_MISSING_REAL_SKILLS_STATES_CITY, JD_LOCATION)
    assert "airflow" in score.missing_keywords, score.missing_keywords
    assert "dbt" in score.missing_keywords, score.missing_keywords


# -- The LIVE-CONFIRMED trigger: the bare word "location" in ordinary prose --
#
# Modelled directly on the JD text that actually fired this defect in
# production (job ``ced2ed2e5e5a46d9bfa04f625``, Kinetic "Technical Product
# Owner - Workday" — TAILORING-EFFICACY-PROBE.md §7): the sentence
# "...Melbourne location with true flexibility..." is ordinary prose, not a
# "Location:" label and not a "based in X" carrier, so ``_geographic_tokens``
# never marks the word "location" itself as geography — only "melbourne" is
# caught by the existing (city-name) fix.
JD_LOCATION_WORD = """
Senior Technical Product Owner — Melbourne, VIC.
Melbourne location with true flexibility for the right candidate.
Required skills: Python, Kubernetes, SQL, Agile, Roadmapping.
5+ years of experience required.
"""

#: Restates every required skill AND the city, but — like any honest résumé
#: — never contains the bare noun "location" as an achievement.
RESUME_LOCATION_WORD_ALL_SKILLS = """
Senior Technical Product Owner with 6 years of experience, based in
Melbourne, VIC.
Skilled in Python, Kubernetes, SQL, Agile, and Roadmapping.
"""

#: Same as above but drops one genuine required skill ("Agile") — the
#: control for "the fix must not over-suppress": a résumé missing a real
#: skill must still be flagged for it once "location" is excluded.
RESUME_LOCATION_WORD_MISSING_SKILL = """
Senior Technical Product Owner with 6 years of experience, based in
Melbourne, VIC.
Skilled in Python, Kubernetes, SQL, and Roadmapping.
"""


def test_6_bare_word_location_must_not_enter_the_required_keyword_set(engine):
    """THE live-confirmed trigger. ``_extract_keywords`` must not surface the
    generic English word "location" as a "required keyword" just because it
    appears in ordinary JD prose — it is not a skill, and no honest résumé
    bullet can ever contain it as an achievement.

    FAILS TODAY (measured 2026-08-04): ``_extract_keywords(JD_LOCATION_WORD)``
    includes the bare token ``"location"`` — confirmed live in production on
    job ``ced2ed2e5e5a46d9bfa04f625`` (TAILORING-EFFICACY-PROBE.md §7), where
    it ranked 25th of 40 keywords for the real JD. The existing geography
    filter (``_geographic_tokens``, ats_engine.py:466-551) only recognises
    place NAMES and label/carrier phrases ("Location:", "based in X") — it
    has no rule for the word "location" occurring as an ordinary noun, so
    this token sails through ``_content_tokens`` untouched (it is also absent
    from ``_STOPWORDS``, ats_engine.py:77-97).
    """
    keywords = set(engine._extract_keywords(JD_LOCATION_WORD))
    assert "location" not in keywords, (
        "the bare word 'location' was extracted as a required résumé "
        f"keyword from ordinary JD prose (ATS-KW-001 live trigger); "
        f"full keyword set={sorted(keywords)}"
    )


def test_7_missing_keyword_list_does_not_contain_the_bare_word_location(engine):
    """The user-facing gap list, live-confirmed flavour. A candidate who
    restates every required skill (and even the city) must not see the bare
    word "location" listed as something they are "missing" — it is a
    permanent, unclosable miss for every candidate on such a posting.

    FAILS TODAY (measured 2026-08-04): ``missing_keywords`` includes
    ``"location"`` even though every required SKILL (and the city) is
    present in the résumé — this is exactly what reached
    ``gapKeywords``/``unreachableKeywords`` in the live production run
    (resume_id c11a96463377bc6d24bf9b429, TAILORING-EFFICACY-PROBE.md §7).
    """
    score = engine.score(RESUME_LOCATION_WORD_ALL_SKILLS, JD_LOCATION_WORD)
    assert "location" not in score.missing_keywords, (
        "missing_keywords surfaced the bare word 'location' as a résumé gap "
        f"(ATS-KW-001 live trigger); full missing set={sorted(score.missing_keywords)}"
    )


def test_8_a_genuinely_missing_skill_is_still_flagged_in_the_location_word_jd(engine):
    """Pin: the fix for the bare word "location" must not over-suppress —
    a résumé genuinely missing a required skill in this same JD must still
    show that skill as missing. Passes today AND must keep passing after the
    fix (guards against a fix that satisfies test_6/test_7 by gutting keyword
    scoring generally, e.g. dropping every token TF-IDF-adjacent to
    "location")."""
    score = engine.score(RESUME_LOCATION_WORD_MISSING_SKILL, JD_LOCATION_WORD)
    assert "agile" in score.missing_keywords, score.missing_keywords
