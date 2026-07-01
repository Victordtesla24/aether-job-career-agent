"""Tests for the resume parser (P1-S04).

These assert against the *real* content of the read-only asset
`assets/resume/Vik_Resume_Final.pdf`. No content is fabricated: every expected
value below is extracted directly from the PDF. The format hash is the SHA-256
of the raw PDF bytes and must never change.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.services.resume_parser import compute_format_hash, parse_resume_pdf
from app.services.resume_tailor import tailor_bullets

REPO_ROOT = Path(__file__).resolve().parents[3]
RESUME_PATH = REPO_ROOT / "assets" / "resume" / "Vik_Resume_Final.pdf"

# SHA-256 of the raw PDF bytes — the format-preserving hash. Immutable.
EXPECTED_FORMAT_HASH = (
    "0700d1aa1a48de5dc9ca308968ff5a6049b2b0ea38adac5550353279b0768a25"
)


def test_resume_asset_exists() -> None:
    assert RESUME_PATH.is_file(), f"missing read-only asset: {RESUME_PATH}"


def test_compute_format_hash_matches_raw_sha256() -> None:
    expected = hashlib.sha256(RESUME_PATH.read_bytes()).hexdigest()
    assert compute_format_hash(RESUME_PATH) == expected
    assert compute_format_hash(RESUME_PATH) == EXPECTED_FORMAT_HASH


def test_format_hash_is_stable_across_calls() -> None:
    first = compute_format_hash(RESUME_PATH)
    second = compute_format_hash(RESUME_PATH)
    assert first == second


def test_compute_format_hash_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        compute_format_hash(REPO_ROOT / "assets" / "resume" / "does_not_exist.pdf")


def test_parse_resume_returns_expected_shape() -> None:
    result = parse_resume_pdf(RESUME_PATH)
    assert result["page_count"] == 3
    assert result["char_count"] > 0
    assert isinstance(result["raw_text"], str)
    assert result["format_hash"] == EXPECTED_FORMAT_HASH


def test_parse_resume_extracts_contact_info() -> None:
    contact = parse_resume_pdf(RESUME_PATH)["contact"]
    assert contact["email"] == "sarkar.vikram@gmail.com"
    assert contact["github"] == "github.com/Victordtesla24"
    assert contact["linkedin"] == "linkedin.com/in/vikramd-profile"
    assert contact["phone"] is not None
    assert "61" in contact["phone"]


def test_parse_resume_detects_known_sections() -> None:
    sections = parse_resume_pdf(RESUME_PATH)["sections"]
    for heading in (
        "CAREER OBJECTIVE",
        "WORK EXPERIENCE",
        "EDUCATION",
        "SKILLS",
        "CERTIFICATIONS",
    ):
        assert heading in sections


def test_parse_resume_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        parse_resume_pdf(REPO_ROOT / "assets" / "resume" / "nope.pdf")


def test_tailor_bullets_is_lossless_passthrough_stub() -> None:
    bullets = [
        "Led end-to-end delivery for the Agile Kookaburras squad.",
        "Reduced P95 latency to under 200 ms for 10k+ device concurrency.",
    ]
    out = tailor_bullets(bullets, job_description="Senior Delivery Manager")
    # The stub must not fabricate or drop content.
    assert out == bullets


def test_tailor_bullets_handles_empty_input() -> None:
    assert tailor_bullets([], job_description="anything") == []
