"""Job-alert email intake — parser tests (W-ALERT).

EVERY input in this file is a REAL alert email captured from the operator's own
Gmail mailboxes on 2026-08-02 and anonymised (recipient name, addresses,
per-recipient tracking tokens and the per-user saved-search id redacted — see
``tests/data/job_alerts/``). The postings themselves are untouched: the titles,
companies, locations, posted dates and job URLs asserted below are exactly what
SEEK and Michael Page sent. Nothing here is invented.

Fail-before: ``app.services.job_alert_parser`` does not exist, so every test in
this module errors on import.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.job_alert_parser import (
    ALERT_SOURCE_BY_PLATFORM,
    detect_alert_platform,
    parse_job_alert,
)

_DATA = Path(__file__).parent / "data" / "job_alerts"

# The exact From/Subject headers of the captured messages.
SEEK_ALERT_FROM = "SEEK Job Alerts <jobmail@s.seek.com.au>"
SEEK_ALERT_SUBJECT_EA = "20 new jobs for enterprise architect in Melbourne VIC 3000"
SEEK_ALERT_SUBJECT_PM = "20 new jobs for senior project manager in Melbourne VIC 3000"
SEEK_APPLICATION_FROM = "SEEK Applications <noreply@s.seek.com.au>"
SEEK_APPLICATION_SUBJECT = (
    "Hi Alex, the Project Manager job with DXC Technology Australia & New Zealand "
    "has closed"
)
MICHAELPAGE_FROM = "Michael Page Australia <noreply@mail.michaelpage.com.au>"
MICHAELPAGE_SUBJECT = "New jobs for: Information Technology : Melbourne"


def _read(name: str) -> str:
    return (_DATA / name).read_text()


# --------------------------------------------------------------- detection
def test_detects_real_seek_job_alert_sender():
    assert detect_alert_platform(SEEK_ALERT_FROM, SEEK_ALERT_SUBJECT_EA) == "seek"


def test_does_not_treat_a_seek_application_status_email_as_a_job_alert():
    """The mailbox also holds 5 real "…has closed" SEEK Applications emails.

    They are application STATUS notices about roles that are no longer open —
    turning them into Job rows would put dead listings on the board.
    """
    assert (
        detect_alert_platform(SEEK_APPLICATION_FROM, SEEK_APPLICATION_SUBJECT) is None
    )


@pytest.mark.parametrize(
    ("from_header", "subject", "expected"),
    [
        (
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "10 new jobs for “solution architect”",
            "linkedin",
        ),
        (
            "Indeed <alert@indeed.com>",
            "new jobs for project manager in Melbourne VIC",
            "indeed",
        ),
        (
            "Workforce Australia <noreply@workforceaustralia.gov.au>",
            "New jobs matching your saved search",
            "workforceaustralia",
        ),
        (MICHAELPAGE_FROM, MICHAELPAGE_SUBJECT, "michaelpage"),
        (
            "Careers <jobalerts@some-recruiter.example>",
            "5 new jobs for you",
            "generic",
        ),
    ],
)
def test_detects_the_other_automated_alert_senders(from_header, subject, expected):
    assert detect_alert_platform(from_header, subject) == expected


@pytest.mark.parametrize(
    ("from_header", "subject"),
    [
        # Real non-alert mail sitting in the same 7-day window.
        ("Adobe <noreply@adobe.com>", "Your payment failed"),
        ("Google Payments <payments-noreply@google.com>", "Your invoice is available"),
        ("Temu <email@news.temuemail.com>", "WOW! You Got A BIG OFFER!"),
        ("Aarthi N <AarthiN@workskil.com.au>", "Workskil - Post Placement Support"),
        # An automated sender whose subject is not a job alert at all.
        ("SEEK <noreply@s.seek.com.au>", "Your SEEK profile is 60% complete"),
    ],
)
def test_ignores_non_alert_mail(from_header, subject):
    assert detect_alert_platform(from_header, subject) is None


def test_alert_sources_are_distinct_per_platform():
    """Provenance must be visible and never collide with a scraped source."""
    sources = set(ALERT_SOURCE_BY_PLATFORM.values())
    assert len(sources) == len(ALERT_SOURCE_BY_PLATFORM)
    assert ALERT_SOURCE_BY_PLATFORM["seek"] == "seek-alert"
    assert ALERT_SOURCE_BY_PLATFORM["linkedin"] == "linkedin-alert"
    assert ALERT_SOURCE_BY_PLATFORM["workforceaustralia"] == "workforceaustralia-alert"
    # 'seek' (the ToS-gated scraper source) must NOT be reused — the alert path
    # is a different, compliant channel and the active feed gates on 'seek'.
    assert "seek" not in sources


# ------------------------------------------------------- SEEK extraction
def test_parses_every_posting_out_of_the_real_seek_alert():
    parsed = parse_job_alert(
        from_header=SEEK_ALERT_FROM,
        subject=SEEK_ALERT_SUBJECT_EA,
        text=_read("seek-job-alert-enterprise-architect.txt"),
        html=None,
    )
    assert parsed.platform == "seek"
    assert parsed.source == "seek-alert"
    # 20 "new jobs" cards + 3 "Jobs you may have missed" cards = 23 real postings.
    assert len(parsed.postings) == 23
    assert parsed.skipped == 0

    first = parsed.postings[0]
    assert first.title == "Solution Architect"
    assert first.company == "Talent"
    assert first.location == "Melbourne VIC"
    # The REAL apply URL, stripped of the per-recipient alert tracking params.
    assert first.source_url == "https://au.seek.com/job/93696282"
    assert first.source == "seek-alert"

    by_url = {p.source_url: p for p in parsed.postings}
    # A card carrying a "Strong applicant" badge and a salary line.
    pra = by_url["https://au.seek.com/job/93644697"]
    assert (pra.title, pra.company, pra.location) == (
        "Senior Solutions Architect",
        "PRA",
        "Melbourne VIC",
    )
    assert pra.salary_text == "$1000p/d-$1150p/d"
    # A suburb-qualified location.
    metricon = by_url["https://au.seek.com/job/93679995"]
    assert metricon.company == "Metricon Homes"
    assert metricon.location == "Notting Hill, Melbourne VIC"
    # A "Jobs you may have missed" card carries a REAL posted date.
    monash = by_url["https://au.seek.com/job/93489108"]
    assert monash.title == "Enterprise Architect"
    assert monash.company == "Monash Health"
    assert monash.location == "Clayton, Melbourne VIC"
    assert monash.posted_at == "2026-07-22"


def test_seek_alert_never_emits_a_field_it_did_not_read():
    for name in (
        "seek-job-alert-enterprise-architect.txt",
        "seek-job-alert-senior-project-manager.txt",
    ):
        parsed = parse_job_alert(
            from_header=SEEK_ALERT_FROM,
            subject=SEEK_ALERT_SUBJECT_EA,
            text=_read(name),
            html=None,
        )
        assert parsed.postings, name
        for posting in parsed.postings:
            # Required fields are always genuinely present…
            assert posting.title.strip()
            assert posting.company.strip()
            assert posting.source_url.startswith("https://au.seek.com/job/")
            # …and nothing is ever back-filled with a placeholder.
            assert posting.title != posting.company
            assert "unknown" not in posting.title.lower()
            assert "unknown" not in posting.company.lower()
            assert posting.location is None or posting.location.strip()
            # Salary is kept VERBATIM and never parsed into numbers: the real
            # data mixes per-day, per-hour and per-annum figures.
            assert posting.salary_min is None
            assert posting.salary_max is None
            # No description exists in an alert email beyond the teaser line.
            assert "responsibilit" not in posting.description.lower()


def test_seek_footer_links_are_not_mistaken_for_postings():
    """The real footer carries au.seek.com/jobs?keywords=…, /my-activity,
    /settings/notifications/unsubscribe and help.au.seek.com links."""
    parsed = parse_job_alert(
        from_header=SEEK_ALERT_FROM,
        subject=SEEK_ALERT_SUBJECT_EA,
        text=_read("seek-job-alert-enterprise-architect.txt"),
        html=None,
    )
    for posting in parsed.postings:
        assert "keywords=" not in posting.source_url
        assert "unsubscribe" not in posting.source_url
        assert "my-activity" not in posting.source_url


def test_the_same_job_in_two_alerts_yields_one_identical_url():
    """Job 93654381 (Technology Project Manager / Talent) appears in BOTH real
    alert emails, each carrying a DIFFERENT savedSearchID + tracking token.

    If the parser kept those params the two rows would not dedup and the board
    would show the same role twice.
    """
    a = parse_job_alert(
        from_header=SEEK_ALERT_FROM,
        subject=SEEK_ALERT_SUBJECT_EA,
        text=_read("seek-job-alert-enterprise-architect.txt"),
        html=None,
    )
    b = parse_job_alert(
        from_header=SEEK_ALERT_FROM,
        subject=SEEK_ALERT_SUBJECT_PM,
        text=_read("seek-job-alert-senior-project-manager.txt"),
        html=None,
    )
    shared = {p.source_url for p in a.postings} & {p.source_url for p in b.postings}
    assert "https://au.seek.com/job/93654381" in shared


def test_second_real_seek_alert_parses_its_own_postings():
    parsed = parse_job_alert(
        from_header=SEEK_ALERT_FROM,
        subject=SEEK_ALERT_SUBJECT_PM,
        text=_read("seek-job-alert-senior-project-manager.txt"),
        html=None,
    )
    assert len(parsed.postings) == 23
    by_url = {p.source_url: p for p in parsed.postings}
    cbus = by_url["https://au.seek.com/job/93645532"]
    assert (cbus.title, cbus.company, cbus.location) == (
        "Senior Project Manager",
        "CBUS Super",
        "Melbourne VIC",
    )
    # A title that itself contains a pipe character must survive intact.
    downer = by_url["https://au.seek.com/job/93683628"]
    assert downer.title == "Senior Project Manager | TXL Power Projects"
    assert downer.company == "Downer EDI Limited"


# ------------------------------------------- Michael Page (anchor extraction)
def test_michael_page_alert_finds_real_urls_but_refuses_to_invent_a_posting():
    """The REAL Michael Page alert links every card twice: the visible anchor
    goes through a click-tracking redirector (``click.em.page.com/?qs=…``), and
    the genuine ``michaelpage.com.au/job-detail/…`` URL sits only on the Outlook
    VML button, which carries no label. The email also never names the hiring
    company for any role — only a title, a location and a rate.

    So the two real job URLs cannot be completed into a posting without
    inventing at least one NOT NULL field. The only honest outcome is to find
    them, skip them, and say why — never to back-fill "Michael Page" as the
    employer or to guess a company out of the blurb.
    """
    parsed = parse_job_alert(
        from_header=MICHAELPAGE_FROM,
        subject=MICHAELPAGE_SUBJECT,
        text=None,
        html=_read("michaelpage-job-alert.html"),
    )
    assert parsed.platform == "michaelpage"
    assert parsed.source == "michaelpage-alert"
    # Two real job-detail URLs are in the message…
    assert parsed.job_urls_found == 2
    # …and neither can be completed honestly, so neither becomes a posting.
    assert parsed.postings == []
    assert parsed.skipped == 2
    assert "fabricated" in parsed.reason.lower()
    # The sender's own brand is never promoted to an employer name.
    assert "Michael Page" not in [p.company for p in parsed.postings]


def test_click_tracker_urls_are_never_used_as_a_source_url():
    parsed = parse_job_alert(
        from_header=MICHAELPAGE_FROM,
        subject=MICHAELPAGE_SUBJECT,
        text=None,
        html=_read("michaelpage-job-alert.html"),
    )
    for posting in parsed.postings:
        assert "click.em.page.com" not in posting.source_url


# --------------------------------------------------------------- guard rails
def test_a_non_alert_message_parses_to_nothing():
    parsed = parse_job_alert(
        from_header="Adobe <noreply@adobe.com>",
        subject="Your payment failed",
        text="Your payment failed. Update your card at https://adobe.com/account",
        html=None,
    )
    assert parsed.platform is None
    assert parsed.postings == []


def test_empty_body_parses_to_nothing_without_raising():
    parsed = parse_job_alert(
        from_header=SEEK_ALERT_FROM,
        subject=SEEK_ALERT_SUBJECT_EA,
        text=None,
        html=None,
    )
    assert parsed.platform == "seek"
    assert parsed.postings == []
    assert parsed.reason
