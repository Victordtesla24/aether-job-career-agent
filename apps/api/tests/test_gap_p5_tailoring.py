"""GAP-TAIL-001 — evidence-grounded tailoring that actually improves ATS.

The tailored resume was scoring WORSE than the original against the target job
(negative conversion lift) for two structural reasons:

1. ``_compute_conversion_metrics`` scored the *full* original resume against the
   JD but only the *bullets* of the tailored resume — an apples-to-oranges
   comparison that stripped the keyword-dense skills/summary context from the
   tailored side, guaranteeing a large negative delta regardless of rewrite
   quality.
2. The guards were too conservative: the JD-echo guard rejected terminology the
   candidate genuinely uses (every word individually evidence-supported), and
   nothing stopped an otherwise-legal rewrite from *dropping* a JD keyword the
   original bullet already covered (lowering ATS).

This suite locks in the elite honest bar (§11.2): tailored ATS >= baseline
(strictly > for a clear match), truthful JD keywords surfaced, fabricated tokens
still rejected, quantified metrics preserved, section structure untouched.
"""
from __future__ import annotations

from app.agents.tailor_agent import _compute_conversion_metrics
from app.services.ats_engine import ATSEngine
from app.services.resume_tailor import (
    ResumeTailorService,
    _evidence_index,
    strip_bullet_lines,
    unsupported_tokens,
)

# --- shared fixture: a keyword-dense resume with a real skills section --------

_RESUME = (
    "JANE DOE\n"
    "Senior Backend Engineer\n"
    "\n"
    "SKILLS\n"
    "Python, PostgreSQL, Docker, REST, testing, agile\n"
    "\n"
    "EXPERIENCE\n"
    "Acme Corp\n"
    "2019 - 2024 | Sydney\n"
    "• Built backend services handling 2000000 requests per day, cutting latency by 40%.\n"
    "• Led a team of 5 engineers delivering payment features.\n"
)
_ORIGINAL_BULLETS = [
    {
        "text": "Built backend services handling 2000000 requests per day, cutting latency by 40%.",
        "evidenceRef": "bullet-0",
    },
    {"text": "Led a team of 5 engineers delivering payment features.", "evidenceRef": "bullet-1"},
]
_JD = (
    "Senior Python Engineer. Requirements: Python, PostgreSQL, Docker, REST, "
    "testing, agile, GraphQL, backend services."
)


def _svc() -> ResumeTailorService:
    return ResumeTailorService()


# --- 1. non-negative / strictly-positive conversion lift ---------------------


def test_conversion_lift_is_non_negative_for_noop() -> None:
    """No rewrites at all must never produce a negative lift (the old code did:
    full-resume baseline vs bullets-only tailored)."""
    metrics = _compute_conversion_metrics(_RESUME, _ORIGINAL_BULLETS, _ORIGINAL_BULLETS, _JD)
    assert metrics["tailoredATSScore"] >= metrics["baselineATSScore"]
    assert metrics["estimatedConversionLift"].startswith("+")


def test_conversion_lift_is_strictly_positive_for_clear_match() -> None:
    """Surfacing a truthful JD keyword the resume lacked raises the ATS score."""
    tailored = [
        {
            "text": "Built GraphQL backend services handling 2000000 requests per day, "
            "cutting latency by 40%.",
            "evidenceRef": "bullet-0",
        },
        _ORIGINAL_BULLETS[1],
    ]
    metrics = _compute_conversion_metrics(_RESUME, _ORIGINAL_BULLETS, tailored, _JD)
    assert metrics["tailoredATSScore"] > metrics["baselineATSScore"], metrics
    assert metrics["estimatedConversionLift"].startswith("+")


# --- 2. per-bullet ATS floor: never drop a JD keyword the original covered ----


def test_rewrite_dropping_a_jd_keyword_is_reverted() -> None:
    originals = [
        {
            "text": "Reduced infrastructure costs by 15% while improving reliability.",
            "evidenceRef": "bullet-0",
        }
    ]
    resume_text = originals[0]["text"]
    jd = "We need reliability engineering and cost optimization. reliability is essential."
    # Legal on every other axis (metric kept, no fabrication, no JD-echo) but it
    # drops "reliability" — a JD keyword the original already covered → weaker ATS.
    raw = {
        "bullets": [{"text": "Reduced infrastructure costs by 15%.", "evidenceRef": "bullet-0"}],
        "evidenceRefs": ["bullet-0"],
    }
    result = _svc()._validate(raw, originals, resume_text, jd)
    assert result.bullets[0]["text"] == originals[0]["text"]
    assert result.changes == 0
    assert result.rejected


# --- 3. truthful JD-keyword surfacing (evidence-supported) is accepted --------


def test_truthful_evidence_backed_terminology_is_accepted() -> None:
    """A JD phrase whose every word is in the candidate's evidence corpus is
    truthful terminology mirroring, not lifting — it must survive the JD-echo
    guard and raise keyword coverage."""
    resume_text = "Built backend services handling 2000000 requests, cutting latency by 40%."
    originals = [{"text": resume_text, "evidenceRef": "bullet-0"}]
    evidence_extra = (
        "GitHub profile: jane. Notable repositories:\n"
        "- graphql-gateway (Python): built a GraphQL API gateway for backend services."
    )
    jd = "Senior engineer needs GraphQL backend services and low latency."
    raw = {
        "bullets": [
            {
                "text": "Built GraphQL backend services handling 2000000 requests, "
                "cutting latency by 40%.",
                "evidenceRef": "bullet-0",
            }
        ],
        "evidenceRefs": ["bullet-0"],
    }
    result = _svc()._validate(raw, originals, resume_text, jd, evidence_extra)
    assert not result.rejected, result.rejected
    assert result.changes == 1
    new_text = result.bullets[0]["text"].lower()
    assert "graphql" in new_text  # truthful JD keyword surfaced
    assert "graphql" not in resume_text.lower()  # absent from baseline


# --- 4. fabrication is still rejected -----------------------------------------


def test_fabricated_capitalized_skill_is_rejected() -> None:
    resume_text = "Built backend services cutting latency by 40%."
    originals = [{"text": resume_text, "evidenceRef": "bullet-0"}]
    jd = "Senior engineer with Kubernetes experience."
    raw = {
        "bullets": [
            {
                "text": "Built backend services on Kubernetes cutting latency by 40%.",
                "evidenceRef": "bullet-0",
            }
        ],
        "evidenceRefs": ["bullet-0"],
    }
    result = _svc()._validate(raw, originals, resume_text, jd)
    assert result.bullets[0]["text"] == resume_text  # fabrication kept out
    assert result.changes == 0
    assert result.rejected


# --- 5. quantified metrics preserved ------------------------------------------


def test_quantified_metric_is_preserved() -> None:
    resume_text = "Reduced costs by 40% across four teams."
    originals = [{"text": resume_text, "evidenceRef": "bullet-0"}]
    jd = "Cost reduction and team leadership across the business."
    raw = {
        "bullets": [{"text": "Reduced costs across teams.", "evidenceRef": "bullet-0"}],
        "evidenceRefs": ["bullet-0"],
    }
    result = _svc()._validate(raw, originals, resume_text, jd)
    assert "40%" in result.bullets[0]["text"]
    assert result.changes == 0


# --- 6. content-only: section structure unchanged -----------------------------


def test_section_structure_is_unchanged() -> None:
    originals = [
        {"text": "Alpha bullet one.", "evidenceRef": "bullet-0"},
        {"text": "Beta bullet two.", "evidenceRef": "bullet-1"},
        {"text": "Gamma bullet three.", "evidenceRef": "bullet-2"},
    ]
    resume_text = " ".join(b["text"] for b in originals)
    raw = {
        "bullets": [{"text": "Alpha bullet one, refined.", "evidenceRef": "bullet-0"}],
        "evidenceRefs": ["bullet-0"],
    }
    result = _svc()._validate(raw, originals, resume_text, "Alpha beta gamma role.")
    assert [b["evidenceRef"] for b in result.bullets] == ["bullet-0", "bullet-1", "bullet-2"]
    assert [b["evidenceRef"] for b in result.originals] == ["bullet-0", "bullet-1", "bullet-2"]


def test_strip_bullet_lines_keeps_context_drops_bullets() -> None:
    context = strip_bullet_lines(_RESUME)
    assert "SKILLS" in context
    assert "Python, PostgreSQL" in context
    assert "backend services handling" not in context  # bullet content removed
    # The stripped context still scores against the JD (it is the keyword-dense
    # skills section), so baseline is never understated to zero.
    assert ATSEngine().score(context, _JD).keyword_match > 0


# --- 7. GAP-TAIL-001 RE-FIX: JD-only domain terms cannot be injected ----------
#
# Live writer-audit finding: the tailoring pass injected 'financial crime' and
# 'core banking' — domain terms present in the JOB DESCRIPTION but absent from
# the candidate's resume + career data — and dropped real quantified outcomes.
# The corpus that VALIDATES a claim must be the candidate's evidence ONLY; the
# JD is the target to mirror, never proof of truth.

_TELCO_RESUME = (
    "Led technical delivery of AI/ML solutions across the Telstra program.\n"
    "Translated business analysis into actionable technical specifications.\n"
)
_TELCO_BULLETS = [
    {
        "text": "Led technical delivery of AI/ML solutions across the Telstra program.",
        "evidenceRef": "bullet-0",
    },
    {
        "text": "Translated business analysis into actionable technical specifications.",
        "evidenceRef": "bullet-1",
    },
]
# A banking-fraud JD whose domain vocabulary the candidate has NEVER used.
_BANKING_JD = (
    "Delivery lead for financial crime detection and core banking transformation. "
    "Experience with financial crime, fraud, and core banking platforms essential."
)


def test_jd_only_domain_term_injection_is_rejected() -> None:
    """(a) A rewrite that injects a lowercase domain term present in the JD but
    absent from the candidate's resume + career data is REJECTED — the original,
    evidence-grounded bullet is kept. 'financial crime'-style injection can never
    pass, regardless of surrounding evidence-backed words or phrasing."""
    svc = _svc()
    variants = [
        # 2-word term flanked by the candidate's own evidence words.
        "Led technical delivery of financial crime solutions across the Telstra program.",
        # 'core banking' injected the same way.
        "Led technical delivery of core banking solutions across the Telstra program.",
        # domain words interleaved so no verbatim JD 3-gram forms (defeats the
        # phrase-level backstop — only evidence validation catches this).
        "Led financial technical delivery of crime solutions for the banking program.",
    ]
    for rewrite in variants:
        raw = {"bullets": [{"text": rewrite, "evidenceRef": "bullet-0"}]}
        result = svc._validate(raw, _TELCO_BULLETS, _TELCO_RESUME, _BANKING_JD)
        assert result.bullets[0]["text"] == _TELCO_BULLETS[0]["text"], rewrite
        assert rewrite in result.rejected, rewrite
        assert result.changes == 0, rewrite
    # And 'financial'/'crime'/'banking' really are JD-only (not in evidence).
    ev_stems, _n = _evidence_index(_TELCO_RESUME)
    for term in ("financial", "crime", "banking"):
        assert term not in ev_stems


def test_rewrite_dropping_most_metrics_is_rejected() -> None:
    """(b) A metric-rich bullet whose rewrite strips all/most of its quantified
    figures (replaced by generic filler) is REJECTED — the original is kept."""
    svc = _svc()
    original = (
        "Built a six-day tiered test harness over 75 hours, governing 40 scenarios, "
        "11 data tables and a 30 to 90 person-day scope."
    )
    originals = [{"text": original, "evidenceRef": "bullet-0"}]
    jd = "Seeking a delivery lead to re-engineer the delivery plan and ensure success."
    # Drops every figure except one → generic filler.
    filler = "Re-engineered the delivery plan over 75 hours, ensuring successful implementation."
    raw = {"bullets": [{"text": filler, "evidenceRef": "bullet-0"}]}
    result = svc._validate(raw, originals, original, jd)
    assert result.bullets[0]["text"] == original
    assert filler in result.rejected
    assert result.changes == 0


def test_evidence_corpus_excludes_job_description() -> None:
    """(c) The corpus that validates a claim is candidate evidence ONLY — the JD
    text never enters it. Unit-tests the corpus assembly used by ``_validate``:
    ``resume raw_text + evidence_extra`` and nothing from the job description."""
    resume_text = "Built backend services handling 2000000 requests, cutting latency by 40%."
    evidence_extra = (
        "GitHub profile: jane. Notable repositories:\n"
        "- graphql-gateway (Python): built a GraphQL API gateway for backend services."
    )
    # This is exactly how ResumeTailorService._validate assembles the corpus.
    evidence_source = f"{resume_text}\n{evidence_extra}"
    ev_stems, _n = _evidence_index(evidence_source)
    # Candidate evidence terms are present…
    assert "graphql" in ev_stems
    assert "backend" in ev_stems
    # …but JD-only domain terms never leak into the corpus.
    for jd_only in ("financial", "crime", "banking", "kubernetes"):
        assert jd_only not in ev_stems, jd_only
    # And the guard, given the JD purely as a risk signal, still rejects a
    # JD-only lowercase term while leaving the candidate's own terms untouched.
    jd_stems, _n2 = _evidence_index(_BANKING_JD)
    flagged = unsupported_tokens(
        "delivered financial crime backend services", ev_stems, _n, jd_stems
    )
    assert "financial" in flagged and "crime" in flagged
    assert "backend" not in flagged and "services" not in flagged


def test_truthful_evidence_backed_jd_keyword_is_accepted_and_lifts_ats() -> None:
    """(d) A truthful, evidence-backed JD keyword still surfaces: the rewrite is
    ACCEPTED and tailoredATS >= baseline. The fabrication guard must not become
    so strict that it blocks legitimate ATS optimisation."""
    resume_text = "Built backend services handling 2000000 requests, cutting latency by 40%."
    originals = [{"text": resume_text, "evidenceRef": "bullet-0"}]
    # The candidate genuinely has GraphQL (proven by their public repo).
    evidence_extra = (
        "GitHub profile: jane. Notable repositories:\n"
        "- graphql-gateway (Python): built a GraphQL API gateway for backend services."
    )
    jd = "Senior engineer needs GraphQL backend services and low latency."
    rewrite = (
        "Built GraphQL backend services handling 2000000 requests, cutting latency by 40%."
    )
    raw = {"bullets": [{"text": rewrite, "evidenceRef": "bullet-0"}]}
    result = _svc()._validate(raw, originals, resume_text, jd, evidence_extra)
    assert not result.rejected, result.rejected
    assert result.changes == 1
    assert "graphql" in result.bullets[0]["text"].lower()
    # tailoredATS >= baseline for the accepted rewrite.
    metrics = _compute_conversion_metrics(
        resume_text, result.originals, result.bullets, jd
    )
    assert metrics["tailoredATSScore"] >= metrics["baselineATSScore"], metrics
