"""Gmail receipt gate for a live site application.

A click on the employer's Submit control is an attempt, not a transmission.
The Applications tracker may only move a card to Submitted after
``Application.transmittedAt`` is stamped, and that stamp now requires the
candidate's OWN connected Gmail to carry an ATS application-receipt matching
this employer and this role, arrived AFTER the submit click.

This module never invents a receipt. Matching is conservative: an ATS sender
or a receipt subject, PLUS the employer name or the job title, PLUS freshness
against the submit click. Verification-code mail is excluded — that is a gate
before the employer has the application, not proof they received it.

Replay / fixture pages never call this: nothing left the building.
"""
from __future__ import annotations

import logging
import os
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

MANUAL_STEP_AWAITING_RECEIPT = "awaiting_receipt"
MANUAL_STEP_RECEIPT_GMAIL_UNAVAILABLE = "receipt_gmail_unavailable"

#: Clock skew between Gmail's Date / internalDate and this VM.
_FRESHNESS_SKEW_SECONDS = 30.0

#: ATS infrastructure that actually sends application receipts. Employer
#: marketing mail from the company domain is not enough on its own.
RECEIPT_SENDER_DOMAINS: tuple[str, ...] = (
    "ashbyhq.com",
    "greenhouse-mail.io",
    "greenhouse.io",
    "hire.lever.co",
    "lever.co",
    "smartrecruiters.com",
    "myworkday.com",
    "workday.com",
    "icims.com",
    "successfactors.com",
    "workablemail.com",
)

_RECEIPT_SUBJECT = re.compile(
    r"thank(?:s| you) for apply"
    r"|thanks for your application"
    r"|application (?:to .+ )?(?:was |has been |is )?(?:received|submitted)"
    r"|we(?:'|’)?(?:ve| have)? received your application"
    r"|application confirmation"
    r"|your application to "
    r"|successfully submitted"
    r"|application (?:is|has been) (?:in|complete|on file)",
    re.I,
)

_VERIFICATION_SUBJECT = re.compile(
    r"security code|verification code|confirmation code|one[- ]time (?:code|passcode)",
    re.I,
)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def receipt_poll_interval_seconds() -> float:
    return _env_float("AETHER_APPLY_RECEIPT_POLL_INTERVAL_SECONDS", 5.0)


def receipt_poll_timeout_seconds() -> float:
    return _env_float("AETHER_APPLY_RECEIPT_POLL_TIMEOUT_SECONDS", 180.0)


def build_receipt_query() -> str:
    """Gmail search for recent ATS application receipts — no employer literal.

    Company matching happens after the fetch so a hyphenated employer name
    cannot drop the very message we are waiting for.
    """
    senders = " OR ".join(f"from:{domain}" for domain in RECEIPT_SENDER_DOMAINS)
    return (
        f"(({senders}) OR subject:\"thank you for applying\" "
        f"OR subject:\"thanks for applying\" "
        f"OR subject:\"application received\" "
        f"OR subject:\"application confirmation\" "
        f"OR subject:\"we received your application\") newer_than:1d"
    )


def _haystack(header: dict[str, Any], body: dict[str, Any] | None = None) -> str:
    parts = [
        str(header.get("from") or ""),
        str(header.get("subject") or ""),
    ]
    if body:
        parts.append(str(body.get("text") or ""))
        parts.append(re.sub(r"<[^>]+>", " ", str(body.get("html") or "")))
    return " ".join(parts)


def _sender_is_ats(from_header: str) -> bool:
    lowered = (from_header or "").lower()
    return any(domain in lowered for domain in RECEIPT_SENDER_DOMAINS)


def received_epoch(header: dict[str, Any]) -> float:
    """Gmail internalDate (ms) preferred; Date header is sender-supplied."""
    internal = header.get("internalDate")
    if internal not in (None, ""):
        try:
            return float(internal) / 1000.0
        except (TypeError, ValueError):
            pass
    raw = str(header.get("date") or "").strip()
    if not raw:
        return 0.0
    try:
        return parsedate_to_datetime(raw).timestamp()
    except Exception:  # noqa: BLE001 — unparseable is simply not proof
        return 0.0


def is_fresh_receipt(header: dict[str, Any], since_epoch: float) -> bool:
    received = received_epoch(header)
    if received <= 0:
        return False
    return received >= since_epoch - _FRESHNESS_SKEW_SECONDS


def _mentions(haystack: str, needle: str | None) -> bool:
    text = (needle or "").strip()
    if len(text) < 3:
        return False
    return text.lower() in haystack.lower()


def is_application_receipt(
    header: dict[str, Any],
    *,
    company: str | None,
    job_title: str | None,
    since_epoch: float,
    body: dict[str, Any] | None = None,
) -> bool:
    """True only for a fresh ATS receipt that names this employer or this role."""
    if not is_fresh_receipt(header, since_epoch):
        return False
    subject = str(header.get("subject") or "")
    if _VERIFICATION_SUBJECT.search(subject):
        return False
    haystack = _haystack(header, body)
    receipt_shaped = bool(_RECEIPT_SUBJECT.search(subject) or _sender_is_ats(
        str(header.get("from") or "")
    ))
    if body and not _RECEIPT_SUBJECT.search(subject):
        receipt_shaped = receipt_shaped or bool(_RECEIPT_SUBJECT.search(haystack))
    if not receipt_shaped:
        return False
    return _mentions(haystack, company) or _mentions(haystack, job_title)


def _iter_connected_account_ids(user_id: str) -> list[str]:
    from app.repositories.gmail_account import GmailAccountRepository

    rows = GmailAccountRepository().list_accounts(user_id)
    ids: list[str] = []
    for row in rows:
        if not row.get("refreshToken"):
            continue
        account_id = str(row.get("id") or "").strip()
        if account_id:
            ids.append(account_id)
    return ids


def poll_application_receipt(
    user_id: str,
    *,
    since_epoch: float,
    company: str | None = None,
    job_title: str | None = None,
    gmail_factory: Callable[..., Any] | None = None,
    account_ids: Iterable[str] | None = None,
    sleeper: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    interval_seconds: float | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any] | None:
    """Wait for a receipt in EVERY connected Gmail. ``None`` on timeout.

    A missing or revoked grant is not something waiting can fix — that becomes
    :class:`ReceiptMailboxUnavailable`. Transient list failures are retried.
    """
    from app.services.gmail_service import (
        GmailAuthError,
        GmailNotConnectedError,
        GmailService,
    )

    factory: Callable[..., Any] = gmail_factory or GmailService
    sleep = sleeper or time.sleep
    clock = monotonic or time.monotonic
    interval = (
        interval_seconds if interval_seconds is not None else receipt_poll_interval_seconds()
    )
    timeout = (
        timeout_seconds if timeout_seconds is not None else receipt_poll_timeout_seconds()
    )
    query = build_receipt_query()
    started = clock()
    deadline = started + max(timeout, 0.0)
    attempts = 0
    auth_failures = 0
    while True:
        attempts += 1
        ids = list(account_ids) if account_ids is not None else _iter_connected_account_ids(user_id)
        if not ids:
            raise ReceiptMailboxUnavailable(
                "Gmail is not connected — Aether cannot see whether the "
                "employer emailed an application receipt."
            )
        saw_mailbox = False
        for account_id in ids:
            service: Any = None
            headers: list[dict[str, Any]] = []
            try:
                service = factory(user_id, account_id=account_id)
                headers = list(service.list_message_headers(query=query, max_results=20) or [])
                saw_mailbox = True
            except (GmailNotConnectedError, GmailAuthError):
                auth_failures += 1
                continue
            except TypeError:
                # Test doubles and the historical one-arg constructor.
                try:
                    service = factory(user_id)
                    headers = list(
                        service.list_message_headers(query=query, max_results=20) or []
                    )
                    saw_mailbox = True
                except (GmailNotConnectedError, GmailAuthError):
                    auth_failures += 1
                    continue
                except Exception as exc:  # noqa: BLE001 — transient, retry
                    logger.info(
                        "apply-receipt: mailbox poll %d failed (%s) — retrying",
                        attempts,
                        type(exc).__name__,
                    )
                    continue
            except Exception as exc:  # noqa: BLE001 — transient, retry
                logger.info(
                    "apply-receipt: mailbox poll %d failed (%s) — retrying",
                    attempts,
                    type(exc).__name__,
                )
                continue
            for header in sorted(headers, key=received_epoch, reverse=True):
                if service is None or not is_fresh_receipt(header, since_epoch):
                    continue
                body: dict[str, Any] | None = None
                try:
                    body = service.get_message_bodies(str(header.get("id") or ""))
                except Exception:  # noqa: BLE001 — subject/from may already be enough
                    body = None
                if not is_application_receipt(
                    header,
                    company=company,
                    job_title=job_title,
                    since_epoch=since_epoch,
                    body=body,
                ):
                    continue
                return {
                    "messageId": str(header.get("id") or ""),
                    "threadId": str(header.get("threadId") or ""),
                    "from": str(header.get("from") or ""),
                    "subject": str(header.get("subject") or ""),
                    "receivedAt": str(header.get("date") or ""),
                    "accountId": account_id,
                    "pollAttempts": attempts,
                    "pollSeconds": round(clock() - started, 1),
                }
        if not saw_mailbox and auth_failures:
            raise ReceiptMailboxUnavailable(
                "Gmail is not connected — Aether cannot see whether the "
                "employer emailed an application receipt."
            )
        if clock() >= deadline:
            return None
        sleep(interval)


class ReceiptMailboxUnavailable(RuntimeError):
    """Every connected inbox refused the grant. Waiting cannot fix this."""


def awaiting_receipt_detail(
    *,
    company: str | None,
    job_title: str | None,
    form_email: str | None = None,
) -> str:
    employer = (company or "").strip() or "This employer"
    role = (job_title or "").strip() or "this role"
    where = (form_email or "").strip() or "your connected Gmail"
    return (
        f"{employer} was submitted on the employer's site for {role}, but "
        f"Aether has not yet found an application receipt in {where}. "
        "The card is NOT Submitted until that receipt arrives — Aether will "
        "keep watching the connected inbox(es) and will not click Submit again."
    )
