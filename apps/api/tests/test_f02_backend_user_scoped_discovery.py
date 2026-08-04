"""F-02 (backend half) — discovery is the CALLER'S search, or it is refused.

The frontend half landed in ``a090f81``: ``/dashboard/jobs`` and the Scout card
now derive the search from the signed-in user's profile and ASK when that
profile is empty. The backend still fabricated one:

* ``PipelineRunRequest`` defaulted ``query`` to ``_DEFAULT_QUERY``
  (= ``ROLE_FAMILY_QUERY``, a 10-term PM/BA family) and ``location`` to
  ``"Melbourne, Australia"``. ``runPipeline()`` posts ``body: {}``, so pydantic
  materialised those literals, ``params.get("query")`` was truthy, and
  ``_user_search_defaults`` — the profile-derived helper that already existed —
  was NEVER consulted. Every user's "Run All" scouted the same hardcoded
  persona and wrote its unfiltered results to their own board.
* ``_user_search_defaults`` itself substituted the SAME two literals for a user
  whose profile was empty, so even the reachable path fabricated a search
  rather than admitting it had nothing to search for.

Both are the same defect: asserting a job search the customer never asked for.
These tests pin the honest contract — derive it from the user, or refuse and
say which profile field is missing. Never substitute.
"""
from __future__ import annotations

import pytest
from conftest import seed_own_resume, seed_search_target


def _register_and_login(client, email: str) -> dict[str, str]:
    creds = {"email": email, "password": "Str0ngPass1"}
    register = client.post("/auth/register", json=creds)
    assert register.status_code in (201, 409), register.text
    token = client.post("/auth/login", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class _RecordingScout:
    """Stands in for ``ScoutAgent`` and records exactly what it was asked to
    search for. Class-level so a refused run is provably a run that never
    happened, not merely one that returned nothing."""

    calls: list[tuple[str, str, str]] = []

    def run(self, user_id, query, location):
        from app.agents.scout_agent import ScoutResult

        type(self).calls.append((user_id, query, location))
        return ScoutResult()


@pytest.fixture()
def recording_scout(monkeypatch):
    _RecordingScout.calls = []
    monkeypatch.setattr("app.routers.agents.ScoutAgent", _RecordingScout)
    return _RecordingScout


#: The literals the router used to substitute. Named here so a regression that
#: reintroduces either one fails loudly by name.
_HARDCODED_TERMS = (
    "business analyst", "product owner", "product manager", "program manager",
    "project manager", "delivery manager", "technical program manager",
    "scrum master", "agile coach", "transformation manager",
)
_HARDCODED_LOCATION = "Melbourne, Australia"


def _assert_not_the_hardcoded_persona(query: str, location: str) -> None:
    lowered = query.lower()
    foreign = [t for t in _HARDCODED_TERMS if t in lowered]
    assert not foreign, (
        f"the hardcoded PM/BA persona leaked into this user's search: {foreign} "
        f"in {query!r}"
    )
    assert location != _HARDCODED_LOCATION


# ---------------------------------------------------------------------------
# 1) POST /agents/pipeline/run — the "Run All" route named in ADR-F02 §6.
# ---------------------------------------------------------------------------


class TestPipelineRunDerivesTheSearchFromTheUser:
    def test_empty_body_scouts_the_users_own_role_not_the_hardcoded_persona(
        self, client, auth_headers, recording_scout
    ):
        """``runPipeline()`` posts ``{}``. That must reach ScoutAgent as THIS
        user's configured target, never the router's own literal."""
        # The pipeline's fitScorer node scores against the caller's OWN résumé
        # and refuses without one — unrelated to F-02, but the run has to get
        # past it to prove what the scout step was asked to search for.
        seed_own_resume(client, auth_headers)
        seed_search_target(
            client, auth_headers,
            target_role="Senior Data Scientist", location="Sydney, Australia",
        )

        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 200, resp.text

        assert recording_scout.calls, "the pipeline never reached the scout step"
        _user, query, location = recording_scout.calls[0]
        assert query == "Senior Data Scientist"
        assert location == "Sydney, Australia"
        _assert_not_the_hardcoded_persona(query, location)

    def test_two_users_get_two_different_searches(self, client, recording_scout):
        a = _register_and_login(client, "f02-pipeline-a@aether.dev")
        b = _register_and_login(client, "f02-pipeline-b@aether.dev")
        for headers in (a, b):
            seed_own_resume(client, headers)
        seed_search_target(
            client, a, target_role="Registered Nurse", location="Perth, Australia"
        )
        seed_search_target(
            client, b, target_role="Data Engineer", location="Auckland, New Zealand"
        )

        assert client.post(
            "/agents/pipeline/run", json={}, headers=a
        ).status_code == 200
        assert client.post(
            "/agents/pipeline/run", json={}, headers=b
        ).status_code == 200

        searched = [(q, loc) for _u, q, loc in recording_scout.calls]
        assert ("Registered Nurse", "Perth, Australia") in searched
        assert ("Data Engineer", "Auckland, New Zealand") in searched

    def test_empty_profile_is_refused_by_name_not_substituted(
        self, client, auth_headers, recording_scout
    ):
        """A user who has told us nothing gets an honest 422 naming the missing
        profile fields — the backend mirror of the frontend's prompt. It must
        NOT fall back to the role family (that IS the defect).

        The detail is a plain STRING on purpose: the Agents console renders a
        backend 422 through ``agents-feedback.runErrorNotice``, whose
        ``extractApiJsonDetail`` surfaces only a string ``detail``. A structured
        object would fall through to that branch's hardcoded "run Scout to
        discover jobs" copy — which for THIS refusal is both wrong and
        misdirecting (running Scout is refused for the same reason). So the
        refusal must carry its own honest sentence."""
        # Résumé seeded so the ONLY thing this user is missing is a search
        # target: without it the run 422s at the fitScorer node instead, and
        # this test would assert a status code it was already getting.
        seed_own_resume(client, auth_headers)

        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 422, resp.text

        detail = resp.json()["detail"]
        assert isinstance(detail, str), detail
        lowered = detail.lower()
        assert "target role" in lowered
        assert "location" in lowered
        assert "settings" in lowered, "the refusal must say where to fix it"

        assert not recording_scout.calls, (
            "a refused run must never have searched: "
            f"{recording_scout.calls}"
        )

    def test_a_refused_pipeline_records_and_bills_nothing(
        self, client, auth_headers, recording_scout
    ):
        """The refusal happens BEFORE the supervisor node's ``_record_run``, so
        a user with no profile is not charged a run (nor left with a dangling
        audit row) for a search that never happened."""
        seed_own_resume(client, auth_headers)
        assert client.post(
            "/agents/pipeline/run", json={}, headers=auth_headers
        ).status_code == 422
        runs = client.get("/agents/runs", headers=auth_headers).json()
        assert runs == [], runs

    def test_half_a_profile_is_refused_naming_only_the_missing_half(
        self, client, auth_headers, recording_scout
    ):
        seed_own_resume(client, auth_headers)
        seed_search_target(
            client, auth_headers, target_role="Senior Data Scientist", location=""
        )
        resp = client.post("/agents/pipeline/run", json={}, headers=auth_headers)
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "location" in detail.lower()
        assert "target role" not in detail.lower(), (
            "the refusal must name only what is actually missing: " + detail
        )
        assert not recording_scout.calls


# ---------------------------------------------------------------------------
# 2) POST /agents/scout/run (Sync Now / Settings' Sync All / the Scout card /
#    the discovery cron) and the shared ``_dispatch`` seam beneath it.
# ---------------------------------------------------------------------------


class TestScoutRunDerivesTheSearchFromTheUser:
    def test_omitted_query_and_location_fall_back_to_the_users_profile(
        self, client, auth_headers, recording_scout
    ):
        seed_search_target(
            client, auth_headers,
            target_role="Veterinary Nurse", location="Hobart, Australia",
        )
        resp = client.post("/agents/scout/run", json={}, headers=auth_headers)
        assert resp.status_code == 202, resp.text
        _user, query, location = recording_scout.calls[0]
        assert query == "Veterinary Nurse"
        assert location == "Hobart, Australia"

    def test_the_audit_row_records_the_search_that_actually_ran(
        self, client, auth_headers, recording_scout
    ):
        """The ``AgentRun.input`` a run is audited with must be the search that
        happened. A body of ``{}`` resolved from the profile used to be
        recorded verbatim — two nulls — leaving no record of what was searched
        for. (Before F-02 it recorded the hardcoded persona, which was worse:
        an audit trail that agreed with the fabrication.)"""
        seed_search_target(
            client, auth_headers, target_role="Marine Biologist", location="Cairns, AU"
        )
        assert client.post(
            "/agents/scout/run", json={}, headers=auth_headers
        ).status_code == 202

        runs = client.get("/agents/runs", headers=auth_headers).json()
        scout_runs = [r for r in runs if r["agentName"] == "scout"]
        assert len(scout_runs) == 1, runs
        recorded = scout_runs[0]["input"]
        if isinstance(recorded, str):
            import json as _json

            recorded = _json.loads(recorded)
        assert recorded["query"] == "Marine Biologist"
        assert recorded["location"] == "Cairns, AU"

    def test_empty_profile_is_refused_by_name(
        self, client, auth_headers, recording_scout
    ):
        resp = client.post("/agents/scout/run", json={}, headers=auth_headers)
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert isinstance(detail, str), detail
        assert "target role" in detail.lower()
        assert "location" in detail.lower()
        assert not recording_scout.calls

    def test_the_shared_dispatch_seam_refuses_too(
        self, client, auth_headers, test_user_id, recording_scout
    ):
        """``_dispatch`` -> ``_agent_callable`` is the seam BOTH the HTTP routes
        and the async worker (``workers.tasks._run_single_agent_body`` /
        ``_pipeline_core``) resolve scout through. Pinning the refusal here is
        what stops a non-HTTP caller from walking around the route guard."""
        from fastapi import HTTPException

        from app.routers.agents import _dispatch

        with pytest.raises(HTTPException) as excinfo:
            _dispatch(test_user_id, "scout", {})
        assert excinfo.value.status_code == 422
        assert "target role" in str(excinfo.value.detail).lower()
        assert not recording_scout.calls

        seed_search_target(
            client, auth_headers, target_role="Quantity Surveyor", location="Darwin, AU"
        )
        _dispatch(test_user_id, "scout", {})
        assert recording_scout.calls[-1][1] == "Quantity Surveyor"
        assert recording_scout.calls[-1][2] == "Darwin, AU"


# ---------------------------------------------------------------------------
# 3) The operator's 30-minute discovery cron must be untouched.
# ---------------------------------------------------------------------------


class TestDiscoveryCronPathStillWorks:
    """``scripts/discovery_cron.sh`` reads ``/auth/me`` and posts an EXPLICIT
    query + location (falling back to its own literals only if the operator's
    account has none), so it never reaches the profile-derived path at all.
    These tests replay that exact sequence."""

    def test_cron_sequence_with_a_configured_operator_profile(
        self, client, auth_headers, recording_scout
    ):
        seed_search_target(
            client, auth_headers,
            target_role="Business Analyst/Project Manager/Scrum Master",
            location="Melbourne",
        )
        # scripts/discovery_cron.sh:90-92 — read the profile, then send it.
        me = client.get("/auth/me", headers=auth_headers).json()
        query = me.get("targetRole") or "Senior Technical Program Manager"
        location = me.get("location") or "Melbourne, AU"

        resp = client.post(
            "/agents/scout/run",
            json={"query": query, "location": location},
            headers=auth_headers,
        )
        assert resp.status_code == 202, resp.text
        _user, sent_query, sent_location = recording_scout.calls[0]
        assert sent_location == "Melbourne"
        # GAP-SRC-001 broadening is preserved for the cron's real live query.
        assert sent_query.startswith("Business Analyst/Project Manager/Scrum Master,")
        assert "product owner" in sent_query.lower()

    def test_cron_own_fallback_still_runs_for_an_operator_with_no_profile(
        self, client, auth_headers, recording_scout
    ):
        """The cron supplies its own literals when ``/auth/me`` is empty. An
        EXPLICIT caller-supplied query is still honoured — the 422 is for
        callers who supply nothing, not for callers we disagree with."""
        resp = client.post(
            "/agents/scout/run",
            json={
                "query": "Senior Technical Program Manager",
                "location": "Melbourne, AU",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 202, resp.text
        assert recording_scout.calls[0][2] == "Melbourne, AU"


# ---------------------------------------------------------------------------
# 4) The query builder no longer invents a query for nobody.
# ---------------------------------------------------------------------------


class TestBuildScoutQueryNeverInventsAQuery:
    def test_no_target_role_is_a_programming_error_not_a_persona(self):
        from app.services.discovery.query_builder import build_scout_query

        with pytest.raises(ValueError, match="target role"):
            build_scout_query(None)
        with pytest.raises(ValueError, match="target role"):
            build_scout_query("   ")

    def test_a_real_role_is_still_broadened_to_its_family(self):
        """The legitimate half of this module (GAP-SRC-001) is untouched: the
        cron's live narrow title still broadens for sourcing volume."""
        from app.services.discovery.query_builder import (
            ROLE_FAMILY_TERMS,
            build_scout_query,
        )

        query = build_scout_query("Senior Technical Program Manager")
        assert query.split(",")[0] == "Senior Technical Program Manager"
        for term in ROLE_FAMILY_TERMS:
            assert term in query.lower()


class TestTheRouterOwnsNoSearchOfItsOwn:
    def test_no_module_level_query_or_location_default_remains(self):
        """ADR-F02 §3's defining property, applied to the backend: there is no
        constant left to fall back to, so "the user told us nothing" can only
        resolve to a refusal. Reintroducing a default means adding the literal
        back here, where this test fails on it."""
        from app.routers import agents as agents_mod

        assert not hasattr(agents_mod, "_DEFAULT_QUERY")
        assert not hasattr(agents_mod, "_DEFAULT_LOCATION")
