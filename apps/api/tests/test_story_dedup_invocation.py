"""GOLD-MASTER-V4 §22 STEP 2 — GMV4-story-002 (HIGH): story de-duplication
retroactive-merge gap.

ROOT CAUSE (verified first-hand by the risk-officer before this file was
written): ``merge_duplicate_stories``
(``app.services.story_dedup_migration``) has ZERO production call sites.
``grep -rn "merge_duplicate_stories" apps/api/app apps/api/scripts`` returns
only its own definition, its own docstring's usage example, and one
cross-reference from ``story_paraphrase.py``'s docstring — no router, admin
action, maintenance script, or scheduled job invokes it. Insert-time
prevention (``StoryRepository.create`` -> ``story_paraphrase.py``,
``CREATE_TIME_THRESHOLDS``) is separately VERIFIED WORKING on production and
is NOT covered here. This file covers ONLY the retroactive bulk-merge gap
and the safety properties the risk-officer requires before that sweep is
ever wired to a real entrypoint and pointed at live data:

  1. a genuine, reachable production invocation path (today: none)
  2. a dry-run mode that proposes merges with scores and writes nothing
     (today: no ``dry_run`` parameter exists at all)
  3. the MERGE shape itself: oldest row's id survives, tags/metrics unioned
     (today: this is the ONE property already correctly implemented)
  4. a hard guarantee that a merge never physically DELETEs a story row —
     unrecoverable, user-authored career history (today: it does delete)
  5. before/after row counts as proof-of-run (§8.1(a)) (today: absent)
  6. per-user scoping — never merge across two users' story banks (today:
     already correctly scoped, by construction of ``list_by_user(user_id)``)

Run under the shared test-DB lock (aether_test schema is shared across
concurrent swarms — see docs/delivery/../aether-shared-test-db-flakiness
context)::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \\
        tests/test_story_dedup_invocation.py -v

This file NEVER implements the fix (test-author brief). Tests 3 and 6 are
NOT expected to fail — they pin behaviour the risk-officer confirmed already
exists, exactly the same "verify, don't assume absence" posture the
GMV4-tailor-001 precedent required. Tests 1, 2, 4, 5 reproduce the gap and
are expected to fail today.
"""
from __future__ import annotations

import ast
import inspect
import time
import uuid
from pathlib import Path
from typing import Any

from app.repositories.story import StoryRepository

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_API_ROOT = Path(__file__).resolve().parents[1]  # apps/api
_APP_DIR = _API_ROOT / "app"
_SCRIPTS_DIR = _API_ROOT / "scripts"
_OWN_MODULE = _APP_DIR / "services" / "story_dedup_migration.py"


def _story(title: str, situation: str, task: str, action: str, result: str, **extra):
    payload = {
        "title": title,
        "situation": situation,
        "task": task,
        "action": action,
        "result": result,
    }
    payload.update(extra)
    return payload


#: The EXACT paraphrase pair story_paraphrase.py's own docstring (lines
#: 120-136) cites as clearing BULK_MIGRATION_THRESHOLDS (title Jaccard
#: 0.667 >= 0.60) while sitting BELOW CREATE_TIME_THRESHOLDS (0.70) — so
#: both rows are guaranteed to exist as two separate StoryEntry rows before
#: the bulk migration runs, and are guaranteed to qualify for it. Same pair
#: test_we_story_dedup_relevance.py::TestBulkDedupMigration already uses.
def _seed_anz_pair(repo: StoryRepository, user_id: str) -> tuple[dict, dict]:
    older = repo.create(
        user_id,
        _story(
            "ANZ Cloud-Native Core Banking transformation",
            "Legacy core banking needed modernisation.",
            "Modernise the platform onto cloud-native .NET/Azure services.",
            "Led a 5+ cross-functional squad (up to 40 people) migrating core banking.",
            "30% faster delivery, 15% infra cost cut, 95-100% compliance.",
            tags=["banking"],
        ),
    )
    # Small gap so createdAt ordering (which drives which row survives) is
    # deterministic regardless of the DB timestamp column's resolution.
    time.sleep(0.05)
    newer = repo.create(
        user_id,
        _story(
            "ANZ Cloud-Native Core Banking Modernisation",
            "The legacy core banking stack blocked modernisation.",
            "Modernise onto cloud-native .NET and Azure services.",
            "Directed a cross-functional squad of up to 40 people through the migration.",
            "Delivery sped up ~30%, infra cost fell ~15%, compliance reached 95-100%.",
            tags=["azure"],
        ),
    )
    assert older["id"] != newer["id"], (
        "sanity check: create-time dedup must NOT already merge this pair "
        "(it sits below CREATE_TIME_THRESHOLDS by design) — if it did, the "
        "test below has nothing left to exercise"
    )
    return older, newer


def _second_user(client) -> tuple[str, dict[str, str]]:
    """Register a SECOND user on the same client; return (user_id, headers)."""
    creds = {
        "email": f"story-dedup-other-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup3rSecret",
    }
    assert client.post("/auth/register", json=creds).status_code == 201
    token = client.post("/auth/login", json=creds).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["id"], headers


# ---------------------------------------------------------------------------
# 1) Zero production call sites — the core gap
# ---------------------------------------------------------------------------


def _iter_python_files(*dirs: Path):
    for d in dirs:
        if d.exists():
            for f in d.rglob("*.py"):
                if "__pycache__" not in f.parts:
                    yield f


def _calls_merge_duplicate_stories(py_file: Path) -> bool:
    """True only if ``py_file`` contains a genuine AST ``Call`` node invoking
    something named ``merge_duplicate_stories`` — a bare ``import`` (or a
    docstring mention, which isn't even parsed as code) can NEVER satisfy
    this, only an actual invocation."""
    try:
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None
            )
            if name == "merge_duplicate_stories":
                return True
    return False


class TestProductionInvocationPath:
    def test_merge_duplicate_stories_has_a_production_invocation_path(self):
        """merge_duplicate_stories must be reachable from a genuine
        production entrypoint (an admin route, a maintenance script, or a
        scheduled job) — not merely defined and cross-referenced in
        docstrings. Scans every ``.py`` file under ``app/`` and ``scripts/``
        (excluding the function's own defining module) for an actual AST
        Call node naming it.
        """
        candidates = [
            f for f in _iter_python_files(_APP_DIR, _SCRIPTS_DIR)
            if f.resolve() != _OWN_MODULE.resolve()
        ]
        call_sites = [f for f in candidates if _calls_merge_duplicate_stories(f)]
        assert call_sites, (
            "merge_duplicate_stories() has ZERO production call sites under "
            f"{_APP_DIR} or {_SCRIPTS_DIR}: no router, admin action, "
            "maintenance script, or scheduled job invokes it (only its own "
            "docstring usage example and one cross-reference from "
            "story_paraphrase.py's docstring exist) — the retroactive "
            "bulk paraphrase de-dup has therefore NEVER run against live "
            "data (GMV4-story-002)"
        )


# ---------------------------------------------------------------------------
# 2) Dry-run mode — proposed merges + scores, ZERO writes
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_emits_proposed_merges_without_writing(self, monkeypatch):
        """The risk-officer requires a dry-run mode that returns every
        proposed merge pair with its similarity score and performs ZERO
        writes, before this sweep is ever pointed at live data. Today's
        signature is ``merge_duplicate_stories(user_id: str)`` — no
        ``dry_run`` parameter exists at all.
        """
        from app.services import story_dedup_migration as mod

        sig = inspect.signature(mod.merge_duplicate_stories)
        assert "dry_run" in sig.parameters, (
            "merge_duplicate_stories(user_id) has no 'dry_run' parameter "
            f"(found only {list(sig.parameters)!r}) — there is no way to "
            "preview proposed merges without writing to the DB, which the "
            "risk-officer requires before this sweep ever touches live "
            "story data"
        )

        # If/when dry_run exists, it must also touch nothing. Spy on every
        # SQL statement the routine issues via a fake connection/cursor so a
        # real write is unmistakable.
        calls: dict[str, Any] = {"executed_sql": [], "commits": 0}

        class _FakeCursor:
            def execute(self, sql, params=None):
                calls["executed_sql"].append(sql)

            def fetchall(self):
                return []

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _FakeConn:
            def cursor(self):
                return _FakeCursor()

            def commit(self):
                calls["commits"] += 1

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(mod, "ensure_story_dedup_column", lambda: None)
        monkeypatch.setattr(mod, "get_connection", lambda: _FakeConn())
        monkeypatch.setattr(
            mod.StoryRepository,
            "list_by_user",
            lambda self, user_id: [
                {
                    "id": "story-old",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "title": "JIRA Analytics Dashboard for Sprint Velocity & Retrospective Insights",
                    "situation": "S", "task": "T",
                    "action": "Built a dashboard for sprint velocity tracking and retros.",
                    "result": "Improved delivery efficiency by 20% and clarity by 15%.",
                    "metrics": {}, "tags": ["jira"],
                },
                {
                    "id": "story-new",
                    "createdAt": "2026-02-01T00:00:00Z",
                    "title": "JIRA Analytics Dashboard for Agile Team Insights",
                    "situation": "S2", "task": "T2",
                    "action": "Built a dashboard giving agile teams sprint velocity visibility.",
                    "result": "Improved delivery efficiency by 20% and clarity by 15%.",
                    "metrics": {}, "tags": ["agile"],
                },
            ],
        )

        result = mod.merge_duplicate_stories(user_id="user-1", dry_run=True)

        assert not calls["executed_sql"], (
            f"dry_run=True must issue ZERO SQL statements, got "
            f"{calls['executed_sql']!r}"
        )
        assert calls["commits"] == 0, "dry_run=True must never commit"
        assert any(k in result for k in ("proposed", "proposed_merges")), (
            f"dry-run result must list proposed merge pairs with a score, "
            f"got keys {sorted(result)!r}"
        )


# ---------------------------------------------------------------------------
# 3) MERGE shape — oldest survives, tags/metrics unioned.
#    NOT expected to fail: the risk-officer confirmed this is already
#    correctly implemented; pinned here as a regression guard for whatever
#    fix wires this up to a real entrypoint.
# ---------------------------------------------------------------------------


class TestMergeShape:
    def test_merge_preserves_oldest_row_and_unions_tags(self, test_user_id):
        repo = StoryRepository()
        older, newer = _seed_anz_pair(repo, test_user_id)

        from app.services.story_dedup_migration import merge_duplicate_stories

        result = merge_duplicate_stories(user_id=test_user_id)
        assert result.get("merged", 0) >= 1, f"expected the seeded pair to merge, got {result!r}"

        remaining = repo.list_by_user(test_user_id)
        assert len(remaining) == 1, f"expected exactly 1 row after merge, got {len(remaining)}"
        survivor = remaining[0]
        assert survivor["id"] == older["id"], (
            "the OLDEST row's id must survive the merge (a stable id for "
            f"anything already referencing it) — expected {older['id']!r}, "
            f"got {survivor['id']!r}"
        )
        assert set(survivor["tags"]) >= {"banking", "azure"}, (
            f"tags must be UNIONED across the merge, got {survivor['tags']!r}"
        )


# ---------------------------------------------------------------------------
# 4) Hard safety guard — merge must NEVER physically delete a story row.
# ---------------------------------------------------------------------------


class TestNeverDeletes:
    def test_merge_never_deletes_a_story_row(self, test_user_id):
        """Story content is user-authored, unrecoverable career history — a
        false merge that also hard-deletes the loser's row destroys data
        with no way back. Proven against a REAL merge (not by reading
        source): the losing row's id must still resolve to a row after the
        sweep runs.
        """
        repo = StoryRepository()
        older, newer = _seed_anz_pair(repo, test_user_id)

        from app.services.story_dedup_migration import merge_duplicate_stories

        result = merge_duplicate_stories(user_id=test_user_id)
        assert result.get("merged", 0) >= 1, f"expected the seeded pair to merge, got {result!r}"

        still_present = repo.get_by_id(newer["id"], test_user_id)
        assert still_present is not None, (
            f"story row {newer['id']!r} (the merge LOSER) was PHYSICALLY "
            "DELETED by merge_duplicate_stories (see 'DELETE FROM "
            '"StoryEntry"' + "' in story_dedup_migration.py) — this is "
            "exactly the unrecoverable-data risk the risk-officer flagged; "
            "a merge must archive/soft-delete the loser, never hard-DELETE it"
        )


# ---------------------------------------------------------------------------
# 5) Before/after counts (§8.1(a)) — proof the sweep actually ran.
# ---------------------------------------------------------------------------


class TestBeforeAfterCounts:
    def test_merge_reports_before_and_after_counts(self, test_user_id):
        repo = StoryRepository()
        older, newer = _seed_anz_pair(repo, test_user_id)
        before_actual = len(repo.list_by_user(test_user_id))
        assert before_actual == 2

        from app.services.story_dedup_migration import merge_duplicate_stories

        result = merge_duplicate_stories(user_id=test_user_id)

        for key in ("before_count", "after_count"):
            assert key in result, (
                f"merge_duplicate_stories() result is missing {key!r} — "
                "§8.1(a) demands before/after row counts as proof-of-run, "
                f"not just a bare merged count; got keys {sorted(result)!r}"
            )
        assert result["before_count"] == before_actual, (
            f"before_count must equal the real pre-merge row count "
            f"({before_actual}), got {result.get('before_count')!r}"
        )
        assert result["after_count"] == before_actual - result["merged"], (
            "after_count must equal before_count minus merged "
            f"({before_actual} - {result['merged']}), got "
            f"{result.get('after_count')!r}"
        )


# ---------------------------------------------------------------------------
# 6) Per-user scoping — NOT expected to fail: already correctly scoped by
#    construction (list_by_user(user_id) only ever reads one user's rows).
#    Pinned here as an explicit regression guard, since the fix that wires
#    this up must not accidentally widen the query.
# ---------------------------------------------------------------------------


class TestScoping:
    def test_merge_is_scoped_to_a_single_user_or_workspace(self, client, test_user_id):
        repo = StoryRepository()
        mine = repo.create(
            test_user_id,
            _story(
                "ANZ Cloud-Native Core Banking transformation",
                "Legacy core banking needed modernisation.",
                "Modernise the platform onto cloud-native .NET/Azure services.",
                "Led a 5+ cross-functional squad (up to 40 people) migrating core banking.",
                "30% faster delivery, 15% infra cost cut, 95-100% compliance.",
                tags=["banking"],
            ),
        )

        other_id, _other_headers = _second_user(client)
        theirs = repo.create(
            other_id,
            _story(
                "ANZ Cloud-Native Core Banking Modernisation",
                "The legacy core banking stack blocked modernisation.",
                "Modernise onto cloud-native .NET and Azure services.",
                "Directed a cross-functional squad of up to 40 people through the migration.",
                "Delivery sped up ~30%, infra cost fell ~15%, compliance reached 95-100%.",
                tags=["azure"],
            ),
        )

        from app.services.story_dedup_migration import merge_duplicate_stories

        result = merge_duplicate_stories(user_id=test_user_id)
        assert result.get("merged", 0) == 0, (
            f"user {test_user_id!r} has only ONE story of their own — "
            f"nothing to merge against within their own bank, got "
            f"{result!r}; a merged count >= 1 here means the migration "
            "crossed into another user's rows"
        )

        mine_after = repo.get_by_id(mine["id"], test_user_id)
        theirs_after = repo.get_by_id(theirs["id"], other_id)
        assert mine_after is not None, "the running user's own story must be untouched"
        assert theirs_after is not None, (
            "the OTHER user's story must be completely untouched by a merge "
            "run scoped to a different user"
        )
        assert theirs_after["title"] == theirs["title"], (
            "the other user's story content must not have been rewritten "
            "by a merge run it was never part of"
        )
