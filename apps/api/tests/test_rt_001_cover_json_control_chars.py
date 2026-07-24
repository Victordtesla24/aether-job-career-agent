"""RT-001 — cover-letter JSON with literal control characters must parse.

Live evidence (worker.log 2026-07-24): anthropic/claude-sonnet-5 consistently
returns cover-letter JSON whose string values contain LITERAL newlines
(unescaped control characters). Strict ``json.loads`` rejects control chars
inside strings ("Invalid control character at ..."), so every same-model
re-draft failed identically, the (correctly) substitution-free user-chosen
chain exhausted, and the run 503'd — a chronic, deterministic pipeline
failure on perfectly usable content.

Contract locked here:
- ``complete_json`` in ``auto`` mode ACCEPTS well-formed JSON whose strings
  contain raw control characters (lenient ``strict=False`` parse), returning
  the parsed object with those characters preserved;
- genuinely malformed/truncated JSON STILL raises ``LLMUnavailableError``
  (no silent acceptance of garbage, no fixture fallback).
"""
from __future__ import annotations

import pytest

from app.services.llm_client import LLMClient, LLMUnavailableError

# A realistic cover-letter payload: multi-paragraph body with LITERAL
# newline + tab control characters inside the JSON string value.
_CONTROL_CHAR_JSON = (
    '{"letter": "Dear Hiring Manager,\n\nI am excited to apply for the Senior '
    'Product Manager role.\n\tMy experience spans discovery to delivery.\n\n'
    'Kind regards,\nA. Candidate", "tone": "professional"}'
)


class TestControlCharJSONParses:
    def test_control_chars_inside_strings_parse_successfully(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live", lambda self, *a, **k: _CONTROL_CHAR_JSON
        )
        parsed = llm.complete_json("cover_letter", "s", "u")
        assert parsed["tone"] == "professional"
        # The control characters are preserved verbatim in the parsed value.
        assert "\n\n" in parsed["letter"] and "\t" in parsed["letter"]

    def test_control_chars_inside_fenced_json_parse_successfully(
        self, tmp_path, monkeypatch
    ):
        fenced = "```json\n" + _CONTROL_CHAR_JSON + "\n```"
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", lambda self, *a, **k: fenced)
        parsed = llm.complete_json("cover_letter", "s", "u")
        assert parsed["letter"].startswith("Dear Hiring Manager,")

    def test_truncated_json_with_control_chars_still_raises(
        self, tmp_path, monkeypatch
    ):
        truncated = '{"letter": "Dear Hiring Manager,\n\nI am excited to app'
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", lambda self, *a, **k: truncated)
        with pytest.raises(LLMUnavailableError):
            llm.complete_json("cover_letter", "s", "u")

    def test_non_auto_mode_also_parses_control_chars(self, tmp_path):
        """Replay mode goes through the same final parse — keep it lenient too."""
        import json as _json

        fixture = tmp_path / "cover_letter" / "default.json"
        fixture.parent.mkdir(parents=True)
        # The fixture file itself is VALID strict JSON (json.dump escapes);
        # its recorded *content* carries the literal control characters.
        fixture.write_text(_json.dumps({"content": _CONTROL_CHAR_JSON}))
        llm = LLMClient(mode="replay", fixture_dir=tmp_path)
        parsed = llm.complete_json("cover_letter", "s", "u")
        assert "Kind regards" in parsed["letter"]
