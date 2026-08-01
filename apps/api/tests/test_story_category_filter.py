"""GMV4-stories-006 (MEDIUM) — ``GET /stories?category=...`` ignores the filter.

``list_stories`` (apps/api/app/routers/stories.py:140) declares only a
``job_id`` query parameter — there is no ``category`` parameter at all. FastAPI
silently accepts and ignores unrecognised query params, so
``GET /stories?category=Leadership`` returns every story regardless of
category: the filter is a no-op, not merely buggy.
"""
from __future__ import annotations


def _create(client, auth_headers, *, title, tags):
    resp = client.post(
        "/stories",
        json={
            "title": title,
            "situation": f"Situation text for {title}.",
            "task": f"Task text for {title}.",
            "action": f"Action text for {title}.",
            "result": f"Result text for {title}.",
            "tags": tags,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestStoryCategoryFilter:
    def test_stories_category_filter_is_applied_server_side(
        self, client, auth_headers,
    ):
        # `_derive_category` (apps/api/app/routers/stories.py:81) maps tags
        # containing "risk" to "Risk & Compliance" and a title/tags with no
        # category keyword at all to the "Delivery" default — two seeded
        # stories that land in different derived categories.
        risk_story = _create(
            client, auth_headers,
            title="Audited third-party vendor risk controls",
            tags=["risk", "compliance"],
        )
        delivery_story = _create(
            client, auth_headers,
            title="Wrote new customer onboarding documentation",
            tags=["docs"],
        )

        # Sanity check on the fixture data itself, not the defect: confirm the
        # two seeded stories really do land in different derived categories,
        # otherwise the filter assertion below would prove nothing.
        unfiltered = {
            s["id"]: s["category"]
            for s in client.get("/stories", headers=auth_headers).json()
        }
        assert unfiltered[risk_story["id"]] == "Risk & Compliance", unfiltered
        assert unfiltered[delivery_story["id"]] == "Delivery", unfiltered

        filtered = client.get(
            "/stories",
            params={"category": "Risk & Compliance"},
            headers=auth_headers,
        ).json()
        filtered_ids = {s["id"] for s in filtered}
        assert risk_story["id"] in filtered_ids, (
            "the matching-category story must be present in a filtered response"
        )
        assert delivery_story["id"] not in filtered_ids, (
            "GET /stories?category=Risk & Compliance returned a Delivery-category "
            "story too — the category filter is being ignored server-side"
        )

    def test_stories_unknown_category_returns_empty_not_everything(
        self, client, auth_headers,
    ):
        _create(
            client, auth_headers,
            title="Shipped a customer-facing feature on schedule",
            tags=["docs"],
        )

        resp = client.get(
            "/stories",
            params={"category": "Nonexistent-Category-XYZ"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == [], (
            "an unmatched category must return an empty list, not the whole "
            "collection — silently ignoring the filter and returning everything "
            "is the dangerous shape (a user filtering to a category they think "
            "is empty would instead see every other category's stories)"
        )
