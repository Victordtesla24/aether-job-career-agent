"""GOLD-MASTER-V2 §7.2/§7.3 — Story Bank paraphrase dedup + relevance scoring.

FAILING tests written BEFORE any fix, per GM2-STORY-001/GM2-STORY-002
(``uat/reports/evidence/gold-master-v2/screens/stories-screen-test.md``):
34 of the owner's 36 real production stories are paraphrase re-tellings of
only 8 distinct achievements. Root cause verified live: ``StoryRepository
.create`` (apps/api/app/repositories/story.py:34-83) dedups ONLY on an EXACT
sha256 of the five STAR fields (``compute_story_content_hash``,
apps/api/app/services/dedup.py) — any reworded duplicate is silently
inserted as a brand-new row.

Also covers §7.3.3/§7.3.4 relevance scoring — confirmed entirely absent
(``grep -rn "relevance_score|relevanceScore" apps/api apps/web/src`` returns
zero hits outside the evidence report and this file) — and §7.3.2's bulk
de-dup migration, which does not exist anywhere in the repo either
(``find apps/api -iname "*dedup*migrat*"`` returns nothing).

This file NEVER implements the fix (test-author brief §0.4). Two tests
(item 4 and item 5 below) target a plausible module location for
not-yet-written code — that location is an ASSUMPTION, clearly flagged
inline, not a requirement on whoever implements the fix; the BEHAVIORAL
contract is what must hold, not the exact import path. One test (item 3,
"false-positive guard") is a forward-looking non-regression guard the brief
explicitly asked for and is EXPECTED to already pass against current code —
it is NOT a defect reproduction and is called out as such below and in the
evidence report, not silently left in a suite that claims "everything here
fails".

Run under the shared test-DB lock::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_we_story_dedup_relevance.py -v
"""
from __future__ import annotations

from app.repositories.job import JobRepository
from app.repositories.story import StoryRepository


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


def _seed_job(user_id: str, suffix: str, **overrides) -> str:
    payload = {
        "title": "Senior Python Data Engineer",
        "company": "Acme Robotics",
        "location": "Remote",
        "remote": True,
        "description": "We need strong Python, PostgreSQL and ETL pipeline skills.",
        "requirements": [],
        "source": "test",
        "sourceUrl": f"https://example.test/we-story-relevance/{suffix}",
        "postedAt": None,
    }
    payload.update(overrides)
    created = JobRepository().create(user_id, payload)
    return created["id"]


# ---------------------------------------------------------------------------
# 1) Content fingerprint (§7.3.1) — a paraphrase must MERGE, not insert
# ---------------------------------------------------------------------------


class TestParaphraseFingerprintDedup:
    def test_paraphrase_of_existing_achievement_merges_not_inserts(self, test_user_id):
        """A story whose (userId, normalized_title, achievement fingerprint)
        matches an existing one must UPDATE the existing row, not insert a
        second one.

        Reproduces GM2-STORY-002: today's dedup is an EXACT sha256 of the
        five STAR fields, so a reworded duplicate is a fresh insert. This
        synthetic pair keeps the SAME achievement (a Next.js/Supabase
        sprint-velocity dashboard, 20%/15% metrics) but rewords every
        sentence and the title — exactly the extractor-rerun pattern the
        evidence report identifies as the real production cause.
        """
        repo = StoryRepository()
        original = repo.create(
            test_user_id,
            _story(
                "JIRA Analytics Dashboard for Agile Team Insights",
                "Our agile teams lacked visibility into sprint velocity trends.",
                "Build a dashboard surfacing sprint velocity and delivery health.",
                "Built a Next.js + Supabase analytics dashboard consuming JIRA data.",
                "Delivery efficiency improvement: 20%. Operational clarity improvement: 15%.",
            ),
        )
        before = len(repo.list_by_user(test_user_id))

        paraphrased = repo.create(
            test_user_id,
            _story(
                "JIRA Analytics Dashboard for Agile Team Visibility",
                "Agile squads had no real-time insight into how sprints were trending.",
                "Stand up a dashboard giving the team visibility into velocity and health.",
                "Shipped a sprint-velocity analytics dashboard on Next.js and Supabase, "
                "pulling live JIRA data.",
                "Improved delivery efficiency by roughly 20% and operational clarity by 15%.",
            ),
        )
        after = len(repo.list_by_user(test_user_id))

        assert after == before, (
            f"paraphrase of an existing achievement inserted a NEW row "
            f"({before} -> {after} total stories); expected the fingerprint "
            f"match to merge into the existing row {original['id']!r} instead"
        )
        assert paraphrased["id"] == original["id"], (
            "paraphrase dedup must return the SAME existing row id "
            f"(got {paraphrased['id']!r} != {original['id']!r})"
        )

    def test_real_duplicate_titles_from_evidence_report_do_not_double_insert(
        self, test_user_id
    ):
        """Uses the EXACT two duplicate titles from the live production
        evidence (stories-screen-test.md §2, JIRA family): "...for Agile
        Team Insights" vs "...for Agile Team Visibility" — both real titles
        pulled from the owner's actual duplicated Story Bank rows, both
        reporting the identical metrics (20% / 15%) the report calls out.
        """
        repo = StoryRepository()
        repo.create(
            test_user_id,
            _story(
                "JIRA Analytics Dashboard for Agile Team Insights",
                "Sprint velocity was invisible to leadership.",
                "Create a live dashboard exposing sprint velocity and delivery health.",
                "Delivered a Next.js/Supabase dashboard pulling JIRA sprint data.",
                "Delivery efficiency improvement: 20%. Operational clarity improvement: 15%.",
            ),
        )
        before = len(repo.list_by_user(test_user_id))

        repo.create(
            test_user_id,
            _story(
                "JIRA Analytics Dashboard for Agile Team Visibility",
                "Leadership had no visibility into sprint velocity.",
                "Build a live dashboard for sprint velocity and delivery health visibility.",
                "Delivered a Next.js + Supabase dashboard ingesting JIRA sprint data.",
                "Delivery efficiency improvement: 20%. Operational clarity improvement: 15%.",
            ),
        )
        after = len(repo.list_by_user(test_user_id))

        assert after == before, (
            "the two real duplicate titles from the production evidence "
            f"report inserted a SECOND row ({before} -> {after}) instead of "
            "merging — this is the exact GM2-STORY-001/002 defect, reproduced "
            "with the report's own data"
        )


# ---------------------------------------------------------------------------
# 3) False-positive guard — NOT a defect reproduction, a forward guard-rail.
#    Expected to PASS today (exact-hash dedup already keeps genuinely
#    different achievements separate); flagged explicitly in the evidence
#    report as an expected pass, not an "unexpected pass"/test defect.
# ---------------------------------------------------------------------------


class TestFalsePositiveGuard:
    def test_two_genuinely_different_achievements_are_both_stored(self, test_user_id):
        """Two REAL, DIFFERENT achievements must both survive dedup. This is
        the guard-rail the brief calls "as important as the dedup test
        itself": it is what stops an over-aggressive fingerprint (e.g. a
        title-prefix or single-field match) from collapsing two unrelated
        stories into one. Deliberately written to share superficial
        structure (similar opening clause, similar tech stack vocabulary)
        while describing two INCOMPATIBLE achievements, so a naive fix
        cannot pass this by accident.

        EXPECTED RESULT: PASS today. Today's exact-hash dedup only merges
        byte-identical content, so two different stories already survive as
        two rows — this guard exists to keep passing once the fingerprint
        fix (item 1/2 above) ships, not to catch a current bug.
        """
        repo = StoryRepository()
        repo.create(
            test_user_id,
            _story(
                "Led the ANZ Cloud-Native Core Banking Migration",
                "Legacy core banking blocked modernisation.",
                "Migrate core banking onto cloud-native .NET/Azure services.",
                "Directed a 5+ squad (up to 40 people) through the platform migration.",
                "30% faster delivery, 15% infra cost cut, 95-100% compliance.",
            ),
        )
        before = len(repo.list_by_user(test_user_id))

        repo.create(
            test_user_id,
            _story(
                "Led the ATO COBOL Mainframe Test Evidence Automation",
                "Manual mainframe test evidence collection took days per cycle.",
                "Automate COBOL/mainframe test evidence generation for audits.",
                "Directed a small automation squad building the evidence pipeline.",
                "92% effort reduction in evidence collection per audit cycle.",
            ),
        )
        after = len(repo.list_by_user(test_user_id))

        assert after == before + 1, (
            "two genuinely DIFFERENT achievements must BOTH be stored as "
            f"separate rows (before={before}, after={after}) — collapsing "
            "them would be an over-aggressive fingerprint, exactly the "
            "failure mode this guard exists to catch"
        )


# ---------------------------------------------------------------------------
# 4) Bulk de-dup migration (§7.3.2) — idempotent, reports merged count
# ---------------------------------------------------------------------------


class TestBulkDedupMigration:
    def test_bulk_dedup_migration_merges_duplicates_and_is_idempotent(self, test_user_id):
        """A bulk de-dup migration must merge paraphrase duplicates already
        sitting in the DB (accumulated BEFORE any create-time fingerprint fix
        ships — e.g. the owner's real 34-of-36 duplicated rows) and be safe
        to run twice: the second run finds nothing left to merge and reports
        a merged count of 0.

        No such migration exists anywhere in the repo today
        (``find apps/api -iname "*dedup*migrat*"`` and
        ``grep -rn "merge_duplicate_stories" apps/api`` both return nothing
        outside this test). The import path below
        (``app.services.story_dedup_migration.merge_duplicate_stories``) is
        an ASSUMPTION about where the fix will live, mirroring this
        codebase's existing services-layer convention for deterministic
        dedup helpers (``app/services/dedup.py``) — NOT a requirement on the
        implementer. Update the import if the real fix lands elsewhere; the
        BEHAVIORAL contract pinned below (idempotent, reports a merged
        count) is what must hold regardless of where it lives.
        """
        repo = StoryRepository()
        repo.create(
            test_user_id,
            _story(
                "ANZ Cloud-Native Core Banking transformation",
                "Legacy core banking needed modernisation.",
                "Modernise the platform onto cloud-native .NET/Azure services.",
                "Led a 5+ cross-functional squad (up to 40 people) migrating core banking.",
                "30% faster delivery, 15% infra cost cut, 95-100% compliance.",
            ),
        )
        repo.create(
            test_user_id,
            _story(
                "ANZ Cloud-Native Core Banking Modernisation",
                "The legacy core banking stack blocked modernisation.",
                "Modernise onto cloud-native .NET and Azure services.",
                "Directed a cross-functional squad of up to 40 people through the migration.",
                "Delivery sped up ~30%, infra cost fell ~15%, compliance reached 95-100%.",
            ),
        )
        before = len(repo.list_by_user(test_user_id))
        assert before == 2, (
            "sanity check: today's exact-hash create-time dedup does NOT "
            "catch this paraphrase pair, so both rows must exist before the "
            "migration runs"
        )

        from app.services.story_dedup_migration import merge_duplicate_stories

        first_run = merge_duplicate_stories(user_id=test_user_id)
        assert first_run.get("merged", 0) >= 1, (
            f"expected the paraphrase pair seeded above to be merged by the "
            f"first migration run, got {first_run!r}"
        )
        after_first = len(repo.list_by_user(test_user_id))
        assert after_first == before - first_run["merged"], (
            f"row count after merge ({after_first}) must equal before "
            f"({before}) minus the reported merged count ({first_run['merged']})"
        )

        second_run = merge_duplicate_stories(user_id=test_user_id)
        assert second_run.get("merged", 0) == 0, (
            "re-running the migration over an already-merged set must be a "
            f"no-op, got {second_run!r}"
        )
        after_second = len(repo.list_by_user(test_user_id))
        assert after_second == after_first, "second run must not change the row count"


# ---------------------------------------------------------------------------
# 5) story_relevance_score(story, job_description) (§7.3.3)
# ---------------------------------------------------------------------------


class TestStoryRelevanceScore:
    def test_story_relevance_score_returns_bounded_plausible_score(self):
        """story_relevance_score(story, job_description) must return a 0-1
        float, and score a CLEARLY relevant story higher than a CLEARLY
        irrelevant one against the same job description.

        No such function exists anywhere in the repo today
        (``grep -rn "story_relevance_score" apps/api`` returns zero hits
        outside this test and the evidence report). Target location
        (``app.services.story_relevance.story_relevance_score``) mirrors
        this codebase's ``app/services/ats_engine.py`` convention for a
        deterministic fit scorer — an ASSUMPTION, not a requirement; see the
        migration test above for the same caveat.
        """
        from app.services.story_relevance import story_relevance_score

        job_description = (
            "We are hiring a Senior Python Data Engineer to build and operate "
            "large-scale ETL pipelines on PostgreSQL and cloud infrastructure."
        )
        relevant_story = {
            "title": "Python Data Pipeline Optimisation",
            "situation": "Nightly ETL jobs were missing SLAs.",
            "task": "Redesign the pipeline for throughput and reliability.",
            "action": (
                "Rebuilt the ETL pipeline in Python against PostgreSQL, adding "
                "incremental loads and monitoring."
            ),
            "result": "Cut pipeline runtime 60% and eliminated missed SLAs.",
            "tags": ["python", "data engineering", "postgresql", "etl"],
        }
        irrelevant_story = {
            "title": "Community Bake Sale Coordination",
            "situation": "The local school fundraiser needed an organiser.",
            "task": "Coordinate volunteers and vendors for a weekend bake sale.",
            "action": "Recruited 12 volunteers and organised the stall layout and roster.",
            "result": "Raised $2,400 for the school library, beating the prior year by 30%.",
            "tags": ["volunteering", "community"],
        }

        relevant_score = story_relevance_score(relevant_story, job_description)
        irrelevant_score = story_relevance_score(irrelevant_story, job_description)

        assert 0.0 <= relevant_score <= 1.0
        assert 0.0 <= irrelevant_score <= 1.0
        assert relevant_score > irrelevant_score, (
            f"a Python/ETL/PostgreSQL story must score higher against a "
            f"Python Data Engineer JD than a bake-sale story "
            f"(relevant={relevant_score!r}, irrelevant={irrelevant_score!r})"
        )


# ---------------------------------------------------------------------------
# 6) GET /stories?job_id=... exposes relevance_score (§7.3.4)
# ---------------------------------------------------------------------------


class TestRelevanceExposedOnList:
    def test_get_stories_with_job_id_exposes_relevance_score(
        self, client, auth_headers, test_user_id
    ):
        """Verified live (screen-tester + adversarial evidence): ``job_id``
        is silently ignored today (``stories.py:137-140``'s ``list_stories``
        takes no query params at all) and no ``relevance_score``-shaped field
        exists anywhere in ``_enrich()``. Reproduced here at the router/HTTP
        layer directly.
        """
        created = client.post(
            "/stories",
            json={
                "title": "Python Data Pipeline Optimisation",
                "situation": "S.",
                "task": "T.",
                "action": "A.",
                "result": "R.",
                "tags": ["python", "data engineering"],
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text

        job_id = _seed_job(test_user_id, "relevance-exposed")

        resp = client.get(f"/stories?job_id={job_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert rows, "expected at least the seeded story back"
        for row in rows:
            assert "relevance_score" in row, (
                "GET /stories?job_id=... must expose relevance_score per row "
                f"(§7.3.4) — row keys were {sorted(row)}"
            )
            assert 0.0 <= row["relevance_score"] <= 1.0


# ---------------------------------------------------------------------------
# 7) Selection threshold: generation must filter by relevance, not dump
#    every story indiscriminately into the evidence corpus.
# ---------------------------------------------------------------------------


class TestSelectionThreshold:
    def test_build_story_evidence_supports_relevance_filtering_for_generation(self):
        """Cover-letter/application generation must select only stories with
        relevance >= a configurable threshold (default 0.4, per the brief),
        not every story the user owns.

        ``build_story_evidence`` (apps/api/app/agents/tailor_agent.py:120,
        reused verbatim by both the tailoring agent AND
        ``cover_letters.py``'s ``/refine`` path) currently takes ONLY
        ``user_id`` — every story is flattened into the evidence corpus
        unconditionally, with no job/JD parameter and therefore no relevance
        filtering of any kind. This pins the required CONTRACT (a
        job_description parameter capable of driving relevance filtering)
        rather than a specific internal implementation.
        """
        import inspect

        from app.agents.tailor_agent import build_story_evidence

        sig = inspect.signature(build_story_evidence)
        assert "job_description" in sig.parameters, (
            "build_story_evidence(user_id, ...) has no job_description "
            f"parameter (found only {list(sig.parameters)}) — it cannot "
            "filter stories by relevance to the job being applied for, so "
            "every story the user owns is included indiscriminately in "
            "every cover-letter / tailoring generation run"
        )
