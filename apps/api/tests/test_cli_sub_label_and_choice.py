"""CLI-SUB-002/003 — the two fixes that unblock real Ashby/Greenhouse fills.

Root causes (traced live on real forms this session):
- 002: forms key inputs by opaque machine names (Ashby UUIDs), so `_answer_for`
  matched nothing in `_STANDARD_FIELDS` even though the profile HELD the answer
  (LinkedIn, phone, preferred name) — inflating unknown_required_question. Fix:
  a whitelist LABEL fallback.
- 003: the radio/checkbox branch required EXACT answer==label text, so a banked
  "Yes" never landed on "Yes, I'm based in Australia" (form_fill_failed). Fix:
  option-aware matching mirroring the combobox strict-dominance rule.
"""
from __future__ import annotations

import pytest

from app.services.apply_executor import _answer_for, _match_choice_option

PROFILE = {
    "name": "Vikram Deshpande",
    "email": "vik@example.com",
    "phone": "+61 400 000 000",
    "linkedin": "https://www.linkedin.com/in/vikram",
    "location": "Melbourne, VIC",
}


# --- CLI-SUB-002: label fallback ---------------------------------------------
@pytest.mark.parametrize(
    "name,label,expected",
    [
        ("39ebb162-1514-4658-8940-c15a1a71881f", "LinkedIn", "https://www.linkedin.com/in/vikram"),
        ("uuid-x", "LinkedIn Profile URL *", "https://www.linkedin.com/in/vikram"),
        ("uuid-y", "Phone Number", "+61 400 000 000"),
        ("uuid-z", "Email Address", "vik@example.com"),
        ("uuid-p", "Preferred First Name", "Vikram"),   # preferred_name -> first
        ("uuid-l", "Last Name", "Deshpande"),
        ("uuid-c", "Current City", "Melbourne, VIC"),
    ],
)
def test_label_fallback_maps_standard_identity_fields(name, label, expected):
    assert _answer_for({"name": name, "label": label, "kind": "text"}, PROFILE) == expected


def test_label_fallback_never_answers_a_free_text_employer_question():
    # A subjective employer question must NEVER resolve via the label whitelist.
    assert _answer_for(
        {"name": "uuid-q", "label": "Why do you want to work here?", "kind": "textarea"},
        PROFILE,
    ) is None
    assert _answer_for(
        {"name": "uuid-q2", "label": "Describe a challenge you overcame", "kind": "textarea"},
        PROFILE,
    ) is None


def test_name_based_mapping_still_works():
    assert _answer_for({"name": "linkedin", "label": "irrelevant", "kind": "text"}, PROFILE) == \
        "https://www.linkedin.com/in/vikram"


# --- CLI-SUB-003: choice-widget option matching ------------------------------
@pytest.mark.parametrize(
    "answer,options,expected",
    [
        ("Yes", ["Yes, I'm based in Australia", "No"], "Yes, I'm based in Australia"),
        ("No", ["Yes, I'm based in Australia", "No"], "No"),
        ("Australian Citizen", ["I am an Australian/New Zealand Citizen", "I require sponsorship"],
         "I am an Australian/New Zealand Citizen"),
        ("Hybrid", ["Fully remote", "Hybrid (3 days in office)", "Fully in office"],
         "Hybrid (3 days in office)"),
        ("Yes", ["Yes", "No"], "Yes"),  # exact still works
    ],
)
def test_choice_matching_picks_the_right_option(answer, options, expected):
    assert _match_choice_option(answer, options) == expected


def test_choice_matching_refuses_genuine_ambiguity():
    # Two options equally overlap -> refuse rather than guess.
    assert _match_choice_option("blue green", ["blue red", "green red"]) is None
    # No overlap at all -> None.
    assert _match_choice_option("purple", ["red", "green"]) is None
    # No options -> None.
    assert _match_choice_option("Yes", []) is None
