"""Full email-trail interview offers must be read from the conversation, not the stamp.

Live miss: John Black (Robert Walters) arranged a phone screen with Adan
Micallef at Next Business Energy, then Adan moved it to a face-to-face meeting
the next morning at 10:00. Ingest used the latest message's createdAt and
hard-coded type=video, so Interview Center showed the wrong day and the wrong
format.

The parser is deterministic (no LLM): latest message in the trail wins when
facts conflict; relative dates resolve against that message's own timestamp.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.interview_thread_parser import parse_interview_thread

_MEL = ZoneInfo("Australia/Melbourne")


def _nbe_trail() -> list[dict]:
    return [
        {
            "from": "John Black",
            "fromEmail": "john.black@robertwalters.com.au",
            "createdAt": datetime(2026, 8, 6, 14, 0, tzinfo=_MEL),
            "body": (
                "Hi Vikram,\n\n"
                "I've spoken with Adan Micallef, Group Technical Lead at "
                "Next Business Energy. He's keen to have an initial phone "
                "interview tomorrow at 10:00am. He'll call you on 0433 224 556.\n\n"
                "The role is Project Manager — Retail Systems Transformation, "
                "12-month FTC, $155k inc. super, Docklands, hybrid. Core billing "
                "platform transformation, tender of Gentrack vs Tally.\n\n"
                "When did you finish with the ATO?\n\n"
                "John Black\nConsultant, Transformation, Robert Walters\n"
                "+61 3 8628 2137"
            ),
        },
        {
            "from": "Adan Micallef",
            "fromEmail": "adan@nextbusinessenergy.com.au",
            "createdAt": datetime(2026, 8, 18, 16, 0, tzinfo=_MEL),
            "body": (
                "Hi Vikram,\n\n"
                "Confirming we will meet face to face tomorrow morning at "
                "10:00am at our Docklands office instead of a phone call.\n\n"
                "Adan Micallef\nGroup Technical Lead, Next Business Energy\n"
                "0433 401 166\nadan@nextbusinessenergy.com.au"
            ),
        },
    ]


def test_latest_message_wins_format_and_relative_date():
    offer = parse_interview_thread(
        _nbe_trail(),
        subject="Next Business Energy — Project Manager interview",
    )
    assert offer.is_interview is True
    assert offer.interview_type == "onsite"
    assert offer.scheduled_at is not None
    local = offer.scheduled_at.astimezone(_MEL)
    assert local.date().isoformat() == "2026-08-19"
    assert local.hour == 10
    assert local.minute == 0
    assert offer.location is not None
    assert "docklands" in offer.location.lower()
    assert offer.company == "Next Business Energy"
    assert offer.title is not None
    assert "project manager" in offer.title.lower()
    names = " ".join(offer.interviewer_names).lower()
    assert "adan" in names
    assert "john black" in names or "john" in names
    emails = " ".join(offer.interviewer_emails).lower()
    assert "adan@nextbusinessenergy.com.au" in emails
    unanswered = " ".join(offer.unanswered_questions).lower()
    assert "ato" in unanswered
    assert offer.contact_email == "adan@nextbusinessenergy.com.au"
    assert offer.contact_name and "adan" in offer.contact_name.lower()


def test_phone_screen_is_not_overwritten_when_trail_never_changes_format():
    offer = parse_interview_thread(
        [_nbe_trail()[0]],
        subject="Invitation: phone interview — Next Business Energy",
    )
    assert offer.is_interview is True
    assert offer.interview_type == "phone"
    local = offer.scheduled_at.astimezone(_MEL)
    assert local.date().isoformat() == "2026-08-07"
    assert local.hour == 10


def test_video_link_detected_from_meet_url():
    offer = parse_interview_thread(
        [
            {
                "from": "Jane Recruiter",
                "fromEmail": "jane@stripe.com",
                "createdAt": datetime(2026, 8, 19, 9, 0, tzinfo=_MEL),
                "body": (
                    "Please join a Google Meet interview today at 2:00pm for "
                    "Staff Engineer at Stripe: https://meet.google.com/abc-defg-hij"
                ),
            }
        ],
        subject="Interview — Staff Engineer @ Stripe",
    )
    assert offer.interview_type == "video"
    assert offer.meeting_link == "https://meet.google.com/abc-defg-hij"
    assert offer.company == "Stripe"
    local = offer.scheduled_at.astimezone(_MEL)
    assert local.hour == 14


def test_non_interview_thread_is_not_an_offer():
    offer = parse_interview_thread(
        [
            {
                "from": "GitHub",
                "fromEmail": "noreply@github.com",
                "body": "Your aether-job-career-agent workflow failed.",
            }
        ],
        subject="[CI] build failed",
    )
    assert offer.is_interview is False
    assert offer.scheduled_at is None
