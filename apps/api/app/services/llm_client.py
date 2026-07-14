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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

#: Last-resort model retried once when the primary model 404s / 429s (D-0014).
FALLBACK_MODEL = "openai/gpt-oss-20b:free"


def get_fallback_model() -> str:
    """Fallback model id, overridable so non-OpenRouter providers can set one."""
    return os.environ.get("AETHER_MODEL_FALLBACK", FALLBACK_MODEL)


def _extra_headers() -> dict[str, str]:
    """Provider-specific extra HTTP headers from ``AETHER_LLM_EXTRA_HEADERS``.

    Some OpenAI-compatible endpoints require additional headers on every
    request — e.g. Anthropic's compat endpoint needs
    ``anthropic-version: 2023-06-01`` and (for OAuth tokens)
    ``anthropic-beta: oauth-2025-04-20``. Set the env var to a JSON object,
    e.g.::

        AETHER_LLM_EXTRA_HEADERS={"anthropic-version": "2023-06-01"}

    Malformed or non-object JSON is ignored (returns ``{}``) so a bad env
    value can never take the LLM layer down; values are coerced to str.
    """
    raw = os.environ.get("AETHER_LLM_EXTRA_HEADERS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


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


#: Env vars ``_call_live`` checks for a usable API key, in the exact
#: precedence it applies. Exposed as data (not just inline in ``_call_live``)
#: so callers — notably the Agents providers panel (GAP-P4-055) — can report
#: which credential path is *actually* serving live runs instead of guessing.
_LIVE_API_KEY_ENV_VARS = ("AETHER_LLM_API_KEY", "OPENROUTER_API_KEY", "ABACUS_API_KEY")


def get_active_credential_env_var() -> str | None:
    """The env var ``_call_live`` will use as the API key right now, or ``None``.

    Mirrors ``_call_live``'s own precedence exactly (single source of truth)
    so the providers panel never has to fake or guess which credential path
    — including the ``ABACUS_API_KEY`` fallback — is actually serving runs.
    """
    for name in _LIVE_API_KEY_ENV_VARS:
        if os.environ.get(name):
            return name
    return None


# ---------------------------------------------------------------------------
# Provider-aware routing + native Anthropic transport (PROVIDER-CONFIG-RUN).
#
# A model id resolves to EXACTLY one provider and one credential source. There
# is NO cross-provider fallback: a ``claude-*`` model only ever hits
# api.anthropic.com with the Anthropic credential (native Messages API), and
# every other model only ever hits OpenRouter with the OpenRouter credential.
# A missing credential is an honest, provider-named error — never a silent
# reroute (ADR-PC-2 — the billing separation this feature exists to guarantee).
# ---------------------------------------------------------------------------

#: Native Anthropic Messages API (NOT OpenAI-compatible).
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_OAUTH_BETA = "oauth-2025-04-20"


def get_anthropic_max_tokens() -> int:
    """Required ``max_tokens`` for the Anthropic Messages API (env-overridable)."""
    try:
        return int(os.environ.get("AETHER_ANTHROPIC_MAX_TOKENS", "4096"))
    except ValueError:
        return 4096


def resolve_provider(model: str) -> str:
    """Map a model id to its billing provider: ``'anthropic'`` or ``'openrouter'``.

    ``claude-*`` and ``anthropic/*`` are Anthropic-native; everything else is
    served through OpenRouter. Pure function so the router, the verify endpoint
    and the transport all agree on one resolution.
    """
    m = (model or "").strip().lower()
    if m.startswith("claude-") or m.startswith("anthropic/"):
        return "anthropic"
    return "openrouter"


def _infer_anthropic_auth_mode(secret: str) -> str:
    """Anthropic authMode from the key prefix (``sk-ant-oat…`` = subscription)."""
    return "subscription_oauth" if secret.startswith("sk-ant-oat") else "api_key"


@dataclass(frozen=True)
class ProviderCredentialResolution:
    """A resolved provider credential and where it came from."""

    provider: str
    auth_mode: str          # 'api_key' | 'subscription_oauth'
    secret: str
    base_url: str | None
    source: str             # 'database' | 'environment'


def resolve_credential(provider: str) -> "ProviderCredentialResolution | None":
    """Resolve ``provider``'s credential: DB row FIRST, then legacy env fallback.

    Returns ``None`` when neither exists — the caller must then raise an honest,
    provider-named error and must NOT reroute to the other provider.
    """
    # 1. Encrypted DB credential (the in-UI configured path) wins.
    try:
        from app.repositories.provider_credential import ProviderCredentialRepository

        row = ProviderCredentialRepository().get_secret(provider)
    except Exception as exc:  # DB down / table missing / key rotated -> degrade
        logger.warning(
            "provider-credential DB lookup for '%s' failed; falling back to env: %s",
            provider, exc,
        )
        row = None
    if row and row.get("secret"):
        return ProviderCredentialResolution(
            provider=provider,
            auth_mode=row.get("authMode") or "api_key",
            secret=row["secret"],
            base_url=row.get("baseUrl"),
            source="database",
        )
    # 2. Legacy env fallback — strictly provider-scoped, never cross-provider.
    if provider == "anthropic":
        base = os.environ.get("AETHER_LLM_BASE_URL", "")
        direct = os.environ.get("AETHER_LLM_API_KEY")
        if direct and "anthropic.com" in base:
            return ProviderCredentialResolution(
                "anthropic", _infer_anthropic_auth_mode(direct), direct, base, "environment"
            )
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return ProviderCredentialResolution(
                "anthropic", _infer_anthropic_auth_mode(key), key, None, "environment"
            )
        return None
    # openrouter (and every non-anthropic model, which is served via OpenRouter).
    active = get_active_credential_env_var()
    if active:
        base = (
            os.environ.get("AETHER_LLM_BASE_URL")
            or os.environ.get("OPENROUTER_BASE_URL")
        )
        return ProviderCredentialResolution(
            "openrouter", "api_key", os.environ.get(active), base, "environment"
        )
    return None


def anthropic_auth_headers(auth_mode: str, secret: str) -> dict[str, str]:
    """Auth/version headers for the native Anthropic Messages API.

    - ``'subscription_oauth'`` (Claude Max/Pro token, ``sk-ant-oat…``):
      ``Authorization: Bearer <token>`` + ``anthropic-beta: oauth-2025-04-20``.
    - ``'api_key'`` (``sk-ant-api…``): ``x-api-key: <key>`` (no Bearer).
    """
    headers = {
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    if auth_mode == "subscription_oauth":
        headers["Authorization"] = f"Bearer {secret}"
        headers["anthropic-beta"] = ANTHROPIC_OAUTH_BETA
    elif auth_mode == "api_key":
        headers["x-api-key"] = secret
    else:
        raise RuntimeError(f"Unsupported Anthropic authMode '{auth_mode}'")
    return headers


def build_anthropic_request(
    model: str,
    system: str | None,
    user: str,
    *,
    auth_mode: str,
    secret: str,
    base_url: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Prepare a native Anthropic Messages request (``{url, json, headers}``).

    Exposed so tests and the verify endpoint can inspect the prepared request
    without a live call. ``temperature``/``top_p`` are deliberately omitted —
    current Anthropic models 400 on them.
    """
    base = (base_url or ANTHROPIC_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_tokens or get_anthropic_max_tokens()),
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    return {
        "url": f"{base}/v1/messages",
        "json": body,
        "headers": anthropic_auth_headers(auth_mode, secret),
    }


def parse_anthropic_response(body: dict[str, Any]) -> str:
    """Extract assistant text from a Messages API response, honestly.

    Concatenates ``content`` blocks where ``type == 'text'``. A ``refusal`` stop
    reason is surfaced as an error; a ``max_tokens`` truncation with no text is
    an error, and with partial text is logged (the JSON caller's parser catches
    a truncated object and degrades to a fixture).
    """
    stop = body.get("stop_reason")
    if stop == "refusal":
        raise RuntimeError("Anthropic declined to answer (stop_reason=refusal)")
    blocks = body.get("content") or []
    text = "".join(
        b.get("text", "")
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "text"
    )
    if not text.strip():
        if stop == "max_tokens":
            raise RuntimeError(
                "Anthropic response truncated at max_tokens before any text; "
                "raise AETHER_ANTHROPIC_MAX_TOKENS"
            )
        raise RuntimeError("Anthropic returned empty content")
    if stop == "max_tokens":
        logger.warning("Anthropic response truncated at max_tokens (partial content)")
    return text


def _build_openrouter_request(
    model: str,
    system: str,
    user: str,
    temperature: float,
    cred: "ProviderCredentialResolution",
) -> dict[str, Any]:
    """Prepare the existing OpenAI-compatible OpenRouter chat request."""
    base = (cred.base_url or "https://openrouter.ai/api/v1").rstrip("/")
    return {
        "url": f"{base}/chat/completions",
        "json": {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        "headers": {
            "Authorization": f"Bearer {cred.secret}",
            "Content-Type": "application/json",
            **_extra_headers(),
        },
    }


def verify_provider_credential(
    provider: str, *, timeout: float = 15.0
) -> tuple[bool, str, str]:
    """Perform a REAL minimal round-trip against ``provider``'s stored credential.

    Returns ``(ok, status, detail)``. ``ok`` is only True on a genuine 2xx —
    never fabricated. Anthropic sends a 1-token Messages ping; OpenRouter lists
    models. Providers with no native transport report an honest ``'unsupported'``.
    """
    import httpx

    cred = resolve_credential(provider)
    if cred is None:
        return (False, "no_credential", f"No credential configured for '{provider}'.")
    try:
        if provider == "anthropic":
            req = build_anthropic_request(
                "claude-haiku-4-5", None, "ping",
                auth_mode=cred.auth_mode, secret=cred.secret,
                base_url=cred.base_url, max_tokens=1,
            )
            resp = httpx.post(
                req["url"], json=req["json"], headers=req["headers"], timeout=timeout
            )
        elif provider == "openrouter":
            base = (cred.base_url or "https://openrouter.ai/api/v1").rstrip("/")
            resp = httpx.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {cred.secret}"},
                timeout=timeout,
            )
        else:
            return (
                False,
                "unsupported",
                f"Live verification is not available for provider '{provider}' "
                "(its models are served through OpenRouter).",
            )
    except Exception as exc:  # network/DNS/timeout — honest failure, never faked
        return (False, "error", f"Verification request failed: {exc}")
    if 200 <= resp.status_code < 300:
        return (True, "ok", f"{provider} responded HTTP {resp.status_code}.")
    return (
        False,
        "failed",
        f"{provider} returned HTTP {resp.status_code}: {resp.text[:150]}",
    )


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
        """Single live call with a HARD wall-clock cap, routed by provider.

        The model id resolves to EXACTLY one provider + credential source
        (:func:`resolve_provider` / :func:`resolve_credential`). Anthropic models
        use the native Messages API; everything else uses the OpenAI-compatible
        OpenRouter path. A missing credential raises an honest, provider-named
        error — the request is NEVER rerouted to the other provider (ADR-PC-2).

        httpx read timeouts are *per-chunk*: a provider that trickles bytes can
        keep a "30 s read timeout" call alive for minutes (observed 133–157 s
        coverLetter runs → edge 524s, defect D1). The request is therefore
        executed in a worker thread and abandoned outright once ``max_seconds``
        elapses, so the caller can move on to the fallback model / fixture while
        still inside the budget.
        """
        import httpx

        model_id = model or get_model("REASONING")
        provider = resolve_provider(model_id)
        cred = resolve_credential(provider)
        if cred is None:
            raise RuntimeError(
                f"No credential configured for provider '{provider}' "
                f"(model '{model_id}'). Add a {provider} credential in the Agents "
                "panel or its server env key. The request will NOT be rerouted to "
                "another provider — billing separation is enforced."
            )
        if provider == "anthropic":
            req = build_anthropic_request(
                model_id, system, user,
                auth_mode=cred.auth_mode, secret=cred.secret, base_url=cred.base_url,
            )
        else:
            req = _build_openrouter_request(model_id, system, user, temperature, cred)

        connect = CONNECT_TIMEOUT
        read = READ_TIMEOUT
        if max_seconds is not None:
            connect = max(1.0, min(connect, max_seconds))
            read = max(1.0, min(read, max_seconds))
        timeout = httpx.Timeout(connect=connect, read=read, write=10.0, pool=10.0)

        def _do_request() -> httpx.Response:
            return httpx.post(
                req["url"], json=req["json"], headers=req["headers"], timeout=timeout
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
        if provider == "anthropic":
            return parse_anthropic_response(body)
        if "error" in body:
            raise RuntimeError(f"LLM provider error: {body['error']}")
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned empty content")
        return content
