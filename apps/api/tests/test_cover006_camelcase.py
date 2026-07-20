"""MV-cover-letter-studio-006 RE-OPENED / NF-final-PII-001 — CamelCase
concatenation artifacts in the JD Keyword Coverage panel.

Live-verify on prod found the panel still surfacing HTML-scrape CamelCase
CONCATENATION artifacts ("ManagerLocation", "EngineerLocation",
"ResponsibilitiesBuild", "EmployerShare") as TOP chips for the Empire-Life JD
pattern (and others). Root cause: ``_skill_score`` rewarded a token's
internal uppercase (+45) the same whether it came from a legit mixed-case
tech term (PostgreSQL, JavaScript) or from an HTML-scrape gluing where a
heading/label word lost its whitespace against the next word (e.g.
"Manager" + "Location" -> "ManagerLocation").

The fix (in ``app.routers.cover_letters``):
  - ``_is_camel_concatenation_artifact`` detects a token whose CamelCase split
    yields 2+ segments that are ALL standalone common-English/JD-boilerplate
    words -> judged an artifact and dropped entirely from the keyword panel
    (and never rewarded for internal uppercase in ``_skill_score``).
  - A known-tech allowlist (``_MIXED_CASE_TECH_ALLOWLIST``) is checked FIRST
    so legit mixed-case tech terms (JavaScript, TypeScript, PostgreSQL,
    GraphQL, MongoDB, GitHub, GitLab, OAuth2, log4j2, ...) are never treated
    as artifacts, even though their own CamelCase split ("Java"+"Script")
    can look just as word-like as a genuine gluing artifact.

This file is deliberately kept SEPARATE from
``test_mv_clstudio_j_residuals.py`` (owned by another concurrent fixer
working the résumé-seeding residuals in that same module) to avoid a merge
collision.

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock python3 -m pytest \
        tests/test_cover006_camelcase.py -q
"""
from __future__ import annotations

import pytest

from app.routers.cover_letters import (
    _is_camel_concatenation_artifact,
    _jd_keywords,
    _keyword_coverage,
)

_CONCATENATION_ARTIFACTS = (
    "ManagerLocation",
    "EngineerLocation",
    "ResponsibilitiesBuild",
    "EmployerShare",
)

_LEGIT_MIXED_CASE_TECH = (
    "JavaScript",
    "TypeScript",
    "PostgreSQL",
    "GraphQL",
    "MongoDB",
    "Node.js",
    "GitHub",
    "GitLab",
    "OAuth2",
)

# NF-final-resid-001 (final adversarial sweep, residual of NF-final-PII-001 /
# re-opened MV-cover-letter-studio-006): the exact 6 city+label gluings the
# sweep found leaking into prod's JD Keyword Coverage panel as TOP chips.
# _ARTIFACT_SPLIT_WORDS held country names but no city names, so the old
# "EVERY segment must be a standalone boilerplate word" rule never caught a
# real place name glued to a structural JD label.
_CITY_LABEL_ARTIFACTS = (
    "SydneySalary",
    "MelbourneSalary",
    "BrisbaneLocation",
    "AdelaideSalary",
    "PerthSalary",
    "CanberraLocation",
)

# Adversarial variants of my own design (NOT enumerated by the sweep): other
# global place names / proper nouns glued to the same JD structural labels.
# The fix must generalize — catching these WITHOUT a city allowlist — or it
# is just more whack-a-mole.
_ADVERSARIAL_LABEL_ARTIFACTS = (
    "LondonSalary",
    "TorontoLocation",
    "AucklandBenefits",
    "DublinRequirements",
    "ChicagoDepartment",
    "BerlinCompensation",
    "TokyoQualifications",
    "ParisEmployer",
    "MumbaiShare",
)

# False-positive guards: legitimate mixed-case tech/product terms whose
# CamelCase split happens to contain a segment that is ALSO one of the JD
# structural-label words above (Share/Location) — a "flag on ANY label
# segment" rule must not treat these as scrape-gluing artifacts.
_FALSE_POSITIVE_TECH_GUARDS = (
    "SlideShare",   # Slide + Share — a real product name
    "SharePoint",   # Share + Point — Microsoft SharePoint
    "GeoLocation",  # Geo + Location — the browser Geolocation API
)


@pytest.mark.parametrize("artifact", _CONCATENATION_ARTIFACTS)
def test_camel_concatenation_artifact_is_detected(artifact):
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} is an HTML-scrape concatenation artifact and must be "
        "detected"
    )


@pytest.mark.parametrize("term", _LEGIT_MIXED_CASE_TECH)
def test_legit_mixed_case_tech_is_not_flagged_as_artifact(term):
    assert not _is_camel_concatenation_artifact(term), (
        f"{term!r} is a legitimate mixed-case tech term and must NOT be "
        "flagged as a concatenation artifact"
    )


def test_keyword_coverage_drops_camel_concatenation_artifacts_empire_life_pattern():
    """Empire-Life-style scraped JD: heading/label words glued to the next
    word with no space ("Manager"+"Location", "Responsibilities"+"Build",
    "Employer"+"Share", "Engineer"+"Location"). None of those artifacts may
    surface as keyword chips; real skills and legit mixed-case tech terms
    must still surface (NF-final-PII-001 / re-opened
    MV-cover-letter-studio-006)."""
    # Kept tight to the 7 non-artifact tech terms this test asserts on — the
    # panel caps chips at 10, and each additional high-scoring tech term
    # (MongoDB/GitHub/GitLab/OAuth2 are ALSO covered individually by
    # test_legit_mixed_case_tech_is_not_flagged_as_artifact above) competes
    # for those slots by score, so keeping the JD focused avoids crowding out
    # the lower-scoring "Node.js" with unrelated extra tech mentions.
    job = {
        "title": "Senior Platform Team",
        "description": (
            "Senior Platform ManagerLocation: Toronto, Canada. "
            "ResponsibilitiesBuild scalable services using Kubernetes and "
            "Docker. Experience with JavaScript, TypeScript, PostgreSQL, "
            "GraphQL and Node.js required. EmployerShare this role widely. "
            "EngineerLocation: Sydney, Australia."
        ),
    }
    letter = (
        "I bring deep Kubernetes, Docker, JavaScript, TypeScript, "
        "PostgreSQL, GraphQL and Node.js experience."
    )
    kw = _keyword_coverage(letter, job)
    words = [i["keyword"].lower() for i in kw["items"]]

    # Concatenation artifacts must never surface as chips.
    for artifact in _CONCATENATION_ARTIFACTS:
        assert artifact.lower() not in words, (
            f"CamelCase concatenation artifact {artifact!r} leaked into the "
            f"keyword chips: {words!r}"
        )

    # Real skills survive.
    assert "kubernetes" in words, f"real skill dropped: {words!r}"
    assert "docker" in words, f"real skill dropped: {words!r}"

    # Legit mixed-case tech terms still surface — NOT collateral damage.
    for term in ("javascript", "typescript", "postgresql", "graphql", "node.js"):
        assert term in words, (
            f"legit mixed-case tech term {term!r} was wrongly dropped: "
            f"{words!r}"
        )

    # Coverage math stays internally consistent.
    assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
    assert 0 < kw["total"] <= 10


# ---------------------------------------------------------------------------
# NF-final-resid-001 — final adversarial sweep, residual of NF-final-PII-001.
# City/place-name + boilerplate-label CamelCase gluings (SydneySalary,
# MelbourneSalary, BrisbaneLocation, AdelaideSalary, PerthSalary,
# CanberraLocation) survived the "EVERY segment must be a standalone
# boilerplate word" rule because _ARTIFACT_SPLIT_WORDS lists countries but no
# city names — "Sydney"+"Salary" failed the all-segments test since "sydney"
# is nowhere in that set, so the gluing was scored (+45 internal uppercase)
# and ranked into the top chips. Reproduced 3x on prod (API run1, API run2
# fresh session, real-browser Playwright).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("artifact", _CITY_LABEL_ARTIFACTS)
def test_city_label_camel_artifact_is_detected(artifact):
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a city name to a JD structural label and must "
        "be detected as a concatenation artifact (NF-final-resid-001)"
    )


@pytest.mark.parametrize("artifact", _ADVERSARIAL_LABEL_ARTIFACTS)
def test_adversarial_place_label_camel_artifact_is_detected(artifact):
    """Any proper noun glued to a JD structural label is an artifact — the
    fix must generalize past the 6 sweep-named cities without a city
    allowlist (NF-final-resid-001 adversarial variants)."""
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a proper noun to a JD structural label and must "
        "be detected as a concatenation artifact (NF-final-resid-001, "
        "adversarial variant beyond the sweep-named cities)"
    )


@pytest.mark.parametrize("term", _FALSE_POSITIVE_TECH_GUARDS)
def test_label_segment_false_positive_tech_terms_are_not_flagged(term):
    """A legitimate mixed-case tech/product term must not be collateral
    damage from the "any segment is a JD label word" rule just because one
    of its CamelCase segments (Share/Location) happens to match a label word
    (NF-final-resid-001 false-positive guard)."""
    assert not _is_camel_concatenation_artifact(term), (
        f"{term!r} is a legitimate mixed-case tech/product term and must NOT "
        "be flagged as a concatenation artifact merely because one segment "
        "matches a JD label word"
    )


def test_keyword_coverage_drops_city_label_camel_artifacts_empire_life_pattern():
    """Empire-Life-style scraped JD (prod pattern from the sweep): city names
    glued to JD structural labels with no space ("Melbourne"+"Salary",
    "Brisbane"+"Location", "Sydney"+"Salary"). None of these may surface as
    keyword chips; the legit mixed-case tech terms the sweep also verified
    on this exact JD (JavaScript/TypeScript/PostgreSQL/DevOps/iPhone) must
    still surface (NF-final-resid-001)."""
    job = {
        "title": "Senior Platform Engineer",
        "description": (
            "MelbourneSalary: $180k package, negotiable. "
            "BrisbaneLocation: hybrid, 2 days onsite per week. "
            "SydneySalary: DOE, relocation assistance available. "
            "Stack: JavaScript, TypeScript, PostgreSQL and DevOps tooling; "
            "an iPhone is provided for on-call. Reliability and "
            "microservices experience required."
        ),
    }
    letter = (
        "I bring deep JavaScript, TypeScript, PostgreSQL and DevOps "
        "experience building reliable, iPhone-integrated microservices."
    )
    kw = _keyword_coverage(letter, job)
    words = [i["keyword"].lower() for i in kw["items"]]

    for artifact in ("SydneySalary", "MelbourneSalary", "BrisbaneLocation"):
        assert artifact.lower() not in words, (
            f"City+label CamelCase artifact {artifact!r} leaked into "
            f"keyword chips: {words!r}"
        )

    for term in ("javascript", "typescript", "postgresql", "devops", "iphone"):
        assert term in words, (
            f"legit mixed-case tech term {term!r} was wrongly dropped: "
            f"{words!r}"
        )

    assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
    assert 0 < kw["total"] <= 10


def test_keyword_coverage_drops_city_label_camel_artifacts_redpanda_pattern():
    """Redpanda-style scraped JD (prod pattern from the sweep): a second
    independent JD glues DIFFERENT cities to the SAME structural labels
    ("Adelaide"+"Salary", "Canberra"+"Location", "Perth"+"Salary"). None may
    surface as keyword chips; the legit mixed-case tech terms the sweep
    verified on this JD (Golang/Terraform/GraphQL/Kubernetes) must still
    surface (NF-final-resid-001)."""
    job = {
        "title": "Platform Engineer",
        "description": (
            "AdelaideSalary: market rate, superannuation included. "
            "CanberraLocation: onsite, security clearance required. "
            "PerthSalary: negotiable for the right candidate. "
            "We run Golang microservices on Kubernetes, provisioned via "
            "Terraform, fronted by a GraphQL gateway."
        ),
    }
    letter = (
        "I bring deep Golang, Kubernetes, Terraform and GraphQL experience "
        "running production microservices platforms."
    )
    kw = _keyword_coverage(letter, job)
    words = [i["keyword"].lower() for i in kw["items"]]

    for artifact in ("AdelaideSalary", "CanberraLocation", "PerthSalary"):
        assert artifact.lower() not in words, (
            f"City+label CamelCase artifact {artifact!r} leaked into "
            f"keyword chips: {words!r}"
        )

    for term in ("golang", "terraform", "graphql", "kubernetes"):
        assert term in words, (
            f"legit mixed-case tech term {term!r} was wrongly dropped: "
            f"{words!r}"
        )

    assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
    assert 0 < kw["total"] <= 10


# ---------------------------------------------------------------------------
# NF-final-closure-001 — final adversarial CLOSURE sweep, narrow residual of
# NF-final-resid-001 / NF-final-PII-001 / MV-cover-letter-studio-006. An
# ACCENTED/non-ASCII proper noun glued to a JD structural label still leaked
# a fragment: "MünchenLocation" -> chip "nchenLocation". Root cause: the
# ASCII-only ``_WORD_RE`` severed the token at "ü" into "M" + "nchenLocation"
# BEFORE ``_is_camel_concatenation_artifact`` ever ran; the surviving
# fragment's CamelCase split ("nchenLocation" -> ["Location"]) has only ONE
# segment, so the `len(segments) < 2` guard returned False before the
# any-segment-is-a-label check ever fired. Fixed at the root by widening
# ``_WORD_RE`` to be Unicode-aware, so the glued token survives tokenization
# whole and hits the SAME existing label rule an ASCII gluing does — no
# change to ``_is_camel_concatenation_artifact``/``_CAMEL_HUMP_RE`` needed.
# ---------------------------------------------------------------------------

# The exact reported case plus adversarial variants of my own design: other
# single-word accented city names (different accented letters, different
# label words, different label POSITIONS relative to the accent) glued with
# no space to a JD structural label. Each tuple is
# (glued_token, forbidden_fragment_pre_fix) — the forbidden fragment is the
# exact garbage token the ASCII-only tokenizer left behind pre-fix (verified
# by direct simulation of the unfixed ``_WORD_RE`` against each string).
_ACCENTED_LABEL_ARTIFACTS = (
    ("MünchenLocation", "nchenlocation"),        # the reported case (ü)
    ("LocationMünchen", "nchen"),                # label-first order (ü)
    ("ZürichSalary", "richsalary"),               # accent near the start
    ("SalaryZürich", "rich"),                     # label-first order
    ("KölnDepartment", "lndepartment"),           # ö
    ("GöteborgBenefits", "teborgbenefits"),       # ö, longer city name
    ("BenefitsGöteborg", "teborg"),               # label-first order
    ("MünchenQualifications", "nchenqualifications"),
)


@pytest.mark.parametrize("artifact,fragment", _ACCENTED_LABEL_ARTIFACTS)
def test_accented_label_camel_artifact_leaves_no_fragment(artifact, fragment):
    """The glued accented+label token must be dropped WHOLE — no fragment
    (the pre-fix garbage the ASCII-only tokenizer produced) may survive as a
    keyword chip (NF-final-closure-001)."""
    jd = f"Senior Engineer. {artifact}: details below. Apply with your CV."
    keywords = _jd_keywords(jd)
    words = [k.lower() for k in keywords]
    assert fragment not in words, (
        f"{artifact!r} leaked the pre-fix tokenizer fragment {fragment!r} "
        f"into JD keywords: {words!r}"
    )
    assert artifact.lower() not in words, (
        f"{artifact!r} itself leaked into JD keywords: {words!r}"
    )


def test_keyword_coverage_drops_muenchen_location_class_artifact_reported_pattern():
    """The EXACT reported repro (NF-final-closure-001): a scraped JD gluing
    an accented city to a label with no space. Chip must be absent, no
    fragment, and legit tech terms + a legit UNGLUED accented city name must
    still survive."""
    job = {
        "title": "Senior Backend Engineer",
        "description": (
            "MünchenLocation: hybrid, 2 days onsite per week. "
            "We are a Zürich-based company with a satellite office. "
            "Stack: JavaScript, TypeScript, PostgreSQL, Kubernetes and "
            "Docker. DevOps and microservices experience required."
        ),
    }
    letter = (
        "I bring deep JavaScript, TypeScript, PostgreSQL, Kubernetes and "
        "Docker experience building reliable DevOps microservices."
    )
    kw = _keyword_coverage(letter, job)
    words = [i["keyword"].lower() for i in kw["items"]]

    assert "nchenlocation" not in words, (
        f"Accented city+label CamelCase fragment 'nchenLocation' leaked "
        f"into keyword chips: {words!r}"
    )
    assert "münchenlocation" not in words, f"leaked whole: {words!r}"

    for term in ("javascript", "typescript", "postgresql", "kubernetes", "docker"):
        assert term in words, (
            f"legit mixed-case tech term {term!r} was wrongly dropped: "
            f"{words!r}"
        )

    assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
    assert 0 < kw["total"] <= 10


# ---------------------------------------------------------------------------
# Preserved cases (NF-final-closure-001's own acceptance criterion cuts both
# ways): a legitimate accented word that is NOT glued to a label must keep
# working exactly like any other JD term — not be flagged as an artifact,
# and not be shredded into ASCII-only garbage fragments.
# ---------------------------------------------------------------------------


def test_unglued_accented_city_name_is_not_flagged_as_artifact():
    """'Zürich'/'München' standing alone (not glued to a label) are
    legitimate city names, not concatenation artifacts — NF-final-closure-001
    preserved case."""
    assert not _is_camel_concatenation_artifact("Zürich")
    assert not _is_camel_concatenation_artifact("München")


def test_accented_word_survives_tokenization_intact_no_garbage_fragments():
    """'résumé' (and other legit accented JD prose) must tokenize as ONE
    whole word, not be severed into ASCII-only garbage fragments ('r' +
    'sum') — NF-final-closure-001 preserved case: legit accented words in
    JDs must not break keyword extraction."""
    jd = (
        "Please submit your résumé and a brief cover note. "
        "JavaScript and PostgreSQL experience preferred."
    )
    keywords = _jd_keywords(jd)
    words = [k.lower() for k in keywords]
    # The pre-fix ASCII-only tokenizer fragmented "résumé" into "r" (dropped,
    # too short) and "sum" (>=3 chars, survived as a spurious keyword chip).
    assert "sum" not in words, (
        f"'résumé' was fragmented into a spurious 'sum' keyword chip: "
        f"{words!r}"
    )
    # The whole word survives as itself (not silently discarded either).
    assert "résumé" in words, (
        f"'résumé' should tokenize and survive as a single whole keyword: "
        f"{words!r}"
    )
