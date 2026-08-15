"""LinkedIn "Download your data" export FILE UPLOAD ingestion (B7).

Compliant, upload-based — never scrapes linkedin.com. LinkedIn's official
export is a zip of CSVs (``Profile.csv``, ``Positions.csv``, ``Education.csv``,
``Skills.csv``). This is a second *input* path alongside the existing
candidate-paste path (``app.services.career_data.ingest_linkedin``); it
normalizes the CSVs into the same paste-equivalent text and feeds it to the
SAME downstream ingest function — there is no second ingestion pipeline.

Covers (per ticket B7):
  1. a fixture zip with all 4 CSVs ingests, and positions/education/skills
     land in the summary exactly like an equivalent paste would.
  2. an 11MB upload is rejected (413/422), never persisted.
  3. a zip with only Positions.csv ingests partially and reports honestly
     what was (and wasn't) found.
  4. a renamed-to-.exe upload is rejected 422.
  5. the LinkedIn ingestion path makes no network/HTTP-client call of any
     kind — the compliance line (ADR D-0031) — verified by source inspection.
"""
from __future__ import annotations

import csv
import inspect
import io
import re
import zipfile

import pytest

from app.repositories.career_profile import CareerProfileRepository
from app.services import career_data
from app.services.career_data import (
    ingest_linkedin,
    ingest_linkedin_export,
    normalize_linkedin_export,
    parse_linkedin_export_zip,
)

# ---------------------------------------------------------------------------
# Fixture data — deliberately small, deterministic, and shared across cases.
# ---------------------------------------------------------------------------

_PROFILE_ROWS = [
    {
        "First Name": "Vikram",
        "Last Name": "Deshpande",
        "Headline": "Senior Technical Program Manager",
        "Summary": "Delivery lead across banking and government platforms.",
    }
]
_POSITIONS_ROWS = [
    {
        "Company Name": "Acme Bank",
        "Title": "Senior Program Manager",
        "Description": "Led a portfolio of compliance-critical delivery programs.",
        "Location": "Melbourne, VIC",
        "Started On": "Jan 2020",
        "Finished On": "Present",
    },
    {
        "Company Name": "Globex Corp",
        "Title": "Delivery Manager",
        "Description": "Migrated a COBOL mainframe estate to cloud.",
        "Location": "Sydney, NSW",
        "Started On": "Mar 2016",
        "Finished On": "Dec 2019",
    },
]
_EDUCATION_ROWS = [
    {
        "School Name": "University of Melbourne",
        "Degree Name": "Master of Engineering",
        "Field Of Study": "Systems Engineering",
        "Start Date": "2011",
        "End Date": "2013",
    }
]
_SKILLS_ROWS = [{"Name": "Program Management"}, {"Name": "Cloud Migration"}, {"Name": "COBOL"}]


def _csv_text(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _full_export_csv_texts() -> dict[str, str]:
    return {
        "Profile.csv": _csv_text(
            ["First Name", "Last Name", "Headline", "Summary"], _PROFILE_ROWS
        ),
        "Positions.csv": _csv_text(
            ["Company Name", "Title", "Description", "Location", "Started On", "Finished On"],
            _POSITIONS_ROWS,
        ),
        "Education.csv": _csv_text(
            ["School Name", "Degree Name", "Field Of Study", "Start Date", "End Date"],
            _EDUCATION_ROWS,
        ),
        "Skills.csv": _csv_text(["Name"], _SKILLS_ROWS),
    }


def _zip_bytes(csv_texts: dict[str, str], *, folder: str = "") -> bytes:
    """Build a zip archive from ``{filename: csv text}``, LinkedIn-export
    style (real exports nest everything under a dated folder)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in csv_texts.items():
            path = f"{folder}/{name}" if folder else name
            archive.writestr(path, text)
        # A file the ingestion must ignore, unread — real exports ship dozens.
        archive.writestr(f"{folder}/Messages.csv" if folder else "Messages.csv", "irrelevant")
    return buf.getvalue()


def _upload(client, auth_headers, filename: str, data: bytes, mime: str = "application/zip"):
    return client.post(
        "/workspaces/career-data/linkedin-upload",
        files={"file": (filename, data, mime)},
        headers=auth_headers,
    )


# ---------------------------------------------------------------------------
# (1) Full export ingests; positions/education/skills land exactly like an
#     equivalent paste-path ingest would.
# ---------------------------------------------------------------------------


def test_full_export_zip_matches_equivalent_paste_ingest(client, test_user_id):
    csv_texts = _full_export_csv_texts()

    # The SAME text the upload path derives, fed through the SAME paste-path
    # function directly — proves ingest_linkedin_export reuses ingest_linkedin
    # rather than running a second ingestion pipeline.
    paste_text, counts = normalize_linkedin_export(csv_texts)
    paste_equivalent = ingest_linkedin(paste_text)

    from_export = ingest_linkedin_export(csv_texts)

    assert from_export["status"] == "ok" == paste_equivalent["status"]
    assert from_export["content"] == paste_equivalent["content"]
    assert from_export["summary"] == paste_equivalent["summary"]
    assert from_export["error"] is None

    # Positions/education/skills genuinely landed in the paste-shaped summary
    # (the same field the candidate-paste path populates), not some separate
    # upload-only structure.
    summary = from_export["summary"]
    assert "Senior Program Manager at Acme Bank" in summary
    assert "Delivery Manager at Globex Corp" in summary
    assert "Master of Engineering, Systems Engineering" in summary
    assert "University of Melbourne" in summary
    assert "Program Management" in summary and "Cloud Migration" in summary
    assert counts == {"profile": 1, "positions": 2, "education": 1, "skills": 3}
    assert from_export["ingestedCounts"] == counts


def test_full_export_zip_upload_endpoint_persists_like_paste(client, auth_headers, test_user_id):
    zipped = _zip_bytes(_full_export_csv_texts(), folder="Complete_LinkedInDataExport_08-14-2026")
    resp = _upload(client, auth_headers, "Complete_LinkedInDataExport.zip", zipped)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["status"] == "ok"
    assert body["ingestedCounts"] == {"profile": 1, "positions": 2, "education": 1, "skills": 3}

    stored = CareerProfileRepository().get(test_user_id, "linkedin")
    assert stored["status"] == "ok"
    assert "Acme Bank" in stored["summary"]
    assert stored["content"]["source"] == "workspace-paste"  # inherited, not duplicated

    # It also feeds the same corpus the paste path feeds.
    corpus = career_data.build_career_corpus(test_user_id)
    assert "Acme Bank" in corpus


# ---------------------------------------------------------------------------
# (2) Oversized upload rejected, never persisted.
# ---------------------------------------------------------------------------


def test_upload_rejects_file_over_10mb(client, auth_headers, test_user_id):
    eleven_mb = 11 * 1024 * 1024
    oversized = b"a" * eleven_mb
    assert len(oversized) > 10 * 1024 * 1024

    resp = _upload(client, auth_headers, "huge_export.zip", oversized)
    assert resp.status_code in (413, 422), f"status={resp.status_code} body[:300]={resp.text[:300]!r}"
    assert CareerProfileRepository().get(test_user_id, "linkedin") is None


# ---------------------------------------------------------------------------
# (3) Partial export (only Positions.csv) ingests what it has, honestly.
# ---------------------------------------------------------------------------


def test_partial_export_only_positions_ingests_honestly(client, auth_headers, test_user_id):
    csv_texts = {
        "Positions.csv": _csv_text(
            ["Company Name", "Title", "Description", "Location", "Started On", "Finished On"],
            _POSITIONS_ROWS,
        )
    }
    zipped = _zip_bytes(csv_texts)
    resp = _upload(client, auth_headers, "partial_export.zip", zipped)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["status"] == "ok"
    assert "Acme Bank" in body["source"]["summary"]
    # Honest per-section reporting: positions present, everything else zero.
    assert body["ingestedCounts"] == {"profile": 0, "positions": 2, "education": 0, "skills": 0}


def test_zip_with_no_known_csvs_is_reported_empty_not_fabricated(client, auth_headers, test_user_id):
    zipped = _zip_bytes({})  # only the ignored Messages.csv ends up in the zip
    resp = _upload(client, auth_headers, "no_known_files.zip", zipped)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# (4) A disguised executable is rejected 422, never parsed.
# ---------------------------------------------------------------------------


def test_exe_rename_rejected_422(client, auth_headers, test_user_id):
    fake_exe = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64  # PE header magic
    resp = _upload(client, auth_headers, "totally_a_resume.exe", fake_exe, mime="application/octet-stream")
    assert resp.status_code == 422, resp.text
    assert CareerProfileRepository().get(test_user_id, "linkedin") is None


def test_unrecognized_csv_name_rejected_422(client, auth_headers, test_user_id):
    resp = _upload(
        client,
        auth_headers,
        "Connections.csv",
        _csv_text(["First Name", "Last Name"], [{"First Name": "A", "Last Name": "B"}]),
        mime="text/csv",
    )
    assert resp.status_code == 422, resp.text


def test_single_known_csv_upload_ingests(client, auth_headers, test_user_id):
    resp = _upload(
        client,
        auth_headers,
        "Skills.csv",
        _csv_text(["Name"], _SKILLS_ROWS),
        mime="text/csv",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ingestedCounts"]["skills"] == 3
    assert "Program Management" in body["source"]["summary"]


# ---------------------------------------------------------------------------
# (6) A zip whose declared/compressed size is small but whose contents
#     DECOMPRESS to something huge (a "zip bomb") is rejected 422, never
#     fully materialized in memory. DEFLATE lets a small compressed payload
#     named Profile.csv explode to gigabytes on read — a memory-exhaustion
#     DoS an authenticated user could trigger through this exact endpoint.
# ---------------------------------------------------------------------------


def _zip_bomb_bytes() -> bytes:
    """A LinkedIn-shaped zip whose Profile.csv decompresses to >10MB while
    the archive itself stays far under the 10MB raw-upload cap — the same
    kind of payload a hostile "export" could smuggle past that gate to
    exhaust server memory on decompression."""
    huge_payload = b"A" * (12 * 1024 * 1024)  # 12MB of highly-compressible data
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Profile.csv", huge_payload)
    return buf.getvalue()


def test_zip_bomb_profile_csv_rejected_422_not_persisted(client, auth_headers, test_user_id):
    bomb = _zip_bomb_bytes()
    # The whole point of a zip bomb: tiny on the wire, huge decompressed.
    # Confirm this precondition so the test actually exercises the
    # decompressed-size guard, not the pre-existing raw-upload-size gate
    # (which requires the COMPRESSED bytes to exceed 10MB).
    assert len(bomb) < 1 * 1024 * 1024, f"bomb compressed size unexpectedly large: {len(bomb)}"

    resp = _upload(client, auth_headers, "Complete_LinkedInDataExport.zip", bomb)
    assert resp.status_code == 422, f"status={resp.status_code} body[:300]={resp.text[:300]!r}"
    assert CareerProfileRepository().get(test_user_id, "linkedin") is None


def test_parse_linkedin_export_zip_raises_on_decompression_bomb():
    bomb = _zip_bomb_bytes()
    with pytest.raises(zipfile.BadZipFile):
        parse_linkedin_export_zip(bomb)


# ---------------------------------------------------------------------------
# (5) No network/HTTP-client usage anywhere in the LinkedIn ingestion path —
#     the compliance line (ADR D-0031): upload-only, never scraped.
# ---------------------------------------------------------------------------


def test_linkedin_ingestion_path_has_no_network_dependency():
    module_source = inspect.getsource(career_data)
    # An IMPORT of a real HTTP client, never a substring match — the module's
    # honest GitHub-rate-limit copy legitimately contains the English word
    # "requests" ("unauthenticated requests"), which a bare substring check
    # would misfire on.
    assert not re.search(r"^\s*(import|from)\s+(requests|httpx)\b", module_source, re.MULTILINE)

    # The functions actually on the LinkedIn path make no use of the module's
    # own urllib-based fetchers (those are wired to GitHub/portfolio only) —
    # by design, not by accident — and never reference the domain itself.
    # Scoped to just these functions (not the whole module, whose top-of-file
    # compliance docstring legitimately explains "nothing touches
    # linkedin.com" in prose) so this can't misfire on the documentation that
    # states the very guarantee being tested.
    for fn in (ingest_linkedin, ingest_linkedin_export, normalize_linkedin_export, parse_linkedin_export_zip):
        src = inspect.getsource(fn)
        assert "urllib" not in src
        assert "_fetch_html" not in src
        assert "requests" not in src
        assert "httpx" not in src
        assert "linkedin.com" not in src.lower()
