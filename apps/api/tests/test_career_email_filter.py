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


def test_hides_github_pr_even_when_subject_says_interview_ingest():
    """Live leak: notifications@github.com for aether-job-career-agent PRs
    matched bare job/career/interview tokens and sat above recruiter mail."""
    verdict = _v(
        subject="[Victordtesla24/aether-job-career-agent] fix: career-only "
        "Email Center with persisted AI drafts and interview ingest (PR #16)",
        sender="cursor[bot]",
        sender_email="notifications@github.com",
        body="You can view, comment on, or merge this pull request.",
    )
    assert verdict.keep is False
    assert verdict.is_interview_invite is False


def test_hides_consumer_promo_with_no_job_signal():
    verdict = _v(
        subject="Hi Vikram, tell us about your electric vehicle and get $5!",
        sender="Team WeMoney",
        sender_email="hello@e.wemoney.com.au",
        body="Complete our survey about your car.",
    )
    assert verdict.keep is False


def test_hides_vcat_even_when_body_says_application():
    """Court 'application' must not outrank the personal-institution signal."""
    verdict = _v(
        subject="Hearing reminder for 25/32 Queens Road",
        sender="Residential Tenancies",
        sender_email="renting@courts.vic.gov.au",
        body="Your application for a residential tenancies hearing is listed.",
    )
    assert verdict.keep is False
    assert verdict.category == "personal"


def test_hides_seek_customer_solutions_without_job_alert():
    verdict = _v(
        subject="RE: Integration request - SEEK",
        sender="Customer Solutions Team",
        sender_email="customersolutions@seek.com.au",
        body="Thanks for your integration request.",
    )
    assert verdict.keep is False


def test_keeps_daily_rate_recruiter_thread():
    verdict = _v(
        subject="Re: Scrum Master Opportunity (Daily Rate)",
        sender="Vic",
        sender_email="recruiter@talent.example.com",
        body="This daily rate contract starts next month.",
    )
    assert verdict.keep is True


def test_auto_draft_skips_calendar_notification_and_github():
    from app.services.career_email_filter import should_auto_draft_reply

    invite = _v(
        subject="Interview: Adan & Vikram (Project Manager @ Next Business Energy)",
        sender="John Black",
        sender_email="john.black@robertwalters.com.au",
        body="John Black has invited you to an interview.",
        has_calendar_invite=True,
    )
    assert should_auto_draft_reply(
        invite,
        sender="John Black",
        sender_email="john.black@robertwalters.com.au",
    )

    calendar = _v(
        subject="Notification: Phone Interview: Vikram & Adan @ Fri Aug 7",
        sender="Google Calendar",
        sender_email="calendar-notification@google.com",
        body="Interview with Adan",
        has_calendar_invite=True,
    )
    assert calendar.keep is True
    assert should_auto_draft_reply(
        calendar,
        sender="Google Calendar",
        sender_email="calendar-notification@google.com",
    ) is False


def test_career_gmail_query_omits_bare_application_and_opportunity():
    from app.services.career_email_filter import CAREER_GMAIL_QUERY

    q = CAREER_GMAIL_QUERY.lower()
    assert "opportunity" not in q
    assert " or application " not in f" {q} "
    assert "job application" in q
    assert "interview" in q
