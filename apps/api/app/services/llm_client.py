"""Record-replay LLM client for the Python API (P2-S05, hardened post-review).

Modes (``AETHER_LLM_MODE`` env var):
- ``replay`` (default): read a canned response from the fixture directory —
  no network I/O. This is what CI/tests use.
- ``record``: call the live endpoint and persist the response as a fixture.
- ``live``: call the live endpoint (OpenRouter-compatible) directly.
- ``auto``: try the live endpoint first (recording the fixture on success);
  on ANY live failure (404 stale model id, 429 rate limit, 5xx, network),
  retry once with the fallback model, then fall back to the recorded fixture
  if one exists, otherwise raise :class:`LLMUnavailableError` (mapped to
  HTTP 503 by the routers — never an unhandled 500).

Fixtures live under ``AETHER_LLM_FIXTURE_DIR`` (defaults to
``apps/api/tests/fixtures/llm``) as ``<prompt_name>/<key>.json`` with shape
``{"content": "..."}``. ``key`` defaults to ``default``.

Model ids are configured via ``AETHER_MODEL_<TIER>`` env vars because
OpenRouter free-tier model ids are volatile (see ADR D-0014).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

#: Last-resort model retried once when the primary model 404s / 429s (D-0014).
FALLBACK_MODEL = "openai/gpt-oss-20b:free"


class LLMFixtureMissingError(RuntimeError):
    """Raised in replay mode when no fixture exists for a prompt."""


class LLMUnavailableError(RuntimeError):
    """Raised when the live LLM backend failed AND no fixture fallback exists.

    Routers convert this into a clean HTTP 503 ("LLM backend unavailable").
    """


def get_mode() -> str:
    return os.environ.get("AETHER_LLM_MODE", "replay").strip().lower()


def get_fixture_dir() -> Path:
    override = os.environ.get("AETHER_LLM_FIXTURE_DIR")
    return Path(override) if override else _DEFAULT_FIXTURE_DIR


def get_model(tier: str = "REASONING") -> str:
    """Resolve the model id for a tier (REASONING/FAST/STRUCTURED/LIGHT)."""
    return os.environ.get(f"AETHER_MODEL_{tier.upper()}", FALLBACK_MODEL)


class LLMClient:
    """Minimal chat-completion client with record/replay/auto support."""

    def __init__(self, mode: str | None = None, fixture_dir: Path | None = None) -> None:
        self.mode = mode or get_mode()
        self.fixture_dir = fixture_dir or get_fixture_dir()

    def complete(
        self,
        prompt_name: str,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        fixture_key: str = "default",
    ) -> str:
        """Return the assistant's text for a system+user prompt pair."""
        if self.mode == "replay":
            return self._replay(prompt_name, fixture_key)
        if self.mode == "auto":
            return self._auto(
                prompt_name, system, user,
                model=model, temperature=temperature, fixture_key=fixture_key,
            )
        # live / record modes: propagate live errors unchanged (developer modes).
        content = self._call_live(system, user, model=model, temperature=temperature)
        if self.mode == "record":
            self._record(prompt_name, fixture_key, content)
        return content

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        """Like :meth:`complete` but parses the response as JSON."""
        raw = self.complete(prompt_name, system, user, **kwargs)
        # Tolerate markdown fences around JSON payloads.
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        return json.loads(text)

    # ------------------------------------------------------------------
    def _auto(
        self,
        prompt_name: str,
        system: str,
        user: str,
        *,
        model: str | None,
        temperature: float,
        fixture_key: str,
    ) -> str:
        """Live-first with model fallback, then fixture fallback (D-0014)."""
        primary = model or get_model("REASONING")
        for attempt_model in self._model_chain(primary):
            try:
                content = self._call_live(
                    system, user, model=attempt_model, temperature=temperature
                )
            except Exception as exc:  # 404/429/5xx/network/parse — try next
                logger.warning(
                    "LLM live call failed (model=%s, prompt=%s): %s",
                    attempt_model, prompt_name, exc,
                )
                continue
            # Record only if missing so curated replay fixtures are
            # never clobbered by variable live output.
            if not self._fixture_path(prompt_name, fixture_key).is_file():
                self._record(prompt_name, fixture_key, content)
            return content
        # All live attempts failed — fall back to the recorded fixture.
        try:
            content = self._replay(prompt_name, fixture_key)
        except LLMFixtureMissingError as exc:
            raise LLMUnavailableError(
                "LLM backend unavailable: live call failed for "
                f"'{prompt_name}' and no recorded fixture exists"
            ) from exc
        logger.warning(
            "LLM auto mode: served fixture fallback for prompt '%s'", prompt_name
        )
        return content

    @staticmethod
    def _model_chain(primary: str) -> list[str]:
        """Primary model, then one retry with the fallback model."""
        return [primary] if primary == FALLBACK_MODEL else [primary, FALLBACK_MODEL]

    def _fixture_path(self, prompt_name: str, key: str) -> Path:
        return self.fixture_dir / prompt_name / f"{key}.json"

    def _replay(self, prompt_name: str, key: str) -> str:
        path = self._fixture_path(prompt_name, key)
        if not path.is_file():
            raise LLMFixtureMissingError(
                f"LLM replay fixture missing: {path}. Run in record mode first."
            )
        return json.loads(path.read_text())["content"]

    def _record(self, prompt_name: str, key: str, content: str) -> None:
        path = self._fixture_path(prompt_name, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"content": content}, indent=2))

    def _call_live(
        self, system: str, user: str, *, model: str | None, temperature: float
    ) -> str:
        import urllib.request

        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ABACUS_API_KEY")
        base_url = os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        if not api_key:
            raise RuntimeError("No LLM API key configured for live mode")
        payload = json.dumps(
            {
                "model": model or get_model("REASONING"),
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
        if "error" in body:
            raise RuntimeError(f"LLM provider error: {body['error']}")
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned empty content")
        return content
