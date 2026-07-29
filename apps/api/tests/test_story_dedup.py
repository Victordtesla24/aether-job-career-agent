"""G-P4-STORY-DEDUP-004 — Story content-hash dedup tests.

Provenance: the first six cases (create-dedup, distinct content, same-title,
tags/metrics decorators, whitespace normalisation, list has no duplicates) were
authored in the WIP that ruling R-1/R-2/R-3 parked at
``docs/delivery/parked/test_story_dedup.py.parked``; the ``update``-path and
response-leak cases were added by a concurrent agent's round-2 snapshot. Both
intents are absorbed here verbatim in substance and then EXTENDED with the
coverage the WIP-branch audit (``docs/delivery/WIP-BRANCH-AUDIT-2026-07-29.json``)
proved was missing and which made the original re-land unsafe:

  * ``PUT /stories/{id}`` was exercised by NO test at all, so the parked
    ``update()`` — which appended ``"contentHash" = %s`` without ensuring the
    column exists — would have 500'd on the first update against a schema that
    had never run the lazy DDL.
  * the parked insert path selected the internal sha256 into the API response
    while the dedup-hit path did not, so the response shape differed between
    the two ``POST`` outcomes AND leaked an internal dedup token.

Both defects are pinned below at BOTH layers (repository row + HTTP response).
"""
from __future__ import annotations

import pytest


class TestStoryDedup:
    def test_create_duplicate_returns_existing_not_new(
        self, client, auth_headers,
    ):
        """POST /stories with identical content returns 201 but the same row."""
        payload = {
            "title": "Dedup test story",
            "situation": "Situation text for dedup.",
            "task": "Task text for dedup.",
            "action": "Action text for dedup.",
            "result": "Result text for dedup.",
            "tags": ["dedup"],
        }
        r1 = client.post("/stories", json=payload, headers=auth_headers)
        assert r1.status_code == 201
        first_id = r1.json()["id"]

        # Submit the exact same story — should return the same id.
        r2 = client.post("/stories", json=payload, headers=auth_headers)
        assert r2.status_code == 201
        assert r2.json()["id"] == first_id, (
            "duplicate POST must return the existing row, not create a new one"
        )

    def test_create_different_stories_different_ids(
        self, client, auth_headers,
    ):
        """Different content creates distinct rows."""
        r1 = client.post(
            "/stories",
            json={
                "title": "Story A",
                "situation": "S A",
                "task": "T A",
                "action": "A A",
                "result": "R A",
            },
            headers=auth_headers,
        )
        r2 = client.post(
            "/stories",
            json={
                "title": "Story B",
                "situation": "S B",
                "task": "T B",
                "action": "A B",
                "result": "R B",
            },
            headers=auth_headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]

    def test_same_title_different_body_different_ids(
        self, client, auth_headers,
    ):
        """Title-only match does NOT trigger dedup when content differs."""
        title = "Same Title Story"
        r1 = client.post(
            "/stories",
            json={
                "title": title,
                "situation": "First version S.",
                "task": "First version T.",
                "action": "First version A.",
                "result": "First version R.",
            },
            headers=auth_headers,
        )
        r2 = client.post(
            "/stories",
            json={
                "title": title,
                "situation": "Second version S.",
                "task": "Second version T.",
                "action": "Second version A.",
                "result": "Second version R.",
            },
            headers=auth_headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"], (
            "same title but different body must create separate rows"
        )

    def test_different_tags_metrics_still_deduped(
        self, client, auth_headers,
    ):
        """Tags and metrics are decorators — same core STAR = dedup."""
        core = {
            "title": "Core story",
            "situation": "Core S.",
            "task": "Core T.",
            "action": "Core A.",
            "result": "Core R.",
        }
        r1 = client.post(
            "/stories",
            json={**core, "tags": ["tag-a"], "metrics": {"pct": 50}},
            headers=auth_headers,
        )
        r2 = client.post(
            "/stories",
            json={**core, "tags": ["tag-b"], "metrics": {"pct": 75}},
            headers=auth_headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"], (
            "same core STAR fields must dedup regardless of tags/metrics"
        )

    def test_whitespace_normalized(self, client, auth_headers):
        """Leading/trailing whitespace should not defeat dedup."""
        r1 = client.post(
            "/stories",
            json={
                "title": "  WS Normalized  ",
                "situation": " S ",
                "task": " T ",
                "action": " A ",
                "result": " R ",
            },
            headers=auth_headers,
        )
        r2 = client.post(
            "/stories",
            json={
                "title": "ws normalized",
                "situation": "s",
                "task": "t",
                "action": "a",
                "result": "r",
            },
            headers=auth_headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"], (
            "whitespace-insensitive dedup should match despite spacing"
        )

    def test_list_returns_no_duplicates(self, client, auth_headers):
        """After repeated identical POSTs, list should only have one copy."""
        payload = {
            "title": "List dedup story",
            "situation": "List S.",
            "task": "List T.",
            "action": "List A.",
            "result": "List R.",
        }
        for _ in range(3):
            r = client.post("/stories", json=payload, headers=auth_headers)
            assert r.status_code == 201

        stories = client.get("/stories", headers=auth_headers).json()
        titles = [s["title"] for s in stories]
        assert titles.count("List dedup story") == 1, (
            "list must never return duplicate rows for the same content"
        )

    def test_dedup_is_scoped_to_the_owning_user(self, client, auth_headers):
        """A second user posting identical STAR content gets their OWN row.

        The hash is keyed on ``userId``, so dedup must never collapse two
        different people's stories into one shared row (which would hand user B
        a row owned by user A and, via ``_enrich``, user A's evidence).
        """
        payload = {
            "title": "Cross-user story",
            "situation": "Shared S.",
            "task": "Shared T.",
            "action": "Shared A.",
            "result": "Shared R.",
        }
        r1 = client.post("/stories", json=payload, headers=auth_headers)
        assert r1.status_code == 201

        import uuid

        credentials = {
            "email": f"story-dedup-{uuid.uuid4().hex[:10]}@example.com",
            "password": "Sup3rSecret",
        }
        assert client.post("/auth/register", json=credentials).status_code == 201
        login = client.post("/auth/login", json=credentials)
        assert login.status_code == 200, login.text
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r2 = client.post("/stories", json=payload, headers=other_headers)
        assert r2.status_code == 201
        assert r2.json()["id"] != r1.json()["id"], (
            "content dedup must be scoped per user — never cross-user"
        )

    def test_update_recomputes_content_hash(self, client, auth_headers):
        """PUT /stories/{id} with a STAR field change refreshes the hash.

        This is the path the WIP-branch audit flagged as untested: the parked
        ``update()`` wrote ``"contentHash" = %s`` without ensuring the column
        existed, so the first PUT on a schema that had never run the lazy DDL
        raised ``psycopg2.UndefinedColumn`` -> HTTP 500.

        After updating a story's content, re-POSTing the OLD content must
        create a NEW row (the hash moved), and re-POSTing the NEW content must
        dedup to the updated row.
        """
        story_a = {
            "title": "Update hash test",
            "situation": "Original S.",
            "task": "Original T.",
            "action": "Original A.",
            "result": "Original R.",
        }
        r1 = client.post("/stories", json=story_a, headers=auth_headers)
        assert r1.status_code == 201
        story_id = r1.json()["id"]

        updated = client.put(
            f"/stories/{story_id}",
            json={"action": "Updated A."},
            headers=auth_headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["action"] == "Updated A."

        # Re-POST the ORIGINAL content — a NEW row (the stored hash moved).
        r2 = client.post("/stories", json=story_a, headers=auth_headers)
        assert r2.status_code == 201
        assert r2.json()["id"] != story_id, (
            "re-POSTing original content after update must create a new row"
        )

        # Re-POST the UPDATED content — dedups to the updated row.
        new_content = {**story_a, "action": "Updated A."}
        r3 = client.post("/stories", json=new_content, headers=auth_headers)
        assert r3.status_code == 201
        assert r3.json()["id"] == story_id, (
            "re-POSTing updated content must dedup to the updated row"
        )

    def test_update_of_non_star_fields_only_still_succeeds(
        self, client, auth_headers,
    ):
        """A tags/metrics-only PUT leaves the hash alone and must not 500."""
        r1 = client.post(
            "/stories",
            json={
                "title": "Decoration only update",
                "situation": "S.",
                "task": "T.",
                "action": "A.",
                "result": "R.",
            },
            headers=auth_headers,
        )
        assert r1.status_code == 201
        story_id = r1.json()["id"]

        r2 = client.put(
            f"/stories/{story_id}",
            json={"tags": ["renamed"], "metrics": {"pct": "10%"}},
            headers=auth_headers,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["tags"] == ["renamed"]

        # The identity hash did NOT move, so the ORIGINAL content still dedups.
        r3 = client.post(
            "/stories",
            json={
                "title": "Decoration only update",
                "situation": "S.",
                "task": "T.",
                "action": "A.",
                "result": "R.",
            },
            headers=auth_headers,
        )
        assert r3.status_code == 201
        assert r3.json()["id"] == story_id, (
            "a tags/metrics-only update must not change the content identity"
        )


class TestStoryContentHashNeverLeaks:
    """The sha256 dedup token is INTERNAL — it must never reach a client.

    It is an offline-guessable digest of the user's own STAR text; exposing it
    would both leak an internal identifier and let a client probe/forge dedup
    collisions. Pinned at BOTH layers so a future repository change that
    re-selects the column is still caught by the router, and vice versa.
    """

    _PAYLOAD = {
        "title": "No hash leak",
        "situation": "S.",
        "task": "T.",
        "action": "A.",
        "result": "R.",
    }

    def test_http_responses_never_include_content_hash(self, client, auth_headers):
        # INSERT path.
        r1 = client.post("/stories", json=self._PAYLOAD, headers=auth_headers)
        assert r1.status_code == 201
        assert "contentHash" not in r1.json(), (
            "create (insert) response must not leak the internal contentHash"
        )
        story_id = r1.json()["id"]

        # DEDUP-HIT path — the audit proved this returned a DIFFERENT shape.
        r2 = client.post("/stories", json=self._PAYLOAD, headers=auth_headers)
        assert r2.status_code == 201
        assert r2.json()["id"] == story_id
        assert "contentHash" not in r2.json(), (
            "create (dedup-hit) response must not leak the internal contentHash"
        )
        assert set(r1.json()) == set(r2.json()), (
            "insert and dedup-hit must return the SAME response shape"
        )

        # UPDATE path.
        r3 = client.put(
            f"/stories/{story_id}",
            json={"action": "Updated A."},
            headers=auth_headers,
        )
        assert r3.status_code == 200, r3.text
        assert "contentHash" not in r3.json(), (
            "update response must not leak the internal contentHash"
        )

        # LIST path.
        r4 = client.get("/stories", headers=auth_headers)
        assert r4.status_code == 200
        for story in r4.json():
            assert "contentHash" not in story, (
                "list response must not leak the internal contentHash"
            )

    def test_repository_rows_never_carry_content_hash(self, client, test_user_id):
        """Layer 2: the repository itself must not select the internal column."""
        from app.repositories.story import StoryRepository

        repo = StoryRepository()
        inserted = repo.create(test_user_id, dict(self._PAYLOAD))
        assert "contentHash" not in inserted, (
            "StoryRepository.create (insert) must not return the internal hash"
        )

        deduped = repo.create(test_user_id, dict(self._PAYLOAD))
        assert deduped["id"] == inserted["id"]
        assert "contentHash" not in deduped, (
            "StoryRepository.create (dedup hit) must not return the internal hash"
        )
        assert set(inserted) == set(deduped)

        updated = repo.update(inserted["id"], test_user_id, {"action": "A2."})
        assert updated is not None
        assert "contentHash" not in updated, (
            "StoryRepository.update must not return the internal hash"
        )
        assert set(inserted) == set(updated)

        listed = repo.list_by_user(test_user_id)
        assert listed and all("contentHash" not in row for row in listed)


class TestStoryContentHash:
    """Unit-level properties of the hash function itself."""

    def test_hash_is_stable_and_content_sensitive(self):
        from app.services.dedup import compute_story_content_hash

        args = ("u1", "T", "S", "Ta", "A", "R")
        assert compute_story_content_hash(*args) == compute_story_content_hash(*args)
        # A different user must never collide with the same content.
        assert compute_story_content_hash("u2", *args[1:]) != (
            compute_story_content_hash(*args)
        )
        # Every STAR field participates in the identity.
        for idx in range(1, 6):
            mutated = list(args)
            mutated[idx] = mutated[idx] + " changed"
            assert compute_story_content_hash(*mutated) != (
                compute_story_content_hash(*args)
            ), f"field #{idx} must participate in the content hash"

    def test_hash_is_case_and_whitespace_insensitive(self):
        from app.services.dedup import compute_story_content_hash

        assert compute_story_content_hash("u1", " T ", "S", "Ta", "A", "R") == (
            compute_story_content_hash("u1", "t", "s", "ta", "a", "r")
        )


def test_ensure_story_dedup_column_is_idempotent():
    """Lazy DDL (ADR-TR-1) must be safe to call repeatedly, like its siblings."""
    from app.db import ensure_story_dedup_column, get_connection

    ensure_story_dedup_column()
    ensure_story_dedup_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'StoryEntry'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'contentHash'"
            )
            assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("method", ["create", "update"])
def test_repository_ensures_the_dedup_column_before_using_it(
    method, client, test_user_id, monkeypatch,
):
    """BOTH write paths must ensure the lazy column — the audit's blocker #2.

    ``update()`` in the parked WIP wrote ``"contentHash" = %s`` but only
    ``create()`` called the DDL helper, so the first PUT on a schema that had
    never run it raised ``UndefinedColumn`` -> HTTP 500 in production. The
    process-wide ``_story_dedup_column_ready`` latch means a plain end-to-end
    test cannot see the missing call once any earlier test warmed it, so the
    call itself is what gets pinned here.
    """
    import app.repositories.story as story_module

    repo = story_module.StoryRepository()
    seed = repo.create(test_user_id, {
        "title": "DDL guard seed", "situation": "S.", "task": "T.",
        "action": "A.", "result": "R.",
    })

    calls: list[str] = []
    monkeypatch.setattr(
        story_module, "ensure_story_dedup_column", lambda: calls.append(method)
    )
    if method == "create":
        repo.create(test_user_id, {
            "title": "DDL guard other", "situation": "S2.", "task": "T2.",
            "action": "A2.", "result": "R2.",
        })
    else:
        assert repo.update(seed["id"], test_user_id, {"action": "A3."}) is not None
    assert calls == [method], (
        f"StoryRepository.{method} must call ensure_story_dedup_column()"
    )
