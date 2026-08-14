"""U5d-3 Pillar 1 — the Answer Bank STORE and its audit trail (RED first).

Two additive, FK-free tables created by lazy idempotent DDL (ADR-TR-1, the
``EvidenceCorpusItem``/``CareerProfile`` pattern — there is no migration
runner):

* ``AnswerBankItem`` — one row per (user, question class, scope): the canonical
  question, its semantic key, the user's OWN answer verbatim, scope,
  provenance, sensitivity class, staleness policy, timesUsed/lastUsedAt.
* ``AnswerBankUsage`` — one row per AUTO-ANSWER, carrying the three facts the
  ADR's honesty floor demands of every one: which banked item, what match
  confidence, and the question EXACTLY as the employer asked it.

Nothing here talks to an employer, a browser or a model.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture()
def repo():
    from app.repositories.answer_bank import AnswerBankRepository

    return AnswerBankRepository()


class TestSchema:
    def test_the_tables_are_created_lazily_and_idempotently(self, repo, db_session):
        """Called twice from a cold process — no error, no duplicate table."""
        repo.list_for_user("nobody")
        repo.list_for_user("nobody")
        with db_session.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = ANY(current_schemas(false))"
                " AND table_name IN ('AnswerBankItem', 'AnswerBankUsage')"
            )
            found = {row[0] for row in cur.fetchall()}
        assert found == {"AnswerBankItem", "AnswerBankUsage"}

    def test_an_empty_bank_reads_as_empty_never_as_seeded(self, repo, user_id):
        assert repo.list_for_user(user_id) == []


class TestCapture:
    def test_an_answer_is_banked_with_its_provenance_and_derived_class(
        self, repo, user_id
    ):
        item = repo.upsert(
            user_id,
            question="Are you legally authorised to work in Australia?",
            answer="Yes — Australian citizen.",
            provenance="user_answered",
            provenance_detail="app_123",
        )
        assert item["answer"] == "Yes — Australian citizen."
        assert item["provenance"] == "user_answered"
        assert item["provenanceDetail"] == "app_123"
        assert item["sensitivity"] == "factual"
        assert item["semanticKey"] == "concept:work_rights"
        assert item["timesUsed"] == 0
        assert item["lastUsedAt"] is None

    def test_the_answer_is_stored_verbatim_never_normalised(self, repo, user_id):
        raw = "  4 weeks — my last day would be Friday the 12th.  "
        item = repo.upsert(
            user_id, question="Notice period?", answer=raw, provenance="user_answered"
        )
        assert item["answer"] == raw.strip()

    def test_re_answering_the_same_question_updates_in_place(self, repo, user_id):
        first = repo.upsert(
            user_id,
            question="What is your notice period?",
            answer="4 weeks",
            provenance="onboarding",
        )
        second = repo.upsert(
            user_id,
            question="Notice period (weeks)",
            answer="2 weeks",
            provenance="user_answered",
        )
        assert second["id"] == first["id"], "same class + scope must be one row"
        assert second["answer"] == "2 weeks"
        assert second["provenance"] == "user_answered"
        assert len(repo.list_for_user(user_id)) == 1

    def test_a_company_scoped_answer_lives_beside_the_global_one(self, repo, user_id):
        repo.upsert(
            user_id,
            question="What is your notice period?",
            answer="4 weeks",
            provenance="onboarding",
        )
        repo.upsert(
            user_id,
            question="What is your notice period?",
            answer="2 weeks",
            provenance="user_answered",
            scope="company",
            scope_value="Acme Pty Ltd",
        )
        assert len(repo.list_for_user(user_id)) == 2

    def test_an_empty_answer_is_never_banked(self, repo, user_id):
        assert repo.upsert(
            user_id, question="Notice period?", answer="   ", provenance="user_answered"
        ) is None
        assert repo.list_for_user(user_id) == []

    def test_a_staling_class_gets_an_expiry_and_a_stable_one_does_not(
        self, repo, user_id
    ):
        salary = repo.upsert(
            user_id,
            question="What are your salary expectations?",
            answer="AUD 180k",
            provenance="onboarding",
        )
        rights = repo.upsert(
            user_id,
            question="Are you legally authorised to work in Australia?",
            answer="Yes",
            provenance="onboarding",
        )
        assert salary["expiresAt"] is not None
        assert salary["staleDays"] == 180
        assert rights["expiresAt"] is None
        assert rights["staleDays"] is None

    def test_one_users_bank_is_invisible_to_another(self, repo, user_id):
        repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        assert repo.list_for_user("someone-else") == []


class TestEditing:
    def test_the_user_can_edit_an_answer(self, repo, user_id):
        item = repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        updated = repo.update(user_id, item["id"], answer="6 weeks")
        assert updated is not None and updated["answer"] == "6 weeks"

    def test_the_user_can_expire_an_answer_without_deleting_its_history(
        self, repo, user_id
    ):
        item = repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        expired = repo.expire(user_id, item["id"])
        assert expired is not None
        assert expired["expiresAt"] is not None
        assert expired["expiresAt"] <= datetime.now(timezone.utc)
        assert repo.get(user_id, item["id"]) is not None

    def test_the_user_can_delete_an_answer(self, repo, user_id):
        item = repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        assert repo.delete(user_id, item["id"]) is True
        assert repo.get(user_id, item["id"]) is None

    def test_another_users_item_can_be_neither_read_edited_nor_deleted(
        self, repo, user_id
    ):
        item = repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        assert repo.get("intruder", item["id"]) is None
        assert repo.update("intruder", item["id"], answer="hacked") is None
        assert repo.delete("intruder", item["id"]) is False
        assert repo.get(user_id, item["id"])["answer"] == "4 weeks"

    def test_a_judgement_item_can_be_opted_in_and_a_sensitive_one_cannot(
        self, repo, user_id
    ):
        salary = repo.upsert(
            user_id,
            question="What are your salary expectations?",
            answer="AUD 180k",
            provenance="onboarding",
        )
        opted = repo.update(user_id, salary["id"], auto_answer_opt_in=True)
        assert opted["autoAnswerOptIn"] is True

        consent = repo.upsert(
            user_id,
            question="Do you consent to a background check?",
            answer="Yes",
            provenance="onboarding",
        )
        refused = repo.update(user_id, consent["id"], auto_answer_opt_in=True)
        assert refused["autoAnswerOptIn"] is False, (
            "a sensitive answer must never become auto-answerable"
        )


class TestUsageAudit:
    def test_an_auto_answer_records_item_confidence_and_the_question_as_seen(
        self, repo, user_id
    ):
        item = repo.upsert(
            user_id,
            question="Are you legally authorised to work in Australia?",
            answer="Yes",
            provenance="onboarding",
        )
        repo.record_usage(
            user_id,
            item["id"],
            application_id="app_1",
            job_id="job_1",
            question_as_seen="Do you have the right to work in Australia?",
            confidence=0.94,
            method="concept",
        )
        usage = repo.usage_for_items(user_id, [item["id"]])[item["id"]]
        assert len(usage) == 1
        assert usage[0]["questionAsSeen"] == "Do you have the right to work in Australia?"
        assert usage[0]["matchConfidence"] == pytest.approx(0.94)
        assert usage[0]["matchMethod"] == "concept"
        assert usage[0]["applicationId"] == "app_1"

    def test_recording_a_use_advances_times_used_and_last_used(self, repo, user_id):
        item = repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        before = datetime.now(timezone.utc) - timedelta(seconds=5)
        repo.record_usage(
            user_id,
            item["id"],
            application_id="app_1",
            job_id=None,
            question_as_seen="Notice period?",
            confidence=1.0,
            method="exact",
        )
        repo.record_usage(
            user_id,
            item["id"],
            application_id="app_2",
            job_id=None,
            question_as_seen="What notice do you have to give?",
            confidence=0.93,
            method="concept",
        )
        refreshed = repo.get(user_id, item["id"])
        assert refreshed["timesUsed"] == 2
        assert refreshed["lastUsedAt"] >= before

    def test_usage_for_an_unknown_item_is_never_invented(self, repo, user_id):
        assert repo.usage_for_items(user_id, ["nope"]) == {"nope": []}

    def test_a_use_is_never_recorded_against_another_users_item(self, repo, user_id):
        item = repo.upsert(
            user_id, question="Notice period?", answer="4 weeks", provenance="onboarding"
        )
        repo.record_usage(
            "intruder",
            item["id"],
            application_id="app_x",
            job_id=None,
            question_as_seen="Notice period?",
            confidence=1.0,
            method="exact",
        )
        assert repo.get(user_id, item["id"])["timesUsed"] == 0
        assert repo.usage_for_items(user_id, [item["id"]])[item["id"]] == []


class TestMatchableRows:
    def test_the_rows_handed_to_the_matcher_carry_everything_the_gate_reads(
        self, repo, user_id
    ):
        from app.services.answer_bank import find_match

        repo.upsert(
            user_id,
            question="Are you legally authorised to work in Australia?",
            answer="Yes — Australian citizen.",
            provenance="onboarding",
        )
        match = find_match(
            "Do you have the right to work in Australia?", repo.list_for_user(user_id)
        )
        assert match is not None
        assert match.answer == "Yes — Australian citizen."
