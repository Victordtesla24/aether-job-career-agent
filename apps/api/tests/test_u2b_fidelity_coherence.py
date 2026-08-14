"""U2b coherence round — ONE verified fidelity truth, and every consumer derives from it.

Live production evidence (``uat/reports/evidence/agents-uplift/u2b/verify-truthround/``,
2026-08-14) for tailored résumé ``c34ec9016096f3ad0ec06a733``:

``GET /resumes/{id}/fidelity``::

    {"formatPreserved": true, "method": "pdf-in-place-splice",
     "confidence": "partial", "changesRequested": 4, "changesApplied": 3,
     "changesDropped": 1, "droppedChanges": [...]}

``GET /resumes/{id}/download`` headers::

    x-aether-format-confidence: partial
    x-aether-changes-requested: 4
    x-aether-changes-applied: 3
    x-aether-changes-dropped: 1

Two incoherences in that one payload, both fixed here:

1. **``formatPreserved`` was not derived from the verification.** It was carried
   over from the MECHANISM description (a formatHash match), unchanged, while
   the verification standing next to it had just proved a tailored rewrite is
   missing from the file. Every consumer that branches on the boolean — the
   Resume Studio integrity headline does exactly that — then renders an
   affirmative "preserved" claim over a report saying a change was dropped.
   A verified-dropped change means the artifact is NOT a faithful rendering of
   this version, so ``preserved`` may not stay ``True``.

2. **The PDF splice branch shipped the partial file.** Its DOCX and plain-text
   siblings already refuse to: on the identical completeness rule
   (``resumes.py`` "COMPLETENESS RULE for both native paths") they fall through
   to the branded render, which is built from the version's own structured
   content. The splice branch had no such gate, so a user downloading that
   résumé got a document that is neither their baseline nor their tailored
   résumé — silent content loss, the worse of the two failures.

Fixtures are derived from the repository's own bundled résumé asset at run time
(never hard-coded prose), so the integration test exercises the same geometry
that produced the live defect: ``resume_pdf._detect_blocks`` only edits
right-column work bullets, so a rewrite aimed at the left rail cannot be
applied by the splice engine.
"""
from __future__ import annotations

import pytest

# The bundled-layout fixtures live with the truth-round tests; reusing them
# keeps ONE definition of "a change the splice engine structurally cannot
# apply" instead of a second copy that could drift from the real geometry.
from test_u2b_fidelity_verification import (  # noqa: E402
    _pdf_text,
    _right_column_bullet,
    _seed_bundled_baseline,
    _tailor_child,
)

#: The live artifact's own numbers (verify-truthround/fidelity-c34ec901…json).
LIVE_REQUESTED = 4
LIVE_APPLIED = 3
LIVE_DROPPED = 1


def _live_shape_verification():
    """A ``RenderVerification`` with the exact shape live production returned.

    Real ``ChangeOutcome`` objects (no mocks): three rewrites verified present,
    one — the skills line the splice engine skipped — verified missing, with
    the original wording still in the file, which is the signature of a rewrite
    the renderer never looked at.
    """
    from app.services.format_verification import ChangeOutcome, RenderVerification

    dropped = ChangeOutcome(
        before=(
            "AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python, TypeScript, "
            "React/Next.js, Kubernetes, Docker, Terraform, GCP/AWS"
        ),
        after=(
            "Technical background in software development and AI/ML product delivery, "
            "with exposure to LLM pipelines (LangChain, Langfuse)"
        ),
        coverage=0.087,
        applied=False,
        original_remains=True,
    )
    applied = tuple(
        ChangeOutcome(
            before=f"Original bullet {index}",
            after=f"Reworded bullet {index}",
            coverage=1.0,
            applied=True,
            original_remains=False,
        )
        for index in range(LIVE_APPLIED)
    )
    return RenderVerification(
        requested=LIVE_REQUESTED, text_extracted=True, outcomes=applied + (dropped,)
    )


def _splice_base():
    """The mechanism-level report for a tailored, bundled-layout version."""
    from app.services.resume_format import describe_fidelity

    return describe_fidelity(
        bundled_match=True, has_original=False, content_type=None, is_tailored=True
    )


# ---------------------------------------------------------------------------
# (1) formatPreserved is DERIVED from the verification, never carried over
# ---------------------------------------------------------------------------


def test_verified_fidelity_cannot_report_preserved_true_over_a_dropped_change():
    """The exact live payload shape: changesDropped=1 ⇒ formatPreserved is not true."""
    from app.services.resume_format import verified_fidelity

    base = _splice_base()
    assert base.preserved is True, (
        "fixture sanity: the MECHANISM claim starts affirmative — that is the "
        "value the live payload carried through verification unchanged"
    )

    report = verified_fidelity(base, _live_shape_verification())

    assert report.changes_requested == LIVE_REQUESTED
    assert report.changes_applied == LIVE_APPLIED
    assert report.changes_dropped == LIVE_DROPPED
    assert report.confidence == "partial", report
    assert report.preserved is not True, (
        "a download verified to be MISSING a tailored change is not a "
        f"format-preserving rendering of this version, got {report!r}"
    )
    assert report.preserved is False, (
        "the third state (None) means 'we cannot tell'; here we measured it and "
        f"know the artifact is not faithful, so say so, got {report!r}"
    )


@pytest.mark.parametrize(
    ("bundled_match", "has_original", "content_type"),
    [
        (True, False, None),  # pdf-in-place-splice
        (False, True, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (False, True, "text/plain; charset=utf-8"),
        (False, True, "application/pdf"),  # pdf-in-place-splice, forced False by the drop
    ],
)
def test_no_method_pairs_preserved_true_with_a_verified_dropped_change(
    bundled_match, has_original, content_type
):
    """Whatever the mechanism, a verified-dropped change is never "preserved"."""
    from app.services.resume_format import describe_fidelity, verified_fidelity

    base = describe_fidelity(
        bundled_match=bundled_match,
        has_original=has_original,
        content_type=content_type,
        is_tailored=True,
    )
    report = verified_fidelity(base, _live_shape_verification())

    assert report.changes_dropped == LIVE_DROPPED
    assert report.preserved is not True, (
        f"{report.method} claimed preservation over a dropped change: {report!r}"
    )


def test_a_fully_verified_render_still_reports_preserved_true():
    """No over-correction: the honest affirmative case must survive."""
    from app.services.format_verification import ChangeOutcome, RenderVerification
    from app.services.resume_format import verified_fidelity

    complete = RenderVerification(
        requested=2,
        text_extracted=True,
        outcomes=tuple(
            ChangeOutcome(
                before=f"before {i}", after=f"after {i}", coverage=1.0,
                applied=True, original_remains=False,
            )
            for i in range(2)
        ),
    )
    report = verified_fidelity(_splice_base(), complete)

    assert report.changes_dropped == 0
    assert report.preserved is True, report
    assert report.confidence == "high", report

    byte_identical = verified_fidelity(_splice_base(), None, byte_identical=True)
    assert byte_identical.preserved is True, byte_identical


def test_an_unverifiable_artifact_stays_unknown_rather_than_denied():
    """A file we could not re-read reports ``unverified`` — not a denial either.

    The opposite over-correction to the one this round fixes: counting an
    unreadable artifact as "not preserved" would be its own fabrication.
    """
    from app.services.format_verification import RenderVerification
    from app.services.resume_format import verified_fidelity

    report = verified_fidelity(
        _splice_base(),
        RenderVerification(requested=2, text_extracted=False, outcomes=()),
    )

    assert report.confidence == "unverified"
    assert report.changes_dropped == 0
    assert report.preserved is True, (
        "an unread artifact proves nothing about the mechanism claim; the note "
        f"carries the 'unverified' caveat instead, got {report!r}"
    )


# ---------------------------------------------------------------------------
# (2) The splice branch obeys the SAME completeness gate as its siblings
# ---------------------------------------------------------------------------


def test_pdf_splice_that_cannot_apply_a_change_preserves_the_layout_with_residue(
    client, auth_headers,
):
    """A rewrite the splice engine cannot place ⇒ the layout is STILL preserved.

    MODELS-LIVE R-FMT reverses the round-2 policy that dropped the whole
    two-column layout to the branded template over one out-of-scope rewrite (the
    live cfe7a0f→c12187 single-column divergence). The mandate is *tailored =
    baseline with ONLY text changed, visual format intact*, so the splice ships
    the preserved layout, applies the placeable rewrite, and discloses the
    unplaceable one as residue with its baseline wording intact. Falling back to
    the branded render is reserved for a genuine WHOLE-document loss or an
    unreadable file — the U2b CRITICAL guarantee, which stays intact.
    """
    baseline, left, right = _seed_bundled_baseline(client, auth_headers)
    left_after = f"Product and delivery leadership across regulated platforms; {left}"
    head, _, tail = right.partition(":")
    right_after = f"{head}: Re-scoped for the target role, {tail.strip()}"
    child = _tailor_child(
        client, auth_headers, baseline, {"bullet-0": left_after, "bullet-1": right_after}
    )

    res = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers)
    assert res.status_code == 200, res.text
    report = res.json()

    assert report["method"] == "pdf-in-place-splice", (
        "the preserved layout ships; it is NOT dropped to the branded template "
        f"over one out-of-scope rewrite, got {report!r}"
    )
    assert report["formatPreserved"] is True, report
    assert report["confidence"] == "partial", report
    assert report["changesRequested"] == 2
    assert report["changesApplied"] == 1, report
    assert report["changesDropped"] == 1, report
    note = report["note"].lower()
    assert "aether template" not in note, note
    assert "layout is preserved" in note and "original wording" in note, note

    download = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert download.status_code == 200, download.text
    assert download.headers["X-Aether-Changes-Applied"] == "1"
    assert download.headers["X-Aether-Changes-Dropped"] == "1"
    assert download.headers["X-Aether-Format-Method"] == "pdf-in-place-splice"

    # Independently of the endpoint's own report: the placeable rewrite is in the
    # file (checked on the grey-body half after the bold lead-in, which the
    # splice draws through a single TextWriter, so it is a contiguous run), and
    # the unplaceable one keeps its baseline wording (residue).
    text = " ".join(_pdf_text(download.content).split())
    assert right_after.partition(":")[2].strip()[:50] in text, (
        "the placeable rewrite must be in the downloaded file"
    )
    assert left in text, (
        "the unplaceable rewrite keeps its baseline wording in the preserved layout"
    )


def test_a_splice_that_applies_every_change_still_returns_the_original_layout(
    client, auth_headers,
):
    """The flagship path is untouched: a complete splice keeps the user's PDF."""
    baseline, _left, right = _seed_bundled_baseline(client, auth_headers)
    head, _, tail = right.partition(":")
    right_after = f"{head}: Re-scoped for the target role, {tail.strip()}"
    child = _tailor_child(client, auth_headers, baseline, {"bullet-1": right_after})

    report = client.get(
        f"/resumes/{child['id']}/fidelity", headers=auth_headers
    ).json()

    assert report["method"] == "pdf-in-place-splice", report
    assert report["formatPreserved"] is True, report
    assert report["changesRequested"] == 1
    assert report["changesApplied"] == 1, report
    assert report["changesDropped"] == 0, report
    assert report["confidence"] == "high", report
    assert _right_column_bullet(), "fixture sanity: bundled right-column bullets exist"
