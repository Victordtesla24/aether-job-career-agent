"""R-01 / R-02 — the geography filter must never delete a real requirement.

ATS-KW-001 stopped scoring the posting's LOCATION as a required résumé keyword.
It did so with three positional signals (a ``Location:`` label, a closed set of
prose carriers, a comma chain) plus a place-name vocabulary, and rested its
whole safety argument on an EVERY-OCCURRENCE rule.

Two ways that shipped wrong, both measured on HEAD before this file existed:

R-01 (CRITICAL) — the location VALUE span was "80 characters, or up to the
first stop character", and the JD the engine actually receives is
``fit_evidence.job_evidence_text`` = ``title + " " + description + " " +
" ".join(requirements)``: requirement items joined by a BARE SPACE, with no
punctuation between them. A requirements array whose first item mentions
relocation therefore puts the carrier phrase immediately in front of the entire
tech stack with no stop character anywhere, and the span swallowed all of it.
Measured on HEAD 9a338c8 with the reproduction in
:data:`REPRO_REQUIREMENTS` below::

    required-keyword set  -> ['data', 'engineer', 'senior', 'products']
    stack terms scored    -> NONE (all 9 swallowed)
    keyword_match         -> 100.0   missing_keywords -> []

i.e. a candidate with NONE of the posting's stack was told they were a perfect
keyword match with zero gaps. That is worse than the defect the filter was
added to fix: under-filtering leaves a cosmetic entry in the gap list,
over-filtering FABRICATES a perfect match.

R-02 (MAJOR) — vocabulary tokens were seeded at EVERY occurrence, which makes
the every-occurrence rule VACUOUS for exactly the tokens it was advertised to
protect: a term in ``_GEO_STRONG_TOKENS`` was deleted unconditionally however
the posting used it.

The ORIGINAL ATS-KW-001 corpus could not find either: every JD in it terminates
the location with punctuation, and every homonym it tests ("Phoenix") is one
the vocabulary deliberately omits, so it exercises the positional signals and
never the vocabulary. (The finding as filed said deleting the ``.`` after
"Melbourne" in that file's ``JD_TAILOR`` fixture would flip it. Checked against
the 9a338c8 engine: it does not — the window closes on the ``:`` after
"Required skills" instead, and both words it then swallows are stopwords. The
corpus's blindness is real; that particular fixture is just a poor
demonstration of it. See ADR-R01 §1.)

THE INVARIANT THESE TESTS EXIST TO PIN: no JD shape may cause a real
requirement to be deleted from the required-keyword set by the geography
filter. Where the span is ambiguous the filter must FAIL SAFE and keep the
tokens.
"""
from __future__ import annotations

import pytest

#: The exact reproduction. Note the FIRST requirement mentions relocation, and
#: ``job_evidence_text`` joins the items with a bare space.
REPRO_REQUIREMENTS = [
    "Relocation to Melbourne supported",
    "Snowflake",
    "dbt",
    "Airflow",
    "Spark",
    "Kafka",
    "Python",
    "SQL",
    "Terraform",
    "AWS",
]
REPRO_STACK = (
    "snowflake",
    "dbt",
    "airflow",
    "spark",
    "kafka",
    "python",
    "sql",
    "terraform",
    "aws",
)

#: A résumé that carries the posting's generic TITLE words and none of its
#: stack. This is what turns the swallowed span into a fabricated 100.
REPRO_RESUME = """
Senior Data Engineer. Seven years building data products for consumer
marketplaces. Led a small team, owned the reporting layer end to end, and
improved delivery cadence. Bachelor of Science.
"""


@pytest.fixture(scope="module")
def engine():
    from app.services.ats_engine import ATSEngine

    return ATSEngine()


def _production_jd(title: str, description: str, requirements: list[str]) -> str:
    """The JD string production actually scores, built by the production helper."""
    from app.services.fit_evidence import job_evidence_text

    return job_evidence_text(
        {"title": title, "description": description, "requirements": requirements}
    )


def _keywords(engine, jd: str) -> set[str]:
    return set(engine._extract_keywords(jd))


# -- R-01: the production space-joined requirements shape ---------------------


def test_r01_1_space_joined_requirements_keep_the_whole_stack(engine):
    """FAILS BEFORE: every one of the nine stack terms is swallowed by the
    carrier span opened at "Relocation to " and the required-keyword set
    collapses to ``['data', 'engineer', 'senior', 'products']``."""
    jd = _production_jd("Senior Data Engineer", "We build data products.", REPRO_REQUIREMENTS)
    keywords = _keywords(engine, jd)
    missing = [term for term in REPRO_STACK if term not in keywords]
    assert not missing, (
        f"geography filter deleted real requirements {missing} from {sorted(keywords)}"
    )
    assert "melbourne" not in keywords, sorted(keywords)


def test_r01_2_the_reproduction_is_not_reported_as_a_perfect_match(engine):
    """The user-facing consequence, pinned directly. FAILS BEFORE:
    ``keyword_match == 100.0`` and ``missing_keywords == []`` for a résumé
    containing none of the posting's stack."""
    jd = _production_jd("Senior Data Engineer", "We build data products.", REPRO_REQUIREMENTS)
    score = engine.score(REPRO_RESUME, jd)

    assert score.keyword_match != 100.0, (
        "a résumé with none of the posting's stack was scored a PERFECT keyword "
        f"match; missing_keywords={score.missing_keywords}"
    )
    assert score.missing_keywords != [], (
        "a résumé with none of the posting's stack was reported to have ZERO "
        f"keyword gaps; matched={score.matched_keywords}"
    )
    # And the gaps reported must be the real ones, not a residue.
    assert {"snowflake", "airflow", "terraform"} <= set(score.missing_keywords), (
        score.missing_keywords
    )


def test_r01_3_a_carrier_span_stops_at_the_first_non_place_token(engine):
    """The narrow root cause, isolated from ``job_evidence_text``. A carrier
    phrase followed by a place and then ordinary prose with NO punctuation must
    mark only the place. FAILS BEFORE: the span runs a full 80 characters."""
    from app.services.ats_engine import _geographic_tokens

    jd = (
        "Platform Engineer We are based in Wodonga Kubernetes Terraform "
        "Ansible Prometheus Grafana Postgres"
    )
    geography = _geographic_tokens(jd)
    assert "wodonga" in geography, sorted(geography)
    for term in ("kubernetes", "terraform", "ansible", "prometheus", "grafana", "postgres"):
        assert term not in geography, (term, sorted(geography))


# -- R-01: header and separator shapes the original corpus never contained ----


def test_r01_4_title_dash_city_state_header_keeps_the_title_words(engine):
    """``Title - City, ST`` is the single most common posting headline there is.
    FAILS BEFORE: " - " counts as a location-chain separator, so the chain
    ``[engineer, melbourne, vic]`` holds two confirmed places and expansion
    walks LEFT over the job title, deleting "engineer" from the keyword set."""
    jd = _production_jd(
        "Senior Data Engineer - Melbourne, VIC",
        "Own the warehouse.",
        ["Python", "Spark", "Airflow"],
    )
    keywords = _keywords(engine, jd)
    assert "engineer" in keywords, sorted(keywords)
    assert {"python", "spark", "airflow"} <= keywords, sorted(keywords)
    assert "melbourne" not in keywords and "vic" not in keywords, sorted(keywords)


@pytest.mark.parametrize(
    "separator",
    ["·", "•", "|", "–"],
    ids=["middot", "bullet", "pipe", "endash"],
)
def test_r01_5_single_line_separated_postings_keep_their_stack(engine, separator):
    """Bullet / middot / pipe separated one-liners. FAILS BEFORE: none of these
    characters closes a location value, so "Based in Melbourne <sep> Python
    <sep> Spark ..." is swallowed wholesale."""
    jd = (
        f"Data Engineer {separator} Based in Melbourne {separator} Python "
        f"{separator} Spark {separator} Airflow {separator} dbt {separator} Snowflake"
    )
    keywords = _keywords(engine, jd)
    missing = [
        term for term in ("python", "spark", "airflow", "dbt", "snowflake")
        if term not in keywords
    ]
    assert not missing, (separator, missing, sorted(keywords))
    assert "melbourne" not in keywords, sorted(keywords)


def test_r01_6_a_location_with_no_trailing_punctuation_at_all(engine):
    """A ``Location:`` label whose value is not terminated by any punctuation —
    the shape produced whenever a board's location field is concatenated onto
    the next field. FAILS BEFORE: the span runs to the next stop character,
    which is 80 characters away or absent entirely."""
    jd = (
        "Location: Melbourne Required skills Python Spark Airflow SQL "
        "Terraform Kafka Snowflake"
    )
    keywords = _keywords(engine, jd)
    missing = [
        term for term in ("python", "spark", "airflow", "sql", "terraform", "kafka", "snowflake")
        if term not in keywords
    ]
    assert not missing, (missing, sorted(keywords))
    assert "melbourne" not in keywords, sorted(keywords)


def test_r01_7_chain_expansion_refuses_a_chain_it_cannot_account_for(engine):
    """Chain expansion absorbs the unlisted PARTS of one location ("Truganina").
    It must not absorb a comma list that merely happens to hold two places.
    FAILS BEFORE: two confirmed elements license walking the chain to its end,
    so "Python" and "Spark" are deleted."""
    jd = "Data Engineer We hire across Sydney, Melbourne, Python, Spark, Airflow teams"
    keywords = _keywords(engine, jd)
    for term in ("python", "spark", "airflow"):
        assert term in keywords, (term, sorted(keywords))


def test_r01_8_the_unlisted_allowance_is_not_spent_on_a_named_skill(engine):
    """A location value may absorb ONE token no gazetteer carries — that is what
    makes "based in Wodonga" work. It must not spend that allowance on the first
    item of the NEXT field.

    FAILS BEFORE: the 80-character window takes the whole list. Also caught the
    first implementation of this fix, which spent the one-unlisted allowance on
    "Kubernetes" because a chain separator followed the city."""
    jd = "Platform Engineer Location: Melbourne, Kubernetes, Terraform, Go, Rust"
    keywords = _keywords(engine, jd)
    for term in ("kubernetes", "terraform", "rust"):
        assert term in keywords, (term, sorted(keywords))
    assert "melbourne" not in keywords, sorted(keywords)


# -- R-02: the every-occurrence rule must not be vacuous ---------------------


@pytest.mark.parametrize(
    ("jd", "term"),
    [
        (
            "Release Engineer We ship binaries for linux, windows and darwin. "
            "Build with Bazel and Rust.",
            "darwin",
        ),
        ("Frontend Engineer Build the IDE with Monaco, React and TypeScript.", "monaco"),
        ("Systems Engineer Experience with Berkeley DB, LMDB and RocksDB required.", "berkeley"),
        ("Brand Designer Our type system: Georgia, Helvetica and Inter.", "georgia"),
        ("Copywriter You will polish long-form copy and edit for tone.", "polish"),
        ("Field Technician Service Milwaukee and DeWalt power tools daily.", "milwaukee"),
    ],
    ids=["darwin", "monaco", "berkeley", "georgia", "polish", "milwaukee"],
)
def test_r02_1_vocabulary_homonyms_are_not_deleted_unconditionally(engine, jd, term):
    """FAILS BEFORE for all six: ``_GEO_STRONG_TOKENS`` members are seeded at
    EVERY occurrence, so the every-occurrence rule can never save them and they
    are deleted however the posting uses them."""
    keywords = _keywords(engine, jd)
    assert term in keywords, (term, sorted(keywords))


def test_r02_2_a_place_named_in_a_skills_list_survives(engine):
    """The de-vacuumed rule, on a token that REMAINS in the vocabulary.
    "Geneva" is a Swiss city and a classic system typeface. Named inside a
    separator run that already holds two skill-evidenced non-place members it
    must keep its keyword status. FAILS BEFORE: vocabulary membership alone
    deletes it."""
    jd = "Brand Designer Our type system uses Verdana, Tahoma and Geneva across the suite."
    keywords = _keywords(engine, jd)
    assert "geneva" in keywords, sorted(keywords)


def test_r02_3_a_language_competency_is_not_a_location(engine):
    """A demonym in a posting is overwhelmingly a LANGUAGE the candidate must
    speak — the same reasoning ADR-ATS-KW-001 already used to keep "english"
    out of the vocabulary, and which was never applied to any other language.

    FAILS BEFORE: "spanish" is in the vocabulary and is therefore deleted at
    every occurrence, so a bilingual requirement vanishes from the scored set
    and a monolingual candidate is never told they are missing it."""
    jd = _production_jd(
        "Customer Support Specialist",
        "Support our LATAM customers.",
        ["Fluent Spanish", "Zendesk", "Salesforce"],
    )
    keywords = _keywords(engine, jd)
    assert "spanish" in keywords, sorted(keywords)


def test_r02_4_a_real_location_is_still_removed(engine):
    """The other direction — R-02's fix must not resurrect ATS-KW-001. A city
    stated as the posting's location is still not a required résumé keyword."""
    jd = _production_jd(
        "Senior Backend Engineer",
        "Location: Sydney. Join our platform team.",
        ["Python", "PostgreSQL", "Kubernetes"],
    )
    keywords = _keywords(engine, jd)
    assert "sydney" not in keywords, sorted(keywords)
    assert {"python", "postgresql", "kubernetes"} <= keywords, sorted(keywords)


# -- the invariant, stated as a test -----------------------------------------


#: Shapes chosen to attack the span from every direction the corpus missed.
INVARIANT_SHAPES = [
    ("space-joined requirements", "Senior Data Engineer", "We build data products.",
     REPRO_REQUIREMENTS),
    ("relocation first, no punctuation", "Data Engineer", "Great team.",
     ["Relocation to Perth available", "Kubernetes", "Helm", "ArgoCD"]),
    ("carrier mid-requirements", "Analyst", "Reporting role.",
     ["SQL", "Willing to commute to Parramatta daily", "Tableau", "PowerBI"]),
    ("label with no terminator", "Engineer", "Location: Brisbane Skills Python Go Rust", []),
    ("hybrid carrier", "Engineer", "Hybrid in Adelaide Python Django Celery Redis", []),
    ("office carrier", "Engineer", "Our office in Hobart Terraform Packer Vault Consul", []),
    ("working-from carrier", "Engineer", "Working from Canberra Scala Akka Kafka Flink", []),
    ("live-in carrier", "Nurse", "You must live in Geelong Cannulation Triage Phlebotomy", []),
]


@pytest.mark.parametrize(
    ("label", "title", "description", "requirements"),
    INVARIANT_SHAPES,
    ids=[shape[0] for shape in INVARIANT_SHAPES],
)
def test_invariant_the_filter_deletes_only_geography(
    engine, label, title, description, requirements
):
    """THE INVARIANT. For each shape, every token the geography filter removes
    must itself be geography — a place name, a region abbreviation, or location
    vocabulary. A technology or competency term must never be in that set."""
    from app.services.ats_engine import _content_tokens, _geographic_tokens

    jd = _production_jd(title, description, requirements)
    removed = _geographic_tokens(jd) & set(_content_tokens(jd))
    fabrication_risk = removed & _REAL_REQUIREMENT_TERMS
    assert not fabrication_risk, (
        f"[{label}] geography filter deleted real requirement terms "
        f"{sorted(fabrication_risk)}; removed={sorted(removed)}"
    )


#: Every technology / competency term used in :data:`INVARIANT_SHAPES`. None of
#: these is a place under any reading, so any one of them appearing in the
#: filter's output is an over-filter and a fabrication risk.
_REAL_REQUIREMENT_TERMS = {
    "snowflake", "dbt", "airflow", "spark", "kafka", "python", "sql", "terraform", "aws",
    "kubernetes", "helm", "argocd", "tableau", "powerbi", "go", "rust", "django", "celery",
    "redis", "packer", "vault", "consul", "scala", "akka", "flink", "cannulation", "triage",
    "phlebotomy", "skills", "available", "daily",
}
