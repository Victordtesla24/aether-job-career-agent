"""The submission agent must read contact facts off the user's own résumé text.

Regression for the owner-reported defect: the agent asked the user for their
name / phone / email / LinkedIn even though every one of those sat in the
CONTACT block of the résumé it already held, because ``_resume_contact`` only
looked at a pre-structured ``contact`` map that is empty for every PDF/DOCX and
legacy upload. The fields must now be extracted from the résumé's raw text, and
NOTHING may be invented.
"""
from __future__ import annotations

from app.services.apply_executor import _answer_for
from app.workers.apply_sweep import _extract_contact_from_text, _resume_contact

_CONTACT_BLOCK = """VIKRAM DESHPANDE
Senior Technical Program / Delivery Manager
CONTACT INFO
sample.person@gmail.com
+61 400 000 111
Melbourne, VIC, Australia
linkedin.com/in/sample-profile
github.com/sample-handle
"""


def test_extracts_every_standard_contact_field_from_raw_text() -> None:
    got = _extract_contact_from_text(_CONTACT_BLOCK)
    assert got["email"] == "sample.person@gmail.com"
    assert got["phone"] == "+61 400 000 111"
    assert got["linkedin"] == "linkedin.com/in/sample-profile"
    assert got["github"] == "github.com/sample-handle"
    # No third-party website in this résumé → key absent, never guessed.
    assert "website" not in got


def test_invents_nothing_when_text_is_empty() -> None:
    assert _extract_contact_from_text("") == {}
    assert _extract_contact_from_text("   \n  ") == {}


def test_a_bare_year_is_not_treated_as_a_phone_number() -> None:
    got = _extract_contact_from_text("Graduated 2019\nAwarded 2021\n")
    assert "phone" not in got


def test_website_excludes_linkedin_and_github_urls() -> None:
    got = _extract_contact_from_text(
        "https://linkedin.com/in/x\nhttps://github.com/y\nhttps://myportfolio.dev\n"
    )
    assert got["website"] == "https://myportfolio.dev"


def test_resume_contact_backfills_from_raw_text_when_map_is_empty(monkeypatch) -> None:
    """The live shape: sections['contact'] == {} but raw_text carries it all."""
    import app.workers.apply_sweep as mod

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            self._row = ({"contact": {}, "raw_text": _CONTACT_BLOCK},)

        def fetchone(self):
            return self._row

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    monkeypatch.setattr(mod, "get_connection", lambda: _Conn())
    contact = _resume_contact("user-1", "resume-1")
    assert contact["email"] == "sample.person@gmail.com"
    assert contact["phone"] == "+61 400 000 111"
    assert contact["linkedin"] == "linkedin.com/in/sample-profile"
    assert contact["github"] == "github.com/sample-handle"


def test_structured_contact_map_wins_over_text(monkeypatch) -> None:
    """If the user maintained a structured value, it is authoritative."""
    import app.workers.apply_sweep as mod

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            self._row = (
                {
                    "contact": {"phone": "+61 2 0000 0000"},
                    "raw_text": _CONTACT_BLOCK,
                },
            )

        def fetchone(self):
            return self._row

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    monkeypatch.setattr(mod, "get_connection", lambda: _Conn())
    contact = _resume_contact("user-1", "resume-1")
    # explicit map value preserved; the rest backfilled from text
    assert contact["phone"] == "+61 2 0000 0000"
    assert contact["email"] == "sample.person@gmail.com"


# --- the systemic "never again" guarantee -------------------------------- #
# A form field becomes a question to the user ONLY when ``_answer_for``
# returns None (build_form_fill_plan raises ManualStepRequired on an
# unanswered REQUIRED field). So the invariant that makes the reported defect
# impossible to reintroduce is: no standard identity/contact field may resolve
# to None (or "") when the candidate's profile carries it. Any future change
# that lets one slip through fails here.
_RESUME_PROFILE = {
    "name": "Sample Person",
    "email": "sample.person@gmail.com",
    "phone": "+61 400 000 111",
    "location": "Melbourne, VIC, Australia",
    "linkedin": "linkedin.com/in/sample-profile",
    "github": "github.com/sample-handle",
}


def test_no_standard_identity_field_is_ever_asked_when_the_profile_has_it() -> None:
    # Every alias in _STANDARD_FIELDS that maps to a value the résumé supplies
    # must be answered from the profile, never handed back to the user.
    fields = [
        {"name": "name", "kind": "text", "required": True},
        {"name": "full_name", "kind": "text", "required": True},
        {"name": "email", "kind": "email", "required": True},
        {"name": "email_address", "kind": "text", "required": True},
        {"name": "phone", "kind": "tel", "required": True},
        {"name": "mobile", "kind": "text", "required": True},
        {"name": "linkedin", "kind": "url", "required": True},
        {"name": "linkedin_url", "kind": "url", "required": False},
        {"name": "first_name", "kind": "text", "required": True},
        {"name": "last_name", "kind": "text", "required": True},
    ]
    for field in fields:
        answer = _answer_for(field, _RESUME_PROFILE)
        assert answer not in (None, ""), (
            f"field {field['name']!r} was NOT answered from the profile — "
            f"it would be palmed back to the user as a manual step"
        )


def test_html_type_hints_answer_phone_and_email_even_with_odd_labels() -> None:
    # An employer that labels its phone box "contact_no" (not in the alias map)
    # is still answered because type="tel" is unambiguous in HTML itself.
    assert _answer_for({"name": "contact_no", "kind": "tel"}, _RESUME_PROFILE)
    assert _answer_for({"name": "your_email_here", "kind": "email"}, _RESUME_PROFILE)
