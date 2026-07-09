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

import concurrent.futures
import contextvars
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

#: Last-resort model retried once when the primary model 404s / 429s (D-0014).
FALLBACK_MODEL = "openai/gpt-oss-20b:free"


def get_fallback_model() -> str:
    """Fallback model id, overridable so non-OpenRouter providers can set one."""
    return os.environ.get("AETHER_MODEL_FALLBACK", FALLBACK_MODEL)


#: Shared wall-clock deadline (monotonic) for multi-agent orchestrations.
#: When set (via :func:`shared_budget`), every LLMClient in the current
#: context honours ONE deadline instead of arming its own — this is what
#: keeps the pipeline (tailor + coverLetter) inside a single budget so the
#: HTTP edge (~100 s) never returns a 524 (defect D1, audit 2026-07-09).
_shared_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "aether_llm_shared_deadline", default=None
)


@contextmanager
def shared_budget(seconds: float | None = None) -> Iterator[None]:
    """Bound ALL live LLM calls made inside the block by one wall-clock budget."""
    deadline = time.monotonic() + (seconds if seconds is not None else get_budget_seconds())
    token = _shared_deadline.set(deadline)
    try:
        yield
    finally:
        _shared_deadline.reset(token)

#: Per-call HTTP timeouts (seconds). OpenRouter free tier can stall for
#: minutes; a single call must never hold a request hostage.
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0

#: Minimum useful remaining budget — below this we skip live attempts and go
#: straight to fixture replay / typed error instead of firing a doomed call.
_MIN_ATTEMPT_SECONDS = 5.0


def get_budget_seconds() -> float:
    """Overall wall-clock budget for ALL live LLM calls in one client's life.

    One :class:`LLMClient` instance is created per agent run, so this bounds
    the whole fallback chain (primary + fallback model x corrective retries).
    """
    try:
        return float(os.environ.get("AETHER_LLM_BUDGET_SECONDS", "60"))
    except ValueError:
        return 60.0


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
        #: Wall-clock deadline for live calls; armed on the first live attempt
        #: so the whole fallback chain shares one budget (see get_budget_seconds).
        self._deadline: float | None = None

    def _remaining_budget(self) -> float:
        """Seconds left in the live-call budget (arms the deadline lazily).

        A context-level shared deadline (see :func:`shared_budget`) takes
        precedence so multi-agent orchestrations share ONE budget.
        """
        shared = _shared_deadline.get()
        if shared is not None:
            return shared - time.monotonic()
        if self._deadline is None:
            self._deadline = time.monotonic() + get_budget_seconds()
        return self._deadline - time.monotonic()

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
        """Like :meth:`complete` but parses the response as JSON.

        In ``auto`` mode a malformed/truncated live response (e.g. the model
        hit its token limit mid-object) falls back to the recorded fixture
        instead of surfacing an unhandled ``JSONDecodeError`` as a 500.
        """
        raw = self.complete(prompt_name, system, user, **kwargs)
        try:
            return json.loads(self._strip_fences(raw))
        except json.JSONDecodeError:
            if self.mode != "auto":
                raise
        fixture_key = str(kwargs.get("fixture_key", "default"))
        logger.warning(
            "LLM returned malformed JSON for prompt '%s'; falling back to fixture",
            prompt_name,
        )
        try:
            fixture_raw = self._replay_with_default(prompt_name, fixture_key)
            return json.loads(self._strip_fences(fixture_raw))
        except (LLMFixtureMissingError, json.JSONDecodeError) as exc:
            raise LLMUnavailableError(
                f"LLM backend unavailable: live call for '{prompt_name}' returned "
                "malformed JSON and no valid fixture exists"
            ) from exc

    @staticmethod
    def _strip_fences(raw: str) -> str:
        """Tolerate markdown fences around JSON payloads."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        return text

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
        """Live-first with model fallback, then fixture fallback (D-0014).

        Every live attempt is bounded by per-call HTTP timeouts AND the
        client-wide wall-clock budget; once the budget is exhausted we stop
        making live calls and fall straight to fixture replay / typed error
        instead of hanging the request.
        """
        primary = model or get_model("REASONING")
        for attempt_model in self._model_chain(primary):
            remaining = self._remaining_budget()
            if remaining < _MIN_ATTEMPT_SECONDS:
                logger.warning(
                    "LLM budget exhausted before model %s (prompt=%s); "
                    "falling back to fixture",
                    attempt_model, prompt_name,
                )
                break
            try:
                content = self._call_live(
                    system, user, model=attempt_model, temperature=temperature,
                    max_seconds=remaining,
                )
            except Exception as exc:  # 404/429/5xx/network/timeout/parse — try next
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
            content = self._replay_with_default(prompt_name, fixture_key)
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
        fallback = get_fallback_model()
        return [primary] if primary == fallback else [primary, fallback]

    def _fixture_path(self, prompt_name: str, key: str) -> Path:
        return self.fixture_dir / prompt_name / f"{key}.json"

    def _replay_with_default(self, prompt_name: str, key: str) -> str:
        """Replay ``key``; if missing, degrade to the ``default`` fixture.

        Corrective-retry prompts use per-attempt fixture keys (``retry``,
        ``retry2``) that may never have been recorded — the default fixture is
        still a valid, guard-checked response for the prompt, so serving it is
        strictly better than a 503.
        """
        try:
            return self._replay(prompt_name, key)
        except LLMFixtureMissingError:
            if key == "default":
                raise
            logger.warning(
                "LLM fixture '%s/%s' missing; degrading to default fixture",
                prompt_name, key,
            )
            return self._replay(prompt_name, "default")

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
        self,
        system: str,
        user: str,
        *,
        model: str | None,
        temperature: float,
        max_seconds: float | None = None,
    ) -> str:
        """Single live chat-completion call with a HARD wall-clock cap.

        httpx read timeouts are *per-chunk*: a provider that trickles bytes
        can keep a "30 s read timeout" call alive for minutes (observed
        133–157 s coverLetter runs → edge 524s, defect D1). The request is
        therefore executed in a worker thread and abandoned outright once
        ``max_seconds`` elapses, so the caller can move on to the fallback
        model / fixture while still inside the budget.

        Provider selection (OpenAI-compatible chat completions):
        - ``AETHER_LLM_BASE_URL`` / ``AETHER_LLM_API_KEY`` take precedence,
          allowing e.g. Anthropic's OpenAI-compat endpoint
          (``https://api.anthropic.com/v1``) with a Claude model id.
        - Otherwise ``OPENROUTER_BASE_URL`` / ``OPENROUTER_API_KEY`` (default).
        """
        import httpx

        api_key = (
            os.environ.get("AETHER_LLM_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ABACUS_API_KEY")
        )
        base_url = (
            os.environ.get("AETHER_LLM_BASE_URL")
            or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        ).rstrip("/")
        if not api_key:
            raise RuntimeError("No LLM API key configured for live mode")
        connect = CONNECT_TIMEOUT
        read = READ_TIMEOUT
        if max_seconds is not None:
            connect = max(1.0, min(connect, max_seconds))
            read = max(1.0, min(read, max_seconds))
        timeout = httpx.Timeout(connect=connect, read=read, write=10.0, pool=10.0)

        def _do_request() -> httpx.Response:
            return httpx.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model or get_model("REASONING"),
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )

        if max_seconds is None:
            resp = _do_request()
        else:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(_do_request)
                try:
                    resp = future.result(timeout=max_seconds)
                except concurrent.futures.TimeoutError as exc:
                    future.cancel()
                    raise RuntimeError(
                        f"LLM call exceeded hard budget of {max_seconds:.1f}s"
                    ) from exc
            finally:
                # Don't block on a straggling request thread; let it finish
                # in the background and be reaped when the response arrives.
                executor.shutdown(wait=False)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM provider HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"LLM provider error: {body['error']}")
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned empty content")
        return content
