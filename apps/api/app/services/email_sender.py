"""Outbound transactional email — minimal provider abstraction (O-4).

Aether-owned mail (password reset, subscriber welcome, Stripe lifecycle)
goes through this module. ``app.services.gmail_service.py`` is OAuth access
to a USER's own inbox — used for candidate-authored mail and for the
notification digest after the user approves it.

Exactly ONE of two providers is selected by which env vars are present,
checked in this fixed order:

1. SMTP — ``AETHER_SMTP_HOST`` set. Also reads ``AETHER_SMTP_PORT`` (default
   587), ``AETHER_SMTP_USER``, ``AETHER_SMTP_PASS``, ``AETHER_SMTP_FROM``
   (falls back to ``AETHER_SMTP_USER`` when unset).
2. A Resend-style HTTPS API — ``AETHER_EMAIL_API_KEY`` set (checked only when
   SMTP is not configured). Also reads ``AETHER_EMAIL_FROM``.

Neither configured: :func:`send_email` returns ``False`` and logs a single
operator-actionable INFO line (see ``docs/delivery/EMAIL-SETUP.md``) — it
NEVER raises and NEVER claims a send that did not happen. Callers use the
return value to render an honest state to the end user rather than a
fabricated "email sent" claim (the exact anti-pattern this module exists to
avoid — no silent fallback that pretends to have sent mail).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import TypedDict

logger = logging.getLogger(__name__)


class _SmtpConfig(TypedDict):
    host: str
    port: str
    user: str
    password: str
    from_addr: str


class _ApiConfig(TypedDict):
    api_key: str
    from_addr: str


def _smtp_env() -> _SmtpConfig | None:
    host = os.environ.get("AETHER_SMTP_HOST", "").strip()
    if not host:
        return None
    user = os.environ.get("AETHER_SMTP_USER", "").strip()
    return {
        "host": host,
        "port": os.environ.get("AETHER_SMTP_PORT", "587").strip() or "587",
        "user": user,
        "password": os.environ.get("AETHER_SMTP_PASS", ""),
        "from_addr": os.environ.get("AETHER_SMTP_FROM", "").strip() or user,
    }


def _api_env() -> _ApiConfig | None:
    api_key = os.environ.get("AETHER_EMAIL_API_KEY", "").strip()
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "from_addr": os.environ.get("AETHER_EMAIL_FROM", "").strip(),
    }


# Process-level "did the most recent ATTEMPTED send succeed" state (MF-3).
# Deliberately deployment-level, not per-request/per-address: a provider
# outage is independent of whether any particular account exists, so a
# caller reading this after building its response does not weaken
# anti-enumeration (every request reads the same shared value; it is never
# derived from whether THIS request happened to attempt a send). ``None``
# means no attempt has happened yet this process — reported as "not
# degraded" (no evidence of failure).
_last_attempted_send_ok: bool | None = None


def delivery_degraded() -> bool:
    """True iff the most recent ATTEMPTED outbound send in this process failed.

    "Attempted" excludes the no-provider-configured case (that is already
    surfaced honestly via ``is_configured()`` / ``emailSendingEnabled``) —
    this only tracks real transport failures: bad credentials, provider
    outage, unverified sending domain, etc. (see ``_send_via_smtp`` /
    ``_send_via_api``).
    """
    return _last_attempted_send_ok is False


def active_provider() -> str | None:
    """``"smtp"`` | ``"api"`` | ``None`` — whichever provider is configured.

    SMTP wins when both are present (matches the finding's "whichever env is
    present" language with a deterministic tie-break rather than an
    unspecified one).
    """
    if _smtp_env() is not None:
        return "smtp"
    if _api_env() is not None:
        return "api"
    return None


def is_configured() -> bool:
    """True when a usable outbound-email provider is configured.

    "Usable" also requires a sender address (``AETHER_SMTP_FROM``/
    ``AETHER_SMTP_USER`` or ``AETHER_EMAIL_FROM``) — a provider with no
    sender address can never actually deliver, so it is treated the same as
    unconfigured for the honest FE flag.
    """
    provider = active_provider()
    if provider == "smtp":
        smtp_cfg = _smtp_env()
        return bool(smtp_cfg and smtp_cfg["from_addr"])
    if provider == "api":
        api_cfg = _api_env()
        return bool(api_cfg and api_cfg["from_addr"])
    return False


def _send_via_smtp(
    to_email: str, subject: str, text_body: str, html_body: str | None = None
) -> bool:
    cfg = _smtp_env()
    if cfg is None or not cfg["from_addr"]:
        logger.info(
            "email_sender: AETHER_SMTP_HOST is set but no sender address "
            "(AETHER_SMTP_FROM/AETHER_SMTP_USER) is configured; operator "
            "action required — outbound email NOT sent to %s",
            to_email,
        )
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email
    msg.set_content(text_body)
    if html_body:
        # multipart/alternative with the plain text FIRST — the HTML is an
        # alternative rendering, never a replacement: a text-only client must
        # still receive the complete message.
        msg.add_alternative(html_body, subtype="html")
    try:
        port = int(cfg["port"])
    except ValueError:
        port = 587
    try:
        with smtplib.SMTP(cfg["host"], port, timeout=10) as smtp:
            smtp.starttls()
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - any transport failure is a send failure
        logger.exception(
            "email_sender: SMTP send failed for %s via %s", to_email, cfg["host"]
        )
        return False


def _send_via_api(
    to_email: str, subject: str, text_body: str, html_body: str | None = None
) -> bool:
    cfg = _api_env()
    if cfg is None or not cfg["from_addr"]:
        logger.info(
            "email_sender: AETHER_EMAIL_API_KEY is set but AETHER_EMAIL_FROM "
            "is not configured; operator action required — outbound email "
            "NOT sent to %s",
            to_email,
        )
        return False
    import httpx

    payload: dict[str, object] = {
        "from": cfg["from_addr"],
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        # Key omitted entirely when there is no HTML alternative, so the
        # request stays byte-identical to the pre-existing behaviour.
        payload["html"] = html_body
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json=payload,
            timeout=10.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "email_sender: API send to %s failed: HTTP %s %s",
                to_email,
                resp.status_code,
                resp.text[:200],
            )
            return False
        return True
    except Exception:  # noqa: BLE001 - any transport failure is a send failure
        logger.exception("email_sender: API send failed for %s", to_email)
        return False


def send_email(
    to_email: str, subject: str, text_body: str, html_body: str | None = None
) -> bool:
    """Best-effort outbound send; ``True`` only on a confirmed provider success.

    ``html_body`` is OPTIONAL and additive: when given, the message goes out
    as ``multipart/alternative`` with ``text_body`` as the FIRST alternative
    (SMTP) or with an extra ``html`` field (API provider). Aether-owned mail
    passes the branded HTML from
    :func:`app.services.email_branding.render_branded_email` here; leaving it
    ``None`` reproduces the previous plain-text behaviour exactly, which is
    what user-authored and outreach mail deliberately keeps.

    Never raises — a transactional-email failure must never break the
    caller's request (``POST /auth/forgot-password`` stays a 200 either way,
    to preserve anti-enumeration). No provider configured logs one
    operator-actionable INFO line and returns ``False`` (this case does NOT
    update ``delivery_degraded()`` — "not configured" and "configured but
    failing" are honestly distinct states, surfaced separately to callers as
    ``emailSendingEnabled`` and ``deliveryDegraded`` respectively).
    """
    global _last_attempted_send_ok
    provider = active_provider()
    if provider is None:
        logger.info(
            "email_sender: no outbound email provider configured "
            "(AETHER_SMTP_HOST or AETHER_EMAIL_API_KEY) — email to %s NOT "
            "sent. See docs/delivery/EMAIL-SETUP.md to enable.",
            to_email,
        )
        return False
    ok = (
        _send_via_smtp(to_email, subject, text_body, html_body)
        if provider == "smtp"
        else _send_via_api(to_email, subject, text_body, html_body)
    )
    _last_attempted_send_ok = ok
    return ok
