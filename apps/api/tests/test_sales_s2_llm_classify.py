"""S2 — inbound classification: phrase FAST PATH + one LLM fallback.

Live defect: ``_classify_inbound`` was pure phrase matching over three hard-coded
lists, so a genuine prospect who writes in ordinary English —

    "keen to try this for my job hunt, what does it cost?"

— matched nothing, returned ``None``, and the pipeline dropped the message on
the floor with no lead, no log row and no explanation.

The contract pinned here:

* the phrase lists stay as an authoritative FAST PATH. In particular an
  inbound UNSUBSCRIBE is decided by phrases ALONE — compliance never depends
  on an LLM being reachable, and the LLM is not even consulted;
* only messages the phrases do NOT classify reach ONE structured
  ``complete_json`` call returning
  ``{"category", "confidence", "reason"}``;
* ``demo|interest|pricing|partnership`` at confidence ≥ 0.6 creates a lead;
  ``noise`` or low confidence is SKIPPED and counted (never silently dropped);
* an LLM failure degrades HONESTLY to the phrase-only verdict, counted as
  ``classifierDegraded`` — the run never crashes and never fabricates a lead;
* the automated-sender guard (CLI-001) runs BEFORE any LLM call — an automated
  sender must not even cost a token.
"""
from __future__ import annotations

import uuid

from tests._sales_fakes import RecordingLLM, WindowedGmail, agent_for, make_message
from tests.test_sales_agent import (  # type: ignore[import-untyped]
    _email,
    admin_headers,  # noqa: F401 — fixture
    repo,  # noqa: F401 — fixture
    sales_env,  # noqa: F401 — fixture
)

#: The owner's real-world example — deliberately trips NONE of the phrase lists.
PROSE = "Keen to try this for my job hunt — what does it cost?"


def _acct() -> str:
    return f"acct-s2-{uuid.uuid4().hex[:10]}"


# ------------------------------------------------------- phrase fast path
def test_unsubscribe_is_decided_by_phrases_and_never_asks_the_llm(
    repo, sales_env, monkeypatch  # noqa: F811
):
    """Compliance must never depend on an LLM being up."""
    sender = _email("unsub")
    llm = RecordingLLM({"category": "interest", "confidence": 0.99, "reason": "x"})
    fake = WindowedGmail([
        make_message(sender=sender, subject="please unsubscribe me",
                     text="Please unsubscribe me from this list.")
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

    result = agent.run(trigger="manual")

    assert result["suppressed"] == 1
    assert repo.is_suppressed(sender) is True
    assert llm.calls == [], "the LLM was consulted for an unsubscribe decision"


def test_phrase_hit_still_classifies_without_an_llm_call(
    repo, sales_env, monkeypatch  # noqa: F811
):
    sender = _email("phrase")
    llm = RecordingLLM({"category": "noise", "confidence": 0.99, "reason": "x"})
    fake = WindowedGmail([
        make_message(sender=sender, subject="Question about pricing",
                     text="I'm interested in Aether — how does the pricing work?")
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

    result = agent.run(trigger="manual")

    assert result["leadsCreated"] == 1
    assert llm.calls == [], "phrase fast path must short-circuit the LLM"


# ------------------------------------------------------------- LLM path
def test_ordinary_prose_prospect_becomes_a_lead(repo, sales_env, monkeypatch):  # noqa: F811
    """The exact live miss: plain-English interest with zero phrase hits."""
    sender = _email("prose-prospect")
    llm = RecordingLLM(
        {"category": "pricing", "confidence": 0.9,
         "reason": "asks what it costs for their job search"}
    )
    fake = WindowedGmail([
        make_message(sender=sender, subject="Hello", text=PROSE)
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

    result = agent.run(trigger="manual")

    assert len(llm.calls) == 1, "exactly one structured classification call"
    assert result["leadsCreated"] == 1
    assert result["inboundClassifiedLlm"] == 1
    lead = repo.get_lead_by_email(sender)
    assert lead is not None and lead["consentType"] == "inbound_signal"


def test_partnership_and_demo_categories_also_create_leads(
    repo, sales_env, monkeypatch  # noqa: F811
):
    for category in ("partnership", "demo", "interest"):
        sender = _email(f"cat-{category}")
        llm = RecordingLLM({"category": category, "confidence": 0.8, "reason": "r"})
        fake = WindowedGmail([
            make_message(sender=sender, subject="Hello",
                         text="Reaching out about what you have built here.")
        ])
        agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

        result = agent.run(trigger="manual")

        assert result["leadsCreated"] == 1, f"{category} produced no lead"
        assert repo.get_lead_by_email(sender) is not None


def test_noise_and_low_confidence_are_skipped_and_counted(
    repo, sales_env, monkeypatch  # noqa: F811
):
    noise_sender = _email("noise")
    unsure_sender = _email("unsure")
    llm_noise = RecordingLLM({"category": "noise", "confidence": 0.97, "reason": "newsletter"})
    fake = WindowedGmail([
        make_message(sender=noise_sender, subject="Team offsite",
                     text="Reminder about Friday's offsite.")
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm_noise)
    result = agent.run(trigger="manual")
    assert result["leadsCreated"] == 0
    assert result["inboundSkippedNoise"] == 1
    assert repo.get_lead_by_email(noise_sender) is None

    llm_unsure = RecordingLLM({"category": "interest", "confidence": 0.4, "reason": "maybe"})
    fake2 = WindowedGmail([
        make_message(sender=unsure_sender, subject="Hi", text="Saw your thing.")
    ])
    agent2 = agent_for(repo, fake2, monkeypatch, account_id=_acct(), llm=llm_unsure)
    result2 = agent2.run(trigger="manual")
    assert result2["leadsCreated"] == 0, "confidence 0.4 must not create a lead"
    assert result2["inboundSkippedNoise"] == 1
    assert repo.get_lead_by_email(unsure_sender) is None


def test_llm_failure_degrades_honestly_and_is_counted(repo, sales_env, monkeypatch):  # noqa: F811
    sender = _email("degraded")
    llm = RecordingLLM(exc=RuntimeError("provider down"))
    fake = WindowedGmail([
        make_message(sender=sender, subject="Hello", text=PROSE)
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

    result = agent.run(trigger="manual")

    assert result["ran"] is True, "an LLM failure must never crash the run"
    assert result["classifierDegraded"] == 1
    assert result["leadsCreated"] == 0, "a degraded classifier must not invent a lead"
    assert repo.get_lead_by_email(sender) is None


def test_malformed_llm_payload_is_degraded_not_trusted(repo, sales_env, monkeypatch):  # noqa: F811
    sender = _email("malformed")
    llm = RecordingLLM(["not", "an", "object"])
    fake = WindowedGmail([
        make_message(sender=sender, subject="Hello", text=PROSE)
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

    result = agent.run(trigger="manual")

    assert result["classifierDegraded"] == 1
    assert result["leadsCreated"] == 0


# ------------------------------------------------- guard ordering (CLI-001)
def test_automated_sender_guard_runs_before_any_llm_call(repo, sales_env, monkeypatch):  # noqa: F811
    """The safety guard is not merely 'also applied' — it runs FIRST, so an
    automated sender never reaches the classifier at all."""
    llm = RecordingLLM({"category": "interest", "confidence": 0.99, "reason": "x"})
    fake = WindowedGmail([
        make_message(sender="notifications@github.com", name="GitHub",
                     subject="Run failed", text=PROSE)
    ])
    agent = agent_for(repo, fake, monkeypatch, account_id=_acct(), llm=llm)

    result = agent.run(trigger="manual")

    assert result["inboundSkippedAutomated"] == 1
    assert llm.calls == [], "an automated sender reached the LLM classifier"
    assert result["leadsCreated"] == 0
    assert repo.get_lead_by_email("notifications@github.com") is None
