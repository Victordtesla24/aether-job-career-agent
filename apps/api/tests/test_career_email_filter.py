"""Career-inbox classifier — Email Center must show job/career mail only.

Live production evidence (2026-08-17, https://5cb5f0620.abacusai.cloud/dashboard/email):
the "All Recruiter" tab surfaced a Victorian Civil & Administrative Tribunal
tenancy hearing reminder (courts.vic.gov.au, score 75) above recruiter mail,
and did not show an interview meeting invite received the same afternoon from
John Black. These tests pin the deterministic filter that must hide personal
mail and keep interview/recruiter/job-search mail — without an LLM.
"""
from __future__ import annotations

from app.services.career_email_filter import classify_career_email


def _v(**kwargs):
    defaults = dict(
        subject="",
        sender="",
        sender_email="",
        body="",
        label_ids=None,
        has_calendar_invite=False,
    )
    defaults.update(kwargs)
    return classify_career_email(**defaults)


def test_hides_tenancy_hearing_from_courts():
    """The exact live junk: VCAT residential tenancies hearing reminder."""
    verdict = _v(
        subject="Hearing reminder for 25/32 Queens Road",
        sender="Residential Tenancies",
        sender_email="renting@courts.vic.gov.au",
        body="Your residential tenancies hearing is listed.",
    )
    assert verdict.keep is False
    assert verdict.category == "personal"
    assert verdict.is_interview_invite is False


def test_hides_generic_personal_contract_chatter():
    verdict = _v(
        subject="RE: Work on Wednesday 6th May 2026",
        sender="Contracts",
        sender_email="mate@gmail.com",
        body="Can you still come around on Wednesday to finish the fence?",
    )
    assert verdict.keep is False
    assert verdict.category == "personal"


def test_keeps_recruiter_outreach():
    verdict = _v(
        subject="Senior TPM role at Acme — are you open to a chat?",
        sender="Sarah Chen",
        sender_email="sarah.chen@acme.com",
        body="I lead hiring for our Platform team and would like to discuss this role.",
    )
    assert verdict.keep is True
    assert verdict.category in {"priority", "all", "followup"}
    assert verdict.category != "personal"


def test_keeps_interview_calendar_invite_from_named_recruiter():
    """John Black interview meeting invite — the live miss."""
    verdict = _v(
        subject="Invitation: Interview with John Black @ 3:00pm",
        sender="John Black",
        sender_email="john.black@talent.example.com",
        body="John Black has invited you to a Google Meet interview.",
        has_calendar_invite=True,
    )
    assert verdict.keep is True
    assert verdict.is_interview_invite is True
    assert verdict.category == "priority"


def test_keeps_google_calendar_notification_when_interview_themed():
    verdict = _v(
        subject="Accepted: Interview — Staff Engineer @ Stripe",
        sender="Google Calendar",
        sender_email="calendar-notification@google.com",
        body="Interview — Staff Engineer @ Stripe\nWhen: Monday 17 Aug 2026 3:00pm",
        has_calendar_invite=True,
    )
    assert verdict.keep is True
    assert verdict.is_interview_invite is True


def test_hides_google_calendar_invite_without_career_signal():
    """A calendar invite is not automatically a job interview (dentist, VCAT)."""
    verdict = _v(
        subject="Invitation: Hearing reminder for 25/32 Queens Road",
        sender="Google Calendar",
        sender_email="calendar-notification@google.com",
        body="Residential tenancies hearing",
        has_calendar_invite=True,
    )
    assert verdict.keep is False
    assert verdict.is_interview_invite is False


def test_keeps_application_receipt_and_job_alerts():
    receipt = _v(
        subject="Fwd: Your application was successfully submitted",
        sender="Vic",
        sender_email="me@gmail.com",
        body="Your application for Staff Engineer at Stripe was submitted.",
    )
    assert receipt.keep is True

    alert = _v(
        subject="12 new Senior TPM jobs in Melbourne",
        sender="LinkedIn Job Alerts",
        sender_email="jobalerts-noreply@linkedin.com",
        body="Staff Engineer roles matching your job search.",
    )
    assert alert.keep is True
    assert alert.category == "auto"


def test_keeps_local_drafts_even_without_career_keywords():
    """Compose-modal drafts have no Gmail id; they must never be auto-hidden."""
    verdict = _v(
        subject="Quick note",
        sender="me",
        sender_email="me@gmail.com",
        body="Draft body",
        is_local_draft=True,
    )
    assert verdict.keep is True
