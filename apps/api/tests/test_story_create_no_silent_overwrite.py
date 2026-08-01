"""GMV4-story-005 (BLOCKER) — silent data loss on ``POST /stories``.

Found on production by an independent adversarial reviewer: creating a story
returns ``201 Created`` while the create-time paraphrase-merge guard
(``StoryRepository.create`` -> ``apps/api/app/services/story_paraphrase.py``,
``CREATE_TIME_THRESHOLDS``) silently folds the submission into a DIFFERENT
pre-existing row instead. A separate tester read the same mechanism as "dedup
working correctly" (same row id, unioned tags, unchanged card count) — both
observations describe one behaviour; the adversarial reading is correct for a
user who typed a NEW story, got back ``201 Created``, and had a different
existing row's content silently touched with no notice and no undo.

Two things are pinned separately here:

(a) The status code lies. ``201 Created`` asserts a NEW resource was created.
    A merge into an existing row created nothing.
(b) The user is never told a merge happened, and the response gives no way to
    tell a genuine create from a merge.

A third test is the crux: does the merge actually DISCARD the user's newly
submitted text (real, unrecoverable data loss) or does it retain it (a
status-code/disclosure defect only, since nothing the user typed is lost —
only the OLD pre-existing row's prior content is gone)? See the bottom of
this file for the answer this repo's code gives today.

HONEST CONTRACT PINNED BY THESE TESTS: a merge response is ``200 OK`` (not
``201 Created`` — nothing new exists at a new URI) and carries an explicit
``"merged": true`` body flag identifying which row absorbed the input via the
returned ``id``. ``409 Conflict`` was considered and rejected: a paraphrase
merge is not an error the client must resolve — it is a successful save that
happens to have been folded into existing content, so ``200`` + an explicit
flag is the more honest and more actionable contract (a client can branch on
it to show "Merged into <title>" instead of a bare success toast).
"""
from __future__ import annotations

# The pre-existing story already in the Story Bank.
_ORIGINAL = {
    "title": "Led Cloud Migration of the Core Banking Platform",
    "situation": (
        "The bank's core banking platform ran on aging on-premises "
        "infrastructure with frequent outages during peak trading hours."
    ),
    "task": "I was asked to lead the migration program to a cloud native architecture.",
    "action": (
        "I migrated the core banking platform from on-premises data centers to a "
        "cloud native Kubernetes architecture, coordinating with security, network, "
        "and application teams across four release trains."
    ),
    "result": (
        "Reduced deployment cycle time by 40 percent and improved platform uptime "
        "to 99.9 percent while cutting infrastructure costs by 2 million dollars "
        "annually."
    ),
    "tags": ["cloud", "banking"],
}

# A DIFFERENT story the user actually typed: distinct situation/task framing
# (irrelevant to the paraphrase signal, which only looks at title +
# action+result) and a near-identical achievement re-telling — which is
# exactly what makes CREATE_TIME_THRESHOLDS treat it as "the same
# achievement" as `_ORIGINAL`. It is still NEW content the user submitted,
# not a resubmission of the original text (verified offline against
# `app.services.story_paraphrase.is_paraphrase_match` before writing this
# file: title Jaccard 0.714/5-shared, achievement Jaccard 0.786/22-shared —
# both clear CREATE_TIME_THRESHOLDS with margin).
_NEW_SUBMISSION = {
    "title": "Led Cloud Migration of the Core Banking System",
    "situation": (
        "Totally distinct situation framing describing pressure from the board to "
        "modernise before the next regulatory audit cycle, unrelated wording to "
        "the original story above."
    ),
    "task": (
        "Totally distinct task framing describing being pulled in mid-program to "
        "rescue a stalled vendor engagement, unrelated wording to the original "
        "story above."
    ),
    "action": (
        "I migrated the core banking platform from on-premises data centers to a "
        "cloud native Kubernetes architecture, coordinating with security, network, "
        "and application teams across four release trains and two vendors."
    ),
    "result": (
        "Reduced deployment cycle time by 40 percent and improved platform uptime "
        "to 99.9 percent while cutting infrastructure annual run costs by 2 million "
        "dollars."
    ),
    "tags": ["kubernetes", "vendor-management"],
}


class TestStoryCreateNoSilentOverwrite:
    def test_create_returning_an_existing_row_does_not_report_201_created(
        self, client, auth_headers,
    ):
        first = client.post("/stories", json=_ORIGINAL, headers=auth_headers)
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]

        merged = client.post("/stories", json=_NEW_SUBMISSION, headers=auth_headers)
        assert merged.json().get("id") == first_id, (
            "test setup assumption failed: this payload must paraphrase-merge "
            "into the original row for the assertions below to be meaningful"
        )
        assert merged.status_code == 200, (
            f"a request that MERGED into an existing story reported HTTP "
            f"{merged.status_code} — 201 Created asserts a NEW resource was "
            "created at a new URI, which is false here: nothing was created"
        )

    def test_create_merge_is_disclosed_in_the_response_body(
        self, client, auth_headers,
    ):
        first = client.post("/stories", json=_ORIGINAL, headers=auth_headers)
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]

        merged = client.post("/stories", json=_NEW_SUBMISSION, headers=auth_headers)
        body = merged.json()
        assert body.get("id") == first_id, (
            "test setup assumption failed: this payload must paraphrase-merge "
            "into the original row for the assertions below to be meaningful"
        )
        assert body.get("merged") is True, (
            "the response body must explicitly disclose that this POST was "
            "absorbed into an existing story (e.g. a `merged: true` field) so "
            "the client can tell the user their save changed a different, "
            "pre-existing story instead of silently returning a bare success"
        )

    def test_create_merge_preserves_the_users_new_content(
        self, client, auth_headers,
    ):
        """THE CRUX. Does the merge discard the user's newly typed text?"""
        first = client.post("/stories", json=_ORIGINAL, headers=auth_headers)
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]

        merged = client.post("/stories", json=_NEW_SUBMISSION, headers=auth_headers)
        body = merged.json()
        assert body.get("id") == first_id, (
            "test setup assumption failed: this payload must paraphrase-merge "
            "into the original row for the assertions below to be meaningful"
        )
        for field in ("title", "situation", "task", "action", "result"):
            assert body[field] == _NEW_SUBMISSION[field], (
                f"merge must retain the user's NEWLY SUBMITTED {field!r} text — "
                f"got {body[field]!r}, expected {_NEW_SUBMISSION[field]!r}. If "
                "this assertion fails, the user's new submission was discarded "
                "and the OLD row's prior content silently survived instead: "
                "genuine, unrecoverable data loss, not just a status-code lie."
            )

    def test_create_of_a_genuinely_distinct_story_still_creates(
        self, client, auth_headers,
    ):
        """Positive control — a clearly different story still creates for real."""
        distinct = {
            "title": "Negotiated a multi-year vendor contract renewal",
            "situation": (
                "Our primary SaaS vendor proposed a 3x price increase at the "
                "annual renewal."
            ),
            "task": "I was asked to renegotiate the contract before the deadline.",
            "action": (
                "I built a competitive pricing benchmark, ran a structured RFP "
                "against two alternative vendors, and led the renewal negotiation."
            ),
            "result": (
                "Secured a renewal at an 8 percent increase instead of the "
                "proposed 300 percent, saving 1.4 million dollars over the "
                "contract term."
            ),
            "tags": ["procurement"],
        }
        resp = client.post("/stories", json=distinct, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        assert resp.json().get("merged") in (False, None), (
            "a genuinely distinct story must not be reported as a merge"
        )
        stories = client.get("/stories", headers=auth_headers).json()
        assert any(s["id"] == resp.json()["id"] for s in stories), (
            "the newly created story must actually be visible in the list"
        )
