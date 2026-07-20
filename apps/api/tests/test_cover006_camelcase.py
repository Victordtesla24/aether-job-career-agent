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

from app.routers import cover_letters as _cl_module
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


# ---------------------------------------------------------------------------
# NF-final-pass-001 — final-pass adversarial sweep, residual of
# NF-final-closure-001 / NF-final-resid-001 / NF-final-PII-001 /
# MV-cover-letter-studio-006. A proper noun in a NON-Latin script (Cyrillic,
# Greek) or one starting with a non-ASCII-uppercase letter outside the
# accented-Latin range the München fix covers (Turkish İ = U+0130 LATIN
# CAPITAL LETTER I WITH DOT ABOVE) still leaked as a top chip when glued to
# a JD structural label: İstanbulSalary, КиевLocation, МоскваSalary,
# İzmirLocation, ΑθήναLocation.
#
# Root cause (verified live against the retired ``_CAMEL_HUMP_RE`` regex at
# f491170): the regex's hump-START test was ``[A-Z]`` — ASCII-only — so a
# Cyrillic/Greek/Turkish-İ capital letter never started a hump at all.
# Gluing one to an ASCII label word left exactly ONE hump (the label
# itself), e.g. ``_CAMEL_HUMP_RE.findall("МоскваSalary") == ['Salary']``, so
# the ``len(segments) < 2`` early-return in
# ``_is_camel_concatenation_artifact`` fired BEFORE the label-word check
# ever ran — unlike an ASCII gluing ("SydneySalary" -> ['Sydney','Salary'],
# correctly caught since NF-final-resid-001). The München fix
# (NF-final-closure-001) widened only the ``_WORD_RE`` *tokenizer*, not this
# hump *segmenter*, so it never reached this class of gluing.
#
# Fixed at the root (ORCHESTRATOR DESIGN RULING: terminate the class
# structurally, no regex alphabet enumeration) by replacing the ASCII regex
# with ``_camel_humps``, a character-walk using
# ``ch.isupper()``/``ch.islower()``/``ch.isdigit()`` — unicode-correct for
# every cased script in one shot. Caseless scripts (CJK, etc.) have no
# uppercase/lowercase distinction at all, so a caseless character can
# neither start nor continue a hump — it is simply skipped, exactly like
# punctuation — meaning the class genuinely ends here with no further
# per-script enumeration needed.
# ---------------------------------------------------------------------------

# The exact 5 gluings the final-pass adversarial sweep reproduced 3x on prod
# (API run1, fresh-session re-GET, fresh job + browser panel) as TOP chips.
_NON_LATIN_LABEL_ARTIFACTS = (
    "İstanbulSalary",  # İstanbulSalary  (Turkish İ, U+0130)
    "КиевLocation",  # КиевLocation  (Cyrillic)
    "МоскваSalary",  # МоскваSalary  (Cyrillic)
    "İzmirLocation",  # İzmirLocation  (Turkish İ)
    "ΑθήναLocation",  # ΑθήναLocation  (Greek)
)


@pytest.mark.parametrize("artifact", _NON_LATIN_LABEL_ARTIFACTS)
def test_non_latin_proper_noun_label_camel_artifact_is_detected(artifact):
    """The exact 5 non-Latin-script / non-ASCII-capital gluings the
    final-pass adversarial sweep found leaking into prod's JD Keyword
    Coverage panel as TOP chips (NF-final-pass-001)."""
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a non-Latin-script (or Turkish İ) proper noun "
        "to a JD structural label and must be detected as a concatenation "
        "artifact (NF-final-pass-001)"
    )


# Adversarial variants of my own design (NOT enumerated by the sweep): the
# same 5 gluings with the JD structural label placed FIRST and the
# non-Latin-script proper noun glued directly after — the reverse order
# from the sweep-named cases. A structural, hump-membership-based fix must
# be order-independent; a fix that only special-cased "label at the end"
# would still be whack-a-mole.
_NON_LATIN_LABEL_ARTIFACTS_REVERSED = (
    "SalaryМосква",  # SalaryМосква
    "LocationКиев",  # LocationКиев
    "Salaryİstanbul",  # Salaryİstanbul
    "Locationİzmir",  # Locationİzmir
    "LocationΑθήνα",  # LocationΑθήνα
)


@pytest.mark.parametrize("artifact", _NON_LATIN_LABEL_ARTIFACTS_REVERSED)
def test_non_latin_proper_noun_label_camel_artifact_reverse_order_is_detected(
    artifact,
):
    """Reverse gluing order (JD structural label FIRST, non-Latin-script
    proper noun glued directly after) must also be detected — the fix
    operates on hump membership, not position (NF-final-pass-001
    adversarial variant beyond the sweep-named order)."""
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a JD structural label to a non-Latin-script "
        "proper noun (reverse order) and must be detected as a "
        "concatenation artifact (NF-final-pass-001)"
    )


_NON_LATIN_STANDALONE_PRESERVED = (
    "Киев",  # Киев (Kiev), unglued
    "İstanbul",  # İstanbul, unglued
    "Zürich",  # Zürich, unglued (NF-final-closure-001 case retained)
)


@pytest.mark.parametrize("term", _NON_LATIN_STANDALONE_PRESERVED)
def test_standalone_non_latin_proper_noun_not_flagged_as_artifact(term):
    """A non-Latin-script (or accented-Latin) proper noun standing ALONE —
    not glued to a label — is a legitimate JD term, not a concatenation
    artifact (NF-final-pass-001 preserved case, mirrors
    NF-final-closure-001's own unglued-Zürich/München guard)."""
    assert not _is_camel_concatenation_artifact(term), (
        f"{term!r} is a legitimate standalone proper noun and must NOT be "
        "flagged as a concatenation artifact merely for containing a "
        "non-ASCII / non-Latin-script capital letter"
    )


def test_keyword_coverage_drops_non_latin_label_camel_artifacts_reported_pattern():
    """The exact reported pattern (NF-final-pass-001): a scraped JD gluing
    non-Latin-script city names to JD structural labels with no space. None
    of the 5 sweep-named artifacts may surface as keyword chips; legit tech
    terms AND an UNGLUED non-Latin city name mentioned in the same JD must
    still survive."""
    job = {
        "title": "Senior Backend Engineer, EMEA",
        "description": (
            "МоскваSalary: negotiable, relocation assistance available. "
            "КиевLocation: hybrid, 2 days onsite per week. "
            "İstanbulSalary: DOE, relocation assistance available. "
            "İzmirLocation: remote-friendly. "
            "ΑθήναLocation: onsite, EU work authorization required. "
            "We are proud to have engineers based in Киев itself. "
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

    for artifact in _NON_LATIN_LABEL_ARTIFACTS:
        assert artifact.lower() not in words, (
            f"Non-Latin-script proper-noun+label CamelCase artifact "
            f"{artifact!r} leaked into keyword chips: {words!r}"
        )

    for term in ("javascript", "typescript", "postgresql", "kubernetes", "docker"):
        assert term in words, (
            f"legit mixed-case tech term {term!r} was wrongly dropped: "
            f"{words!r}"
        )

    assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
    assert 0 < kw["total"] <= 10


# ---------------------------------------------------------------------------
# ASCII/acronym characterization — locks in the EXACT segmentation the
# retired ``_CAMEL_HUMP_RE`` regex produced (captured live from the regex
# at f491170, BEFORE any code change) as a regression guard for the
# NF-final-pass-001 rewrite. ``_active_camel_humps`` resolves whichever
# segmenter is currently wired into ``app.routers.cover_letters`` — the
# legacy regex (pre-fix) or its replacement, ``_camel_humps`` (post-fix) —
# so this exact test file runs unmodified both BEFORE and AFTER the fix,
# proving the ASCII/acronym segmentation contract (including acronym-run
# handling, e.g. "APIGateway" -> ["API", "Gateway"], "PostgreSQL" ->
# ["Postgre", "SQL"]) stays byte-identical across the rewrite.
# ---------------------------------------------------------------------------


def _active_camel_humps(token: str) -> list[str]:
    fn = getattr(_cl_module, "_camel_humps", None)
    if fn is not None:
        return fn(token)
    return _cl_module._CAMEL_HUMP_RE.findall(token)


# (token, expected_segments) — expected values captured live via
# ``_CAMEL_HUMP_RE.findall(token)`` at f491170, before any change.
_ASCII_HUMP_CHARACTERIZATION = (
    ("ManagerLocation", ["Manager", "Location"]),
    ("EngineerLocation", ["Engineer", "Location"]),
    ("JavaScript", ["Java", "Script"]),
    ("PostgreSQL", ["Postgre", "SQL"]),
    ("GraphQL", ["Graph", "QL"]),
    ("MongoDB", ["Mongo", "DB"]),
    ("GitHub", ["Git", "Hub"]),
    ("OAuth2", ["O", "Auth2"]),
    ("APIGateway", ["API", "Gateway"]),
    ("GatewayAPI", ["Gateway", "API"]),
    ("SQLDatabase", ["SQL", "Database"]),
    ("AB", ["AB"]),
    ("A", ["A"]),
    ("GatewayX", ["Gateway", "X"]),
    ("iPhone", ["Phone"]),
    ("NASA", ["NASA"]),
    ("XMLHttpRequest", ["XML", "Http", "Request"]),
    ("HTMLParser", ["HTML", "Parser"]),
    ("IOError", ["IO", "Error"]),
    ("IPv4Address", ["I", "Pv4", "Address"]),
    ("Node.js", ["Node"]),
    ("C++", ["C"]),
    ("CI/CD", ["C", "I", "CD"]),
    ("abcXYZ", ["XYZ"]),
    ("abcXYZdef", ["XY", "Zdef"]),
    ("ABC", ["ABC"]),
    ("ABc", ["A", "Bc"]),
    ("AaBbCc", ["Aa", "Bb", "Cc"]),
    ("A1B2C3", ["A1", "B2", "C3"]),
    ("Word2Vec", ["Word2", "Vec"]),
    ("GPT4Turbo", ["GP", "T4", "Turbo"]),
    ("iOS", ["OS"]),
    ("macOS", ["OS"]),
    ("eBay", ["Bay"]),
    ("Log4j2", ["Log4j2"]),
    ("WebAssembly", ["Web", "Assembly"]),
    ("SydneySalary", ["Sydney", "Salary"]),
    ("x", []),
    ("", []),
)


@pytest.mark.parametrize("token,expected", _ASCII_HUMP_CHARACTERIZATION)
def test_ascii_camel_hump_segmentation_characterization_byte_identical(
    token, expected
):
    """Locks in the EXACT ASCII/acronym hump segmentation the retired
    ``_CAMEL_HUMP_RE`` regex produced. The NF-final-pass-001 rewrite
    (unicode case-function splitter) must reproduce every one of these
    ASCII/acronym results byte-for-byte — the safety net against silently
    changing acronym-handling behavior while fixing the non-Latin-script
    gap."""
    got = _active_camel_humps(token)
    assert got == expected, (
        f"{token!r} hump segmentation changed: expected {expected!r}, got "
        f"{got!r} — ASCII/acronym behavior must stay byte-identical across "
        "the NF-final-pass-001 rewrite"
    )


# ---------------------------------------------------------------------------
# NF-final-pass-002 — closure-qa novel adversarial sweep, THIRD path to the
# same historical ``len(segments) < 2`` early-return family (previously:
# severed unicode fragments -- NF-final-closure-001; non-Latin CASED proper
# nouns -- NF-final-pass-001). A CASELESS-script proper noun (CJK/Kana/
# Hangul/Arabic/Hebrew/Devanagari/Thai) glued to a JD structural label
# contributes NO cased segment at all -- caseless characters have no
# upper/lower distinction, so ``_camel_humps`` skips them exactly like
# punctuation. The ASCII label therefore becomes the token's SOLE segment
# and the ``len(segments) < 2`` early-return fires before the label-word
# check ever runs, silently accepting the gluing.
#
# ORCHESTRATOR DESIGN RULING: kill the early-return pattern itself rather
# than add a fourth script-family branch. When segmentation yields exactly
# ONE cased segment, the token is now ALSO judged an artifact when that lone
# segment is one of the narrower ``_ARTIFACT_LABEL_WORDS`` AND the token
# carries material beyond that segment (``token != segment`` -- a glued
# caseless/other-noise prefix or suffix is present). A token that IS its
# segment (a standalone label mention, e.g. bare "Salary") is unaffected.
# Zero segments (a caseless proper noun with no glued label) is unaffected.
# ---------------------------------------------------------------------------

# The exact 4 gluings named in the CLOSURE-REPORT.json sweep (prod, top
# chips): CJK/Kanji, Devanagari (observed as a garbage `_WORD_RE`-fragmented
# "बईLocation" -- the leading combining-vowel-shredded remnant of "मुंबई",
# accepted as the real-world token exactly as the sweep captured it),
# Katakana, Arabic.
_CASELESS_LABEL_ARTIFACTS = (
    "القاهرةSalary",  # Arabic (Cairo)
    "बईLocation",  # Devanagari fragment (Mumbai, as actually observed on prod)
    "ソウルSalary",  # Katakana (Seoul)
    "東京Salary",  # CJK/Kanji (Tokyo)
)


@pytest.mark.parametrize("artifact", _CASELESS_LABEL_ARTIFACTS)
def test_caseless_script_label_camel_artifact_is_detected(artifact):
    """The exact 4 caseless-script gluings named in the closure-qa novel
    adversarial sweep (NF-final-pass-002) must be detected as concatenation
    artifacts."""
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a caseless-script proper noun to a JD "
        "structural label and must be detected as a concatenation artifact "
        "(NF-final-pass-002)"
    )


# Label-FIRST order with the same 4 scripts (my own design, not sweep-named).
# Verified live against unmodified c158729 BEFORE writing this test: e.g.
# ``_camel_humps("Salaryソウル") == ['Salary']`` and
# ``_is_camel_concatenation_artifact("Salaryソウル") is False`` pre-fix (the
# CORRECT post-fix expectation is True) -- the fix must be order-independent
# since it operates on segment membership, not position.
_CASELESS_LABEL_ARTIFACTS_REVERSED = (
    "Salary東京",  # CJK/Kanji, label first
    "Locationソウル",  # Katakana, label first
    "Salaryالقاهرة",  # Arabic, label first
    "Locationबई",  # Devanagari fragment, label first
)


@pytest.mark.parametrize("artifact", _CASELESS_LABEL_ARTIFACTS_REVERSED)
def test_caseless_script_label_camel_artifact_reverse_order_is_detected(artifact):
    """Reverse gluing order (JD structural label FIRST, caseless-script
    proper noun glued directly after) must also be detected -- the fix
    operates on hump membership, not position (NF-final-pass-002 adversarial
    variant beyond the sweep-named order)."""
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a JD structural label to a caseless-script "
        "proper noun (reverse order) and must be detected as a "
        "concatenation artifact (NF-final-pass-002)"
    )


# Thai and Hebrew variants of my own design (NOT enumerated by the sweep),
# spanning two more caseless scripts. Hebrew has no combining marks in these
# words so it tokenizes as ONE whole glued token; Thai carries combining
# vowel signs that ``_WORD_RE`` (out of scope for this fix -- a tokenizer
# concern, not a segmenter concern) shreds identically to how the Devanagari
# "बईLocation" fragment above was already produced -- exercised here as-is
# to prove the segmenter-level fix is script-agnostic regardless of how the
# tokenizer upstream happened to fragment the caseless prefix.
_THAI_HEBREW_LABEL_ARTIFACTS = (
    "חיפהSalary",  # Hebrew, whole word (Haifa), no combining marks
    "ירושליםLocation",  # Hebrew, whole word (Jerusalem)
    "งเทพSalary",  # Thai fragment (as `_WORD_RE` actually emits from "กรุงเทพSalary")
)


@pytest.mark.parametrize("artifact", _THAI_HEBREW_LABEL_ARTIFACTS)
def test_thai_hebrew_caseless_label_camel_artifact_is_detected(artifact):
    """Thai and Hebrew variants (my own design, spanning two more caseless
    scripts beyond the sweep-named CJK/Devanagari/Katakana/Arabic) must also
    be detected as concatenation artifacts (NF-final-pass-002)."""
    assert _is_camel_concatenation_artifact(artifact), (
        f"{artifact!r} glues a caseless-script (Thai/Hebrew) proper noun to "
        "a JD structural label and must be detected as a concatenation "
        f"artifact (NF-final-pass-002)"
    )


_CASELESS_STANDALONE_PRESERVED = (
    "東京",  # Tokyo, unglued
    "السعودية",  # Saudi Arabia, unglued
    "ソウル",  # Seoul, unglued
    "ירושלים",  # Jerusalem, unglued
)


@pytest.mark.parametrize("term", _CASELESS_STANDALONE_PRESERVED)
def test_standalone_caseless_proper_noun_not_flagged_as_artifact(term):
    """A caseless-script proper noun standing ALONE -- not glued to a label,
    zero cased segments -- is a legitimate JD term, not a concatenation
    artifact (NF-final-pass-002 preserved case, mirrors NF-final-pass-001's
    own unglued-Киев/İstanbul guard)."""
    assert not _is_camel_concatenation_artifact(term), (
        f"{term!r} is a legitimate standalone caseless-script proper noun "
        "and must NOT be flagged as a concatenation artifact merely for "
        "having zero cased CamelCase segments"
    )


def test_standalone_label_word_behavior_unchanged():
    """A bare JD structural-label word appearing on its own (``token ==
    segment``, no glued material) is a standalone mention, not a gluing
    artifact -- this behavior must stay EXACTLY as it was before
    NF-final-pass-002 (the len==1 special case only fires when the token
    carries material beyond its lone segment)."""
    for term in ("Salary", "Location", "Benefits", "Department", "Share"):
        assert not _is_camel_concatenation_artifact(term), (
            f"standalone label word {term!r} must not be flagged as an "
            "artifact merely for being a JD structural label on its own"
        )
    # A different word entirely (plural/possessive) is exact-match-only, so
    # it was never affected by the label-word rule and must stay that way.
    assert not _is_camel_concatenation_artifact("Salaries"), (
        "'Salaries' is a distinct word from 'Salary' (exact-match label "
        "comparison) and must not be flagged"
    )


def test_keyword_coverage_drops_caseless_label_camel_artifacts_reported_pattern():
    """The exact reported pattern (NF-final-pass-002): a scraped JD gluing
    caseless-script proper nouns to JD structural labels with no space, plus
    the reverse order. None of the artifacts may surface as keyword chips;
    legit tech terms AND an UNGLUED caseless proper noun mentioned in the
    same JD must still survive."""
    job = {
        "title": "Senior Backend Engineer, APAC/MEA",
        "description": (
            "東京Salary: negotiable, relocation assistance available. "
            "ソウルSalary: DOE, relocation assistance available. "
            "القاهرةSalary: competitive, quarterly bonus. "
            "Salary東京: negotiable (duplicate posting fragment). "
            "We are proud to have engineers based in 東京 itself. "
            "Stack: JavaScript, TypeScript, PostgreSQL, Kubernetes, "
            "Terraform and Docker. DevOps and microservices experience "
            "required."
        ),
    }
    letter = (
        "I bring deep JavaScript, TypeScript, PostgreSQL, Kubernetes, "
        "Terraform and Docker experience building reliable DevOps "
        "microservices."
    )
    kw = _keyword_coverage(letter, job)
    words = [i["keyword"].lower() for i in kw["items"]]

    for artifact in ("東京salary", "ソウルsalary", "القاهرةsalary", "salary東京"):
        assert artifact not in words, (
            f"Caseless-script proper-noun+label CamelCase artifact "
            f"{artifact!r} leaked into keyword chips: {words!r}"
        )

    for term in (
        "javascript",
        "typescript",
        "postgresql",
        "kubernetes",
        "terraform",
        "docker",
    ):
        assert term in words, (
            f"legit mixed-case tech term {term!r} was wrongly dropped: "
            f"{words!r}"
        )

    assert kw["covered"] == sum(1 for i in kw["items"] if i["covered"])
    assert 0 < kw["total"] <= 10


# ---------------------------------------------------------------------------
# False-positive survey (documented per orchestrator's explicit instruction
# to think through false positives BEFORE coding):
# ---------------------------------------------------------------------------


def test_hyphen_slash_continuation_tokens_unaffected_by_single_segment_rule():
    """`_WORD_RE` allows ``+#./-`` as in-word continuation characters, so a
    JD string like "Salary/Benefits" or "Salary-Location" tokenizes as ONE
    token -- but `_camel_humps` still yields 2+ segments for these (the
    punctuation is skipped like a caseless character, but there IS a second
    cased hump on the other side), so they were ALREADY caught by the
    pre-existing len>=2 path and are UNAFFECTED by the new len==1 branch.
    Characterizes that no interaction bug was introduced between the two
    branches."""
    assert _cl_module._camel_humps("Salary/Benefits") == ["Salary", "Benefits"]
    assert _cl_module._camel_humps("Salary-Location") == ["Salary", "Location"]
    assert _is_camel_concatenation_artifact("Salary/Benefits")
    assert _is_camel_concatenation_artifact("Salary-Location")


def test_single_label_segment_with_lowercase_ascii_prefix_or_suffix_is_flagged():
    """Documented decision (surveyed `_MIXED_CASE_TECH_ALLOWLIST`, 21 entries
    at the time of this fix): no established real product matches the
    single-cased-label-segment-plus-glued-noise shape (e.g. a hypothetical
    "eSalary"/"iLocation"/"eShare"-style name) closely enough to allowlist
    without evidence. Per the orchestrator's explicit false-positive
    instruction ("decide and document; allowlist if real"), these are
    intentionally treated as artifacts under the new rule -- the same
    ``_MIXED_CASE_TECH_ALLOWLIST`` escape hatch (checked FIRST, before this
    logic runs) is available the moment a real product is identified, with
    no further code change required."""
    for token in ("eSalary", "iLocation", "eShare", "eBenefits"):
        assert _is_camel_concatenation_artifact(token), (
            f"{token!r} glues ASCII noise to a lone JD-label segment and "
            "is treated as an artifact by design (no allowlisted real "
            f"product identified for this shape)"
        )


def test_single_non_label_segment_with_caseless_prefix_is_not_flagged():
    """A caseless-script prefix glued to a SOLE cased segment that is NOT
    one of the narrower ``_ARTIFACT_LABEL_WORDS`` (e.g. "Manager"/
    "Engineer", which live only in the broader ``_ARTIFACT_SPLIT_WORDS``)
    stays unflagged -- the new len==1 rule deliberately mirrors the existing
    len>=2 asymmetry (ANY-segment-is-a-LABEL, not ANY-segment-is-boilerplate)
    rather than widening scope beyond the orchestrator's ruling."""
    for token in ("東京Manager", "東京Engineer", "ソウルDirector"):
        assert not _is_camel_concatenation_artifact(token), (
            f"{token!r} has a single non-label cased segment and must NOT "
            f"be flagged under the narrower len==1 rule"
        )


def test_allowlisted_two_segment_terms_unaffected_by_single_segment_rule():
    """Existing 2-segment allowlisted terms (SlideShare, SharePoint,
    GeoLocation) are unaffected by the new len==1 branch -- they never reach
    it, since the allowlist check runs first and short-circuits before
    `_camel_humps` is even called."""
    for term in ("SlideShare", "SharePoint", "GeoLocation"):
        assert not _is_camel_concatenation_artifact(term)
