"""U2b round 5 — the tailored ground truth is the parent's WHOLE inventory.

Round 2 established the rule that a tailored version is never measured against
its own parse: a child whose stored text has already lost a section has nothing
left to report missing. :func:`app.services.resume_completeness.baseline_record`
implemented that rule for the résumé's TEXT — it takes the parent's ``raw_text``
— but not for its BULLETS: it overwrote the parent's persisted bullet list
wholesale with the child's own::

    payload["bullets"] = tailored          # the child's list, entire

So the ground truth still depended on the child's bullet list being complete.
Every bullet the parent persists that the child's list does not carry — an
original nobody selected for rewrite — simply stopped being expected, and
therefore could not be reported missing by ``verify_completeness``,
``GET /resumes/{id}/fidelity``, the download's verification header, Studio's
"Verified" badge, or the repair census that decides which production rows get
repaired (U2b round-4 land review, 2026-08-14).

That divergence is not hypothetical. The platform persists a résumé's bullets
from a POSITIONAL read of the source PDF
(``app.services.resume_pdf.extract_pdf_bullets``, wired into
``app.agents.tailor_agent``'s bullet healing) while ``raw_text`` stays the flat
text layer — and on the live two-column artifact of record
(résumé ``c12187d107bf994471844e09a``) 10 of the 25 persisted bullets are not
stated verbatim anywhere in that flat text; they exist ONLY in the record's own
bullet list. ``test_the_live_parent_persists_bullets_its_flat_text_never_states``
pins that against the checked-in live fixture, so the shape the rest of this
module exercises is the platform's real one, not an invented one.

The rule pinned here: the tailored contract is the parent's full inventory, with
each slot the tailoring ACTUALLY rewrote expecting the approved AFTER text and
every untouched original expected verbatim. The before → after mapping comes
from the one slot-claiming pass ``rebuild_raw_text`` and ``_substitute_bullets``
already use — never a second matcher, because two matchers drift, and drift is
what rounds 1 through 3 were each spent undoing.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.resume_completeness import build_resume_content, verify_completeness
from app.services.resume_document import rebuild_raw_text
from app.services.resume_repair import raw_text_losses, repair_sections
from app.services.resume_tailor import extract_bullets

_FIXTURES = Path(__file__).parent / "fixtures" / "u2b"

#: The flat text layer of the user's upload — what ``raw_text`` stores.
PARENT_TEXT = (
    "PRIYA NARAYANAN\n"
    "WORK EXPERIENCE\n"
    "Delivery Lead\n"
    "Northwind Bank\n"
    "2019 - 2024 | Sydney\n"
    "  • Ran the payments migration onto a cloud-native platform across four"
    " release trains.\n"
    "  • Cut release lead time from six weeks to four working days for the whole"
    " squad.\n"
    "  • Mentored four graduate engineers through their first year on the"
    " programme.\n"
    "SKILLS\n"
    "  • Python, Terraform, Postgres, Kubernetes and GitHub Actions.\n"
    "CERTIFICATIONS\n"
    "  • Certified Scrum Master, renewed 2024.\n"
)

#: A bullet the POSITIONAL extractor recovered from the source PDF's sidebar and
#: persisted, which the flat text layer never states as one contiguous line —
#: the live shape pinned by ``test_the_live_parent_persists_bullets_...`` below.
POSITIONAL_ONLY = (
    "Chaired the Sydney office diversity and inclusion council for two"
    " consecutive years."
)

REWRITE_BEFORE = (
    "Ran the payments migration onto a cloud-native platform across four release"
    " trains."
)
REWRITE_AFTER = (
    "Delivered the payments migration onto a cloud-native platform, cutting run"
    " cost 30% across four release trains."
)


def _parent() -> dict:
    """The user's upload: the flat text AND the persisted positional bullets."""
    return {
        "id": "parent-1",
        "label": "Priya Narayanan",
        "sections": {
            "raw_text": PARENT_TEXT,
            "bullets": [
                {"text": text}
                for text in [*extract_bullets(PARENT_TEXT), POSITIONAL_ONLY]
            ],
        },
    }


def _child() -> dict:
    """A tailored version whose persisted list carries ONLY what it rewrote."""
    return {
        "id": "child-1",
        "parentId": "parent-1",
        "sections": {
            "raw_text": rebuild_raw_text(PARENT_TEXT, [REWRITE_AFTER]),
            "bullets": [{"text": REWRITE_AFTER}],
        },
    }


def _download(record: dict) -> bytes:
    """The produced artifact's text layer, as the download would carry it."""
    return str((record.get("sections") or {})["raw_text"]).encode()


# --- (a) an untouched original that the child never carried ------------------


def test_an_untouched_original_missing_from_the_download_is_named() -> None:
    """The blind spot itself: an original nobody asked to rewrite goes missing
    from the produced file, and the verifier must say WHICH one."""
    content = build_resume_content(_child(), _parent())
    assert POSITIONAL_ONLY in content.bullets, (
        "the parent persists this bullet, so a tailored download still owes it"
    )

    verification = verify_completeness(_download(_child()), "text/plain", content)

    assert not verification.complete
    assert any(
        "diversity and inclusion council" in item for item in verification.missing
    ), verification.missing


def test_the_tailored_contract_holds_every_bullet_the_parents_own_does() -> None:
    """No bullet may leave the ground truth just because a child was created."""
    parent, child = _parent(), _child()
    parent_bullets = set(build_resume_content(parent).bullets)
    child_bullets = set(build_resume_content(child, parent).bullets)

    # The one bullet the tailoring rewrote is expected as its APPROVED text; the
    # rest of the parent's inventory must survive verbatim.
    assert parent_bullets - child_bullets == {REWRITE_BEFORE}
    assert REWRITE_AFTER in child_bullets


# --- (b) an approved rewrite is the expectation, not an addition to it -------


def test_an_approved_rewrite_replaces_the_original_it_rewrote() -> None:
    """The original's absence from the file is the POINT of tailoring, so it is
    not a loss — only the un-rewritten inventory is. A merge that expected BOTH
    would report every successful tailoring run as damaged."""
    parent, child = _parent(), _child()
    content = build_resume_content(child, parent)

    assert REWRITE_AFTER in content.bullets
    assert REWRITE_BEFORE not in content.bullets

    complete_download = rebuild_raw_text(PARENT_TEXT, list(content.bullets))
    verification = verify_completeness(
        complete_download.encode(), "text/plain", content
    )

    assert verification.complete, verification.missing
    # And the check is real: the original wording genuinely is not in the file.
    assert "Ran the payments migration" not in complete_download


# --- (c) the live artifact of record ----------------------------------------


def _live_parent() -> dict:
    raw_text = (_FIXTURES / "live-two-column-resume-text.txt").read_text()
    return {
        "id": "cfe7a0f27991821dc73f265cd",
        "sections": {
            "raw_text": raw_text,
            "bullets": json.loads(
                (_FIXTURES / "live-persisted-bullets.json").read_text()
            ),
        },
    }


def test_the_live_parent_persists_bullets_its_flat_text_never_states() -> None:
    """The shape this module exercises is the platform's real one.

    The live record's bullet list comes from the positional PDF read; its
    ``raw_text`` is the flat two-column text layer. They are not the same list.
    """
    parent = _live_parent()
    flat = set(extract_bullets(parent["sections"]["raw_text"]))
    persisted = [bullet["text"] for bullet in parent["sections"]["bullets"]]

    unstated = [text for text in persisted if text not in flat]

    assert len(unstated) >= 10, len(unstated)


def test_the_live_artifact_stays_complete_against_the_merged_baseline() -> None:
    """Round 4 repaired résumé ``c12187d107bf994471844e09a`` in production. The
    stricter ground truth must not retroactively call that repair incomplete."""
    parent = _live_parent()
    persisted = [bullet["text"] for bullet in parent["sections"]["bullets"]]
    child = {
        "id": "c12187d107bf994471844e09a",
        "parentId": parent["id"],
        "sections": {
            "raw_text": rebuild_raw_text(parent["sections"]["raw_text"], persisted),
            "bullets": [{"text": text} for text in persisted],
        },
    }

    content = build_resume_content(child, parent)
    verification = verify_completeness(_download(child), "text/plain", content)

    assert verification.complete, verification.missing


# --- (d) the repair census inherits the fix ---------------------------------


def test_the_census_flags_and_repairs_a_child_missing_an_untouched_original() -> None:
    parent, child = _parent(), _child()

    losses = raw_text_losses(child, parent)
    assert any("diversity and inclusion council" in item for item in losses), losses

    repaired = repair_sections(child, parent)
    assert repaired is not None
    assert POSITIONAL_ONLY in repaired["raw_text"]
    # ADDITIVE and reversible: the damaged text is kept verbatim.
    assert repaired["rawTextRepair"]["previousRawText"] == child["sections"]["raw_text"]

    healed = {**child, "sections": repaired}
    assert raw_text_losses(healed, parent) == ()
    # Idempotent: a repaired row is left completely alone on the next pass.
    assert repair_sections(healed, parent) is None


def test_a_bullet_the_resume_does_file_under_a_heading_is_still_policed() -> None:
    """The census may only forgive a mis-filing the ground truth cannot state.

    A bullet the parent never states in its own ``raw_text`` is appended to the
    document model under no heading, and writing it back out necessarily lands
    it under whichever section precedes it — so it has no heading to be moved
    away from. That exemption must not spread: a bullet the résumé DOES file
    under a named heading is still a false claim about where the person did the
    work when the stored text moves it, which is the loss round 4 taught the
    census to see.
    """
    parent = _parent()
    moved = "Mentored four graduate engineers through their first year on the programme."
    misfiled_text = PARENT_TEXT.replace(f"  • {moved}\n", "").replace(
        "SKILLS\n", f"SKILLS\n  • {moved}\n"
    )
    child = {
        "id": "child-misfiled",
        "parentId": "parent-1",
        "sections": {"raw_text": misfiled_text, "bullets": [{"text": REWRITE_AFTER}]},
    }

    losses = raw_text_losses(child, parent)

    assert any(
        "mentored four graduate engineers" in item
        and "filed under “SKILLS”" in item
        and "not “WORK EXPERIENCE”" in item
        for item in losses
    ), losses
    # …and the headingless original is still reported plainly missing, not as a
    # mis-filing it could never have committed.
    assert any("diversity and inclusion council" in item for item in losses), losses
    assert not any(
        "diversity and inclusion council" in item and "filed under" in item
        for item in losses
    ), losses


# --- (e) round trip ---------------------------------------------------------


def test_a_child_regenerated_by_rebuild_raw_text_verifies_complete() -> None:
    """One document model: what the rebuild writes is what the verifier expects."""
    parent, child = _parent(), _child()
    repaired = repair_sections(child, parent)
    assert repaired is not None
    healed = {**child, "sections": repaired}

    content = build_resume_content(healed, parent)
    verification = verify_completeness(_download(healed), "text/plain", content)

    assert verification.complete, verification.missing
    assert REWRITE_AFTER in repaired["raw_text"]
    assert POSITIONAL_ONLY in repaired["raw_text"]


def test_a_child_that_persisted_no_bullets_keeps_the_parents_whole_inventory() -> None:
    """Nothing to map in still means the parent's own résumé, entire."""
    parent = _parent()
    child = {"id": "child-2", "parentId": "parent-1", "sections": {"raw_text": ""}}

    assert set(build_resume_content(child, parent).bullets) == set(
        build_resume_content(parent).bullets
    )
