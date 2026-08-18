"""Sales Agent data layer — leads, campaigns, outreach log, suppression.

Native in-app replacement for the external growth engine (see
``docs/growth/README.md``). Four additive tables created via the repo's
standard lazy-idempotent DDL pattern (advisory lock + CREATE TABLE IF NOT
EXISTS, never destructive), plus one additive column on ``GmailAccount``
(``usedForSalesAgent``) marking the mailbox the agent sends from.

HARD COMPLIANCE GATES (DB-enforced, not prompt discipline):

* **Idempotency** — partial unique index on ``SalesOutreachLog(gmailThreadId)
  WHERE outcome='sent' AND channel='email'``: a second send on the same thread
  hits a constraint violation, it does not rely on the model remembering.
* **Suppression** — :meth:`SalesRepository.is_suppressed` is checked before
  every send; an inbound "unsubscribe" permanently inserts into
  ``SalesSuppressionList`` (primary-keyed on lower-cased email).
* **Recipient provenance** — ``consentType``/``consentEvidence`` are NOT NULL
  and :meth:`SalesRepository.create_lead` REFUSES a lead whose consent type is
  not in the ratified set or whose evidence is empty. There is no code path
  that constructs a lead from a guessed address.
* **Rate limiting** — :meth:`SalesRepository.lifecycle_email_sent_since`
  answers "was this user already nudged this billing cycle" from the log, so
  one nudge/re-engagement per user per cycle is a DB check.

``SalesLead.userId`` auto-backfills by email match against ``User``.email on
insert ([DECISION NEEDED] in the build brief — resolved YES, per its own
recommendation, so lead activity joins real plan/subscription data).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2

from app.db import (
    ensure_user_lifecycle_columns,
    ensure_user_signup_source_column,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.services.stripe_gateway import rewrite_retired_product_urls

#: First-touch utm_source Sales AI stamps on product URLs. Must match
#: ``app.agents.sales_agent.SALES_AI_UTM_SOURCE``.
SALES_AI_SIGNUP_SOURCE = "aether_sales_agent"

#: Ratified consent types (build brief §4.1). Anything else is refused.
CONSENT_TYPES = frozenset(
    {"inbound_signal", "existing_relationship", "existing_user_lifecycle"}
)

#: Ratified lead sources.
LEAD_SOURCES = frozenset(
    {"inbound_email", "existing_user", "referral", "manual_approved"}
)

#: Ratified campaign types (build brief §4.1).
CAMPAIGN_TYPES = frozenset(
    {"welcome", "free_to_paid_nudge", "reengagement", "demo_response", "linkedin_draft"}
)

#: Lead statuses.
LEAD_STATUSES = frozenset(
    {"new", "contacted", "replied", "converted", "unsubscribed", "bounced"}
)

#: Outreach outcomes. ``dry_run`` is additive to the brief's list: the shadow
#: mode (§9) must log what WOULD have been sent as a distinct, honest outcome —
#: never as a fake ``sent``.
OUTREACH_OUTCOMES = frozenset(
    {"sent", "replied", "bounced", "unsubscribed", "draft_queued", "dry_run",
     "blocked", "error", "reserved"}
)

#: The two outcomes that spend a LinkedIn draft slot. ``reserved`` is additive:
#: it marks a slot claimed BEFORE the model call, so two overlapping runs can
#: never both pass a cadence check that neither has yet recorded.
DRAFT_QUEUED = "draft_queued"
DRAFT_RESERVED = "reserved"

#: A reservation older than this never became a draft (the run was killed
#: between claiming the slot and writing the post), so it is reclaimed on the
#: next reserve rather than holding a weekly slot until the window rolls past.
LINKEDIN_RESERVATION_TTL_MINUTES = 15

_ADVISORY_LOCK = 7420240725  # next free id per the repo's lock registry
#: Serializes the LinkedIn weekly-cadence reserve (count + claim) across
#: processes. Held for the duration of that ONE short transaction only.
_LINKEDIN_CADENCE_LOCK = 7420240726

_tables_ready = False


class ConsentViolationError(ValueError):
    """A lead insert was attempted without ratified consent provenance."""


class DuplicateSendError(Exception):
    """The DB idempotency constraint rejected a second 'sent' on a thread."""


def _ensure_sales_tables() -> None:
    """Create the additive sales tables + indexes on first use (idempotent)."""
    global _tables_ready
    if _tables_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "SalesLead" (
                    "id"              text PRIMARY KEY,
                    "email"           text NOT NULL,
                    "name"            text,
                    "source"          text NOT NULL,
                    "sourceThreadId"  text,
                    "userId"          text,
                    "consentType"     text NOT NULL,
                    "consentEvidence" text NOT NULL,
                    "status"          text NOT NULL DEFAULT 'new',
                    "createdAt"       timestamptz NOT NULL DEFAULT NOW(),
                    "updatedAt"       timestamptz NOT NULL DEFAULT NOW()
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "SalesLead_email_key" '
                'ON "SalesLead" (LOWER("email"))'
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "SalesCampaign" (
                    "id"           text PRIMARY KEY,
                    "name"         text NOT NULL,
                    "type"         text NOT NULL,
                    "templateBody" text NOT NULL,
                    "active"       boolean NOT NULL DEFAULT true,
                    "createdAt"    timestamptz NOT NULL DEFAULT NOW(),
                    "updatedAt"    timestamptz NOT NULL DEFAULT NOW()
                )
                '''
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "SalesOutreachLog" (
                    "id"             text PRIMARY KEY,
                    "leadId"         text,
                    "campaignId"     text,
                    "channel"        text NOT NULL,
                    "gmailMessageId" text,
                    "gmailThreadId"  text,
                    "subject"        text,
                    "body"           text,
                    "recipient"      text,
                    "sentAt"         timestamptz,
                    "outcome"        text,
                    "detail"         text,
                    "createdAt"      timestamptz NOT NULL DEFAULT NOW()
                )
                '''
            )
            # Idempotency gate (build brief §6): one real email send per Gmail
            # thread, enforced by the database.
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS '
                '"SalesOutreachLog_sent_thread_key" '
                'ON "SalesOutreachLog" ("gmailThreadId") '
                "WHERE \"outcome\" = 'sent' AND \"channel\" = 'email'"
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS '
                '"SalesOutreachLog_message_key" '
                'ON "SalesOutreachLog" ("gmailMessageId") '
                'WHERE "gmailMessageId" IS NOT NULL'
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "SalesSuppressionList" (
                    "email"          text PRIMARY KEY,
                    "reason"         text NOT NULL,
                    "suppressedAt"   timestamptz NOT NULL DEFAULT NOW(),
                    "sourceThreadId" text
                )
                '''
            )
            # Additive per-account role flag on the EXISTING Gmail credential
            # table ([DECISION NEEDED] resolved: add additively) — marks which
            # connected mailbox the sales agent polls and sends from.
            cur.execute(
                'ALTER TABLE IF EXISTS "GmailAccount" '
                'ADD COLUMN IF NOT EXISTS "usedForSalesAgent" boolean '
                'NOT NULL DEFAULT false'
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "SalesBrandArtifact" (
                    "id"          text PRIMARY KEY,
                    "kind"        text NOT NULL,
                    "inputHash"   text NOT NULL,
                    "input"       jsonb NOT NULL,
                    "content"     text NOT NULL,
                    "createdById" text NOT NULL,
                    "createdAt"   timestamptz NOT NULL DEFAULT NOW()
                )
                '''
            )
            cur.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS "SalesBrandArtifact_kind_inputHash_key" '
                'ON "SalesBrandArtifact" ("kind", "inputHash")'
            )
        conn.commit()
    _tables_ready = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SalesRepository:
    """Raw-SQL repository for the sales agent's four tables."""

    def __init__(self) -> None:
        _ensure_sales_tables()

    # ------------------------------------------------------- brand artifacts
    def get_or_create_brand_artifact(
        self,
        *,
        kind: str,
        input_hash: str,
        artifact_input: dict[str, str],
        content: str,
        created_by_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Persist a reproducible creative or return its existing content hash.

        The unique index is the concurrency-safe dedupe boundary.  A rendered
        SVG and its exact normalized source are retained for auditability.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "SalesBrandArtifact"
                        ("id","kind","inputHash","input","content","createdById")
                    VALUES (%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT ("kind","inputHash") DO NOTHING
                    RETURNING *
                    ''',
                    (
                        new_id(), kind, input_hash, json.dumps(artifact_input), content,
                        created_by_id,
                    ),
                )
                rows = rows_to_dicts(cur)
                if rows:
                    conn.commit()
                    return rows[0], False
                cur.execute(
                    'SELECT * FROM "SalesBrandArtifact" '
                    'WHERE "kind"=%s AND "inputHash"=%s',
                    (kind, input_hash),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        assert rows
        return rows[0], True

    # ------------------------------------------------------------- leads
    def create_lead(
        self,
        *,
        email: str,
        consent_type: str,
        consent_evidence: str,
        source: str,
        name: str | None = None,
        source_thread_id: str | None = None,
        status: str = "new",
    ) -> dict[str, Any]:
        """Insert a lead (or return the existing one for that email).

        Enforces recipient provenance (build brief §6): refuses unratified
        consent types, empty evidence, and inbound leads without a real
        Gmail thread/message id as evidence.
        """
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ConsentViolationError("A lead requires a real email address.")
        if consent_type not in CONSENT_TYPES:
            raise ConsentViolationError(
                f"consentType {consent_type!r} is not a ratified consent type."
            )
        if not (consent_evidence or "").strip():
            raise ConsentViolationError("consentEvidence must not be empty.")
        if source not in LEAD_SOURCES:
            raise ConsentViolationError(f"source {source!r} is not ratified.")
        if source == "inbound_email" and not (source_thread_id or "").strip():
            raise ConsentViolationError(
                "An inbound_email lead requires the real Gmail thread id."
            )
        existing = self.get_lead_by_email(email)
        if existing is not None:
            return existing
        user_id = self._user_id_for_email(email)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "SalesLead"
                        ("id","email","name","source","sourceThreadId","userId",
                         "consentType","consentEvidence","status")
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (LOWER("email")) DO NOTHING
                    RETURNING *
                    ''',
                    (new_id(), email, name, source, source_thread_id, user_id,
                     consent_type, consent_evidence, status),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        if rows:
            return rows[0]
        # Concurrent insert won the race — return the winner's row.
        found = self.get_lead_by_email(email)
        assert found is not None
        return found

    def _user_id_for_email(self, email: str) -> str | None:
        """Auto-backfill: map a lead email to an existing Aether account."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id" FROM "User" WHERE LOWER("email") = LOWER(%s) LIMIT 1',
                    (email,),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def get_lead_by_email(self, email: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT * FROM "SalesLead" WHERE LOWER("email") = LOWER(%s)',
                    (email,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_leads(
        self,
        *,
        status: str | None = None,
        source: str | None = None,
        consent_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append('"status" = %s')
            params.append(status)
        if source:
            clauses.append('"source" = %s')
            params.append(source)
        if consent_type:
            clauses.append('"consentType" = %s')
            params.append(consent_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT COUNT(*) FROM "SalesLead" {where}', params
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    f'SELECT * FROM "SalesLead" {where} '
                    'ORDER BY "createdAt" DESC LIMIT %s OFFSET %s',
                    [*params, max(1, min(int(limit), 200)), max(0, int(offset))],
                )
                rows = rows_to_dicts(cur)
        return rows, total

    def set_lead_status(self, lead_id: str, status: str) -> None:
        if status not in LEAD_STATUSES:
            raise ValueError(f"unknown lead status {status!r}")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "SalesLead" SET "status"=%s, "updatedAt"=NOW() '
                    'WHERE "id"=%s',
                    (status, lead_id),
                )
            conn.commit()

    # --------------------------------------------------------- campaigns
    def list_campaigns(self, include_inactive: bool = True) -> list[dict[str, Any]]:
        where = "" if include_inactive else 'WHERE "active" = true'
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT * FROM "SalesCampaign" {where} ORDER BY "createdAt" ASC'
                )
                rows = rows_to_dicts(cur)
        return rows

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT * FROM "SalesCampaign" WHERE "id" = %s', (campaign_id,)
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def active_campaign_by_type(self, ctype: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT * FROM "SalesCampaign" '
                    'WHERE "type" = %s AND "active" = true '
                    'ORDER BY "updatedAt" DESC LIMIT 1',
                    (ctype,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def create_campaign(
        self, *, name: str, ctype: str, template_body: str, active: bool = True
    ) -> dict[str, Any]:
        if ctype not in CAMPAIGN_TYPES:
            raise ValueError(f"unknown campaign type {ctype!r}")
        if not (name or "").strip() or not (template_body or "").strip():
            raise ValueError("name and templateBody are required")
        template_body = rewrite_retired_product_urls(template_body)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "SalesCampaign"
                        ("id","name","type","templateBody","active")
                    VALUES (%s,%s,%s,%s,%s) RETURNING *
                    ''',
                    (new_id(), name.strip(), ctype, template_body, active),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def update_campaign(
        self,
        campaign_id: str,
        *,
        name: str | None = None,
        template_body: str | None = None,
        active: bool | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = ['"updatedAt" = NOW()']
        params: list[Any] = []
        if name is not None:
            sets.append('"name" = %s')
            params.append(name.strip())
        if template_body is not None:
            sets.append('"templateBody" = %s')
            params.append(rewrite_retired_product_urls(template_body))
        if active is not None:
            sets.append('"active" = %s')
            params.append(bool(active))
        params.append(campaign_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "SalesCampaign" SET {", ".join(sets)} '
                    'WHERE "id" = %s RETURNING *',
                    params,
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def seed_default_campaigns(self) -> int:
        """Insert the default template set once (skipped if any campaign exists).

        Always rewrites retired Abacus hosts in stored operator copy so a
        template seeded before the Hostinger cutover cannot be copied or
        previewed with a dead URL.
        """
        created = 0
        if not self.list_campaigns():
            for name, ctype, body in DEFAULT_CAMPAIGNS:
                self.create_campaign(name=name, ctype=ctype, template_body=body)
                created += 1
        self.rewrite_retired_product_hosts()
        return created

    def rewrite_retired_product_hosts(self) -> dict[str, int]:
        """Persist the live product origin into live operator copy.

        Campaign templates and unposted LinkedIn drafts are artefacts the
        founder will send or copy. Historical ``sent`` / ``dry_run`` outreach
        is left alone — that is the audit of what actually left the mailbox.
        """
        campaigns_rewritten = 0
        for row in self.list_campaigns():
            body = row.get("templateBody") or ""
            rewritten = rewrite_retired_product_urls(body)
            if rewritten != body:
                self.update_campaign(row["id"], template_body=rewritten)
                campaigns_rewritten += 1

        drafts_rewritten = 0
        drafts, _total = self.list_outreach(
            outcome=DRAFT_QUEUED, channel="linkedin_draft", limit=200
        )
        for row in drafts:
            body = row.get("body") or ""
            rewritten = rewrite_retired_product_urls(body)
            if rewritten != body:
                self._update_outreach_body(row["id"], rewritten)
                drafts_rewritten += 1
        return {
            "campaigns": campaigns_rewritten,
            "linkedinDrafts": drafts_rewritten,
        }

    def _update_outreach_body(self, outreach_id: str, body: str) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "SalesOutreachLog" SET "body" = %s '
                    'WHERE "id" = %s AND "outcome" = %s',
                    (body, outreach_id, DRAFT_QUEUED),
                )
            conn.commit()

    # ------------------------------------------------------ outreach log
    def record_outreach(
        self,
        *,
        channel: str,
        outcome: str,
        lead_id: str | None = None,
        campaign_id: str | None = None,
        gmail_message_id: str | None = None,
        gmail_thread_id: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        recipient: str | None = None,
        sent_at: datetime | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        """Append to the outreach log. A duplicate real send on the same
        thread raises :class:`DuplicateSendError` (the DB constraint)."""
        if outcome not in OUTREACH_OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        if channel not in ("email", "linkedin_draft"):
            raise ValueError(f"unknown channel {channel!r}")
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        '''
                        INSERT INTO "SalesOutreachLog"
                            ("id","leadId","campaignId","channel","gmailMessageId",
                             "gmailThreadId","subject","body","recipient","sentAt",
                             "outcome","detail")
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING *
                        ''',
                        (new_id(), lead_id, campaign_id, channel, gmail_message_id,
                         gmail_thread_id, subject, body, recipient, sent_at,
                         outcome, detail),
                    )
                    rows = rows_to_dicts(cur)
                conn.commit()
        except psycopg2.errors.UniqueViolation as exc:
            raise DuplicateSendError(
                f"thread {gmail_thread_id!r} already has a 'sent' outreach row"
            ) from exc
        except psycopg2.IntegrityError as exc:  # driver-version safety net
            raise DuplicateSendError(str(exc)) from exc
        return rows[0]

    def thread_already_sent(self, gmail_thread_id: str) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "SalesOutreachLog" '
                    "WHERE \"gmailThreadId\" = %s AND \"outcome\" = 'sent' "
                    "AND \"channel\" = 'email' LIMIT 1",
                    (gmail_thread_id,),
                )
                return cur.fetchone() is not None

    def message_already_processed(self, gmail_message_id: str) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "SalesOutreachLog" '
                    'WHERE "gmailMessageId" = %s LIMIT 1',
                    (gmail_message_id,),
                )
                return cur.fetchone() is not None

    def list_outreach(
        self,
        *,
        outcome: str | None = None,
        channel: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if outcome:
            clauses.append('"outcome" = %s')
            params.append(outcome)
        if channel:
            clauses.append('"channel" = %s')
            params.append(channel)
        if since:
            clauses.append('"createdAt" >= %s')
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT COUNT(*) FROM "SalesOutreachLog" {where}', params
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    f'SELECT * FROM "SalesOutreachLog" {where} '
                    'ORDER BY "createdAt" DESC LIMIT %s OFFSET %s',
                    [*params, max(1, min(int(limit), 200)), max(0, int(offset))],
                )
                rows = rows_to_dicts(cur)
        return rows, total

    def lifecycle_email_sent_since(
        self, email: str, since: datetime, campaign_types: tuple[str, ...] = (
            "free_to_paid_nudge", "reengagement",
        ),
    ) -> bool:
        """DB rate-limit check: was a nudge/re-engagement ALREADY sent (or
        dry-run-logged) to this address since ``since`` (billing-cycle start)?"""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    SELECT 1 FROM "SalesOutreachLog" o
                    LEFT JOIN "SalesCampaign" c ON c."id" = o."campaignId"
                    WHERE LOWER(o."recipient") = LOWER(%s)
                      AND o."createdAt" >= %s
                      AND o."outcome" IN ('sent','dry_run')
                      AND (c."type" = ANY(%s) OR o."campaignId" IS NULL)
                    LIMIT 1
                    ''',
                    (email, since, list(campaign_types)),
                )
                return cur.fetchone() is not None

    # -------------------------------------------------------- suppression
    def suppress(
        self, email: str, reason: str, source_thread_id: str | None = None
    ) -> None:
        email = (email or "").strip().lower()
        if not email:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO "SalesSuppressionList"
                        ("email","reason","sourceThreadId")
                    VALUES (%s,%s,%s)
                    ON CONFLICT ("email") DO NOTHING
                    ''',
                    (email, reason, source_thread_id),
                )
            conn.commit()

    def is_suppressed(self, email: str) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "SalesSuppressionList" '
                    'WHERE "email" = LOWER(%s) LIMIT 1',
                    ((email or "").strip(),),
                )
                return cur.fetchone() is not None

    def suppression_count(self) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM "SalesSuppressionList"')
                return int(cur.fetchone()[0])

    def list_suppressions(self, limit: int = 200) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT * FROM "SalesSuppressionList" '
                    'ORDER BY "suppressedAt" DESC LIMIT %s',
                    (max(1, min(int(limit), 500)),),
                )
                return rows_to_dicts(cur)

    # ----------------------------------------------------- sending account
    def sales_sending_accounts(self, user_id: str) -> list[dict[str, Any]]:
        """Connected Gmail accounts flagged ``usedForSalesAgent`` (public shape,
        NO tokens)."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id","userId","accountEmail","isPrimary",'
                    '"usedForSalesAgent","syncStatus" FROM "GmailAccount" '
                    'WHERE "userId" = %s AND "usedForSalesAgent" = true '
                    'ORDER BY "isPrimary" DESC, "createdAt" ASC',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def list_gmail_accounts_public(self, user_id: str) -> list[dict[str, Any]]:
        """ALL of the admin's connected Gmail accounts (public shape, NO
        tokens) with the ``usedForSalesAgent`` flag — for the admin UI toggle."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id","userId","accountEmail","isPrimary",'
                    '"usedForSalesAgent","syncStatus" FROM "GmailAccount" '
                    'WHERE "userId" = %s '
                    'ORDER BY "isPrimary" DESC, "createdAt" ASC',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def set_sales_sending_account(
        self, user_id: str, account_id: str, enabled: bool
    ) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "GmailAccount" SET "usedForSalesAgent" = %s, '
                    '"updatedAt" = NOW() WHERE "id" = %s AND "userId" = %s',
                    (enabled, account_id, user_id),
                )
                updated = cur.rowcount > 0
            conn.commit()
        return updated

    # ----------------------------------------------------------- overview
    def overview(self) -> dict[str, Any]:
        """Real numbers only (build brief §6 'honest metrics').

        MRR joins ``Subscription.billingInterval`` so an annual plan counts at
        its true monthly-equivalent (priceAudAnnual / 12) instead of being
        double-counted at the full monthly price.

        ``signups`` excludes accounts an admin has deleted. ADMIN-2.0's delete
        is SOFT (``User.deletedAt``; eight child tables cascade off ``User.id``,
        so the row cannot go away), which means a plain ``COUNT(*)`` would keep
        counting deleted accounts as growth forever — and would disagree with
        ``/admin/metrics/executive``, which already excludes them
        (``admin_metrics.py:90,179``). Two admin screens contradicting each
        other about the same population is exactly the kind of untraceable
        figure this console is not allowed to show. Lazy-DDL contract as in
        ``_lifecycle_candidates``: the column post-dates this repository.
        """
        ensure_user_lifecycle_columns()
        ensure_user_signup_source_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Same population as /admin/metrics/executive (admin_metrics.py:
                # 90,179): admins are staff, not signups — counting them here
                # made the two admin screens disagree (6 vs 5).
                cur.execute(
                    'SELECT COUNT(*) FROM "User"'
                    ' WHERE "deletedAt" IS NULL AND "isAdmin" = false'
                )
                signups = int(cur.fetchone()[0])
                cur.execute(
                    '''
                    SELECT COUNT(*),
                           COALESCE(SUM(
                             CASE
                               WHEN s."billingInterval" = 'year'
                                 THEN COALESCE(p."priceAudAnnual", 0)::numeric / 12
                               ELSE COALESCE(p."priceAudMonthly", 0)::numeric
                             END
                           ), 0)
                    FROM "Subscription" s
                    JOIN "Plan" p ON p."id" = s."planId"
                    WHERE s."status" IN ('active','trialing','past_due')
                      AND LOWER(p."name") <> 'free'
                    ''',
                )
                paid_row = cur.fetchone()
                paid_conversions = int(paid_row[0])
                mrr_aud = float(paid_row[1])
                cur.execute(
                    "SELECT COUNT(*) FILTER (WHERE \"outcome\" = 'sent'),"
                    "       COUNT(*) FILTER (WHERE \"outcome\" = 'replied'),"
                    "       COUNT(*) FILTER (WHERE \"outcome\" = 'dry_run'),"
                    "       COUNT(*) FILTER (WHERE \"channel\" = 'linkedin_draft'"
                    "                        AND \"outcome\" = 'draft_queued')"
                    ' FROM "SalesOutreachLog"'
                )
                sent, replied, dry_run, drafts = cur.fetchone()
                cur.execute(
                    "SELECT COUNT(DISTINCT \"gmailThreadId\") "
                    "FILTER (WHERE \"outcome\" = 'sent' AND \"channel\" = 'email')"
                    ' FROM "SalesOutreachLog"'
                )
                sent_threads = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT COUNT(DISTINCT \"gmailThreadId\") "
                    "FILTER (WHERE \"outcome\" = 'replied')"
                    ' FROM "SalesOutreachLog"'
                )
                replied_threads = int(cur.fetchone()[0])
                cur.execute('SELECT COUNT(*) FROM "SalesLead"')
                lead_count = int(cur.fetchone()[0])
                cur.execute(
                    'SELECT COUNT(*) FROM "User"'
                    ' WHERE "deletedAt" IS NULL AND "isAdmin" = false'
                    ' AND "signupSource" = %s',
                    (SALES_AI_SIGNUP_SOURCE,),
                )
                attributed_signups = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT COUNT(*) FROM \"User\" u"
                    " JOIN \"Subscription\" s ON s.\"userId\" = u.\"id\""
                    " JOIN \"Plan\" p ON p.\"id\" = s.\"planId\""
                    " WHERE u.\"deletedAt\" IS NULL AND u.\"isAdmin\" = false"
                    " AND u.\"signupSource\" = %s"
                    " AND s.\"status\" IN ('active','trialing','past_due')"
                    " AND LOWER(p.\"name\") <> 'free'",
                    (SALES_AI_SIGNUP_SOURCE,),
                )
                attributed_paid = int(cur.fetchone()[0])
        # Distinct mailed threads in the denominator. repliesObserved stays
        # the COUNT of replied rows. Rate is null until a real send exists —
        # 0.0% with zero sends would invent a measurement.
        reply_rate = (
            (replied_threads / sent_threads) if sent_threads > 0 else None
        )
        return {
            "signups": signups,
            "paidConversions": paid_conversions,
            "mrrAud": round(mrr_aud, 2),
            "leads": lead_count,
            "emailsSent": int(sent),
            "repliesObserved": int(replied),
            "replyRate": reply_rate,
            "dryRunLogged": int(dry_run),
            "linkedinDraftsQueued": int(drafts),
            "suppressionCount": self.suppression_count(),
            "attributedSignups": attributed_signups,
            "attributedPaid": attributed_paid,
        }

    # ------------------------------------------------------------ watermark
    # Stored in AdminSetting (existing key/value store) so no fifth table is
    # needed. Key is per Gmail account id.
    @staticmethod
    def get_watermark(account_id: str) -> dict[str, Any]:
        from app.repositories.admin import get_setting

        raw = get_setting(f"salesAgent.watermark.{account_id}", None)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = None
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def set_watermark(account_id: str, value: dict[str, Any]) -> None:
        from app.repositories.admin import set_setting

        set_setting(f"salesAgent.watermark.{account_id}", json.dumps(value))

    @staticmethod
    def prune_orphan_watermarks(active_account_ids: tuple[str, ...] = ()) -> int:
        """Delete watermark rows whose Gmail account no longer exists.

        ``GmailAccount`` rows are really deleted when the operator disconnects
        an account, but the watermark lived on in ``AdminSetting`` forever —
        so a reconnect that minted a NEW account id left the old key behind as
        permanent litter, and a re-used id would have resumed from a watermark
        belonging to a mailbox that no longer exists. Idempotent: returns the
        number of rows actually removed (0 on a clean store).

        ``active_account_ids`` are the accounts the CURRENT run is polling and
        are never pruned — they may legitimately not be ``GmailAccount`` rows
        (injected test doubles), and pruning the watermark of a mailbox being
        scanned right now would restart its backlog walk from scratch.
        """
        from app.repositories.gmail_account import GmailAccountRepository

        GmailAccountRepository()._ensure_table()
        prefix = "salesAgent.watermark."
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "key" FROM "AdminSetting" WHERE "key" LIKE %s',
                    (f"{prefix}%",),
                )
                keys = [r[0] for r in cur.fetchall()]
                if not keys:
                    return 0
                cur.execute('SELECT "id" FROM "GmailAccount"')
                known = {r[0] for r in cur.fetchall()} | set(active_account_ids)
                orphans = [k for k in keys if k[len(prefix):] not in known]
                if not orphans:
                    return 0
                cur.execute(
                    'DELETE FROM "AdminSetting" WHERE "key" = ANY(%s)', (orphans,)
                )
                removed = cur.rowcount
            conn.commit()
        return int(removed or 0)

    # ------------------------------------------------------- linkedin cadence
    @staticmethod
    def _linkedin_draft_counts(cur: Any, since: datetime) -> tuple[int, Any]:
        """``(count, lastAt)`` of the week's drafts on an OPEN cursor.

        Reservations count: a slot claimed by a run that is still generating
        its draft is spent, and a second run must see it as spent — that is
        the whole point of :meth:`reserve_linkedin_draft_slot`.
        """
        cur.execute(
            'SELECT COUNT(*), MAX("createdAt") FROM "SalesOutreachLog" '
            'WHERE "channel" = %s AND "outcome" = ANY(%s) AND "createdAt" >= %s',
            ("linkedin_draft", [DRAFT_QUEUED, DRAFT_RESERVED], since),
        )
        count, last_at = cur.fetchone()
        return int(count or 0), last_at

    def linkedin_draft_cadence(self, since: datetime) -> dict[str, Any]:
        """How many LinkedIn drafts were queued since ``since``, and when the
        most recent one was — the two facts the drafting cadence needs.

        Counted straight off the outreach log (the only place drafts land), so
        drafts queued by the admin "generate content" action count towards the
        same weekly budget as the pipeline's own.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                count, last_at = self._linkedin_draft_counts(cur, since)
        return {"count": count, "lastAt": last_at}

    def reserve_linkedin_draft_slot(
        self,
        *,
        since: datetime,
        per_week: int,
        min_spacing_seconds: int = 0,
        campaign_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically claim ONE of the week's LinkedIn draft slots.

        The cadence used to be a check-then-act: count the week's drafts, spend
        ten seconds inside the model, then insert. Two overlapping runs — a
        double-clicked ``/run-now``, two admin tabs, cron overlapping a manual
        trigger — both read the same pre-insert count and both drafted, so the
        advertised cap was not actually enforceable.

        The count and the row that consumes the slot now happen inside ONE
        transaction serialized by a transaction-scoped advisory lock, and the
        reservation is taken BEFORE the model call. The lock is released by the
        commit at the end of this method: no model call ever runs inside a
        database transaction. An honest failure gives the slot straight back
        (:meth:`release_linkedin_draft_slot`); success turns the reservation
        into the real draft row in place (:meth:`finalize_linkedin_draft`), so
        a slot is consumed exactly once.

        Reservations older than :data:`LINKEDIN_RESERVATION_TTL_MINUTES` are
        reclaimed here (idempotently): a process killed mid-draft must not hold
        a weekly slot until the window rolls past it.
        """
        _ensure_sales_tables()
        now = datetime.now(timezone.utc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)", (_LINKEDIN_CADENCE_LOCK,)
                )
                cur.execute(
                    'DELETE FROM "SalesOutreachLog" WHERE "channel" = %s '
                    'AND "outcome" = %s AND "createdAt" < %s',
                    (
                        "linkedin_draft",
                        DRAFT_RESERVED,
                        now - timedelta(minutes=LINKEDIN_RESERVATION_TTL_MINUTES),
                    ),
                )
                reclaimed = int(cur.rowcount or 0)
                count, last_at = self._linkedin_draft_counts(cur, since)
                outcome: dict[str, Any] = {
                    "reserved": False,
                    "reservationId": None,
                    "queuedLast7d": count,
                    "lastAt": last_at,
                    "blockedBy": None,
                    "nextEligibleAt": None,
                    "staleReclaimed": reclaimed,
                }
                if count >= per_week:
                    outcome["blockedBy"] = "cap"
                    conn.commit()
                    return outcome
                if last_at is not None and min_spacing_seconds > 0:
                    last = last_at
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    next_at = last + timedelta(seconds=min_spacing_seconds)
                    if now < next_at:
                        outcome["blockedBy"] = "spacing"
                        outcome["nextEligibleAt"] = next_at
                        conn.commit()
                        return outcome
                reservation_id = new_id()
                cur.execute(
                    'INSERT INTO "SalesOutreachLog" '
                    '("id","campaignId","channel","outcome","detail") '
                    "VALUES (%s,%s,%s,%s,%s)",
                    (
                        reservation_id,
                        campaign_id,
                        "linkedin_draft",
                        DRAFT_RESERVED,
                        "weekly draft slot reserved — generating the draft now",
                    ),
                )
            conn.commit()
        outcome["reserved"] = True
        outcome["reservationId"] = reservation_id
        outcome["queuedLast7d"] = count
        return outcome

    def release_linkedin_draft_slot(self, reservation_id: str) -> bool:
        """Hand an unused slot back. Only ever deletes a row still in the
        ``reserved`` state — a real logged draft is never removed."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "SalesOutreachLog" WHERE "id" = %s '
                    'AND "channel" = %s AND "outcome" = %s',
                    (reservation_id, "linkedin_draft", DRAFT_RESERVED),
                )
                released = int(cur.rowcount or 0)
            conn.commit()
        return released > 0

    def finalize_linkedin_draft(
        self,
        reservation_id: str,
        *,
        subject: str,
        body: str,
        detail: str,
    ) -> dict[str, Any] | None:
        """Turn a reservation into the real queued draft, in place.

        Updating the reserved row (rather than inserting a second one) is what
        makes a slot consumable exactly once. Returns ``None`` when the
        reservation is gone — e.g. reclaimed as stale — so the caller can say
        so instead of pretending a draft was queued.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "SalesOutreachLog" SET "outcome" = %s, "subject" = %s, '
                    '"body" = %s, "detail" = %s '
                    'WHERE "id" = %s AND "outcome" = %s RETURNING *',
                    (
                        DRAFT_QUEUED,
                        subject,
                        body,
                        detail,
                        reservation_id,
                        DRAFT_RESERVED,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None


#: Default campaign templates seeded so the UI is never empty. Copy is honest
#: about Aether's real features and ratified pricing (Free A$0 / 5 runs,
#: Starter A$19/mo, Pro A$39/mo, Power A$69/mo — AUD, GST-inclusive) and is
#: fully editable in the admin UI. ``{{...}}`` placeholders are personalized
#: at send time; the compliance footer is APPENDED SERVER-SIDE and is not part
#: of the template.
DEFAULT_CAMPAIGNS: tuple[tuple[str, str, str], ...] = (
    (
        "Welcome — new signup",
        "welcome",
        "Hi {{name}},\n\n"
        "Thanks for signing up to Aether Career Agent — you now have a Free plan "
        "with 5 agent runs per month.\n\n"
        "The fastest way to see what Aether can do:\n"
        "1. Upload your resume in Resume Studio.\n"
        "2. Set your target role and location in Settings.\n"
        "3. Run Job Discovery — Aether finds and fit-scores real openings, then "
        "tailors your resume to the ones you pick (every claim grounded in your "
        "own resume, never invented).\n\n"
        "If you get stuck or want a walkthrough, just reply to this email.\n\n"
        "Vik\nAether Career Agent — https://aether.srv1356245.hstgr.cloud",
    ),
    (
        "Free → paid nudge",
        "free_to_paid_nudge",
        "Hi {{name}},\n\n"
        "You've been making real use of Aether's Free plan (5 runs/month), and "
        "it looks like you're close to this month's limit.\n\n"
        "If Aether is helping, the Starter plan is A$19/month (GST incl.) for "
        "more runs, and Pro (A$39/mo) adds the deeper reasoning models for "
        "resume tailoring and interview prep. Annual billing saves ~2 months.\n\n"
        "Upgrade any time from Settings → Billing, or reply here with "
        "questions.\n\n"
        "Vik\nAether Career Agent — https://aether.srv1356245.hstgr.cloud/pricing",
    ),
    (
        "Re-engagement check-in",
        "reengagement",
        "Hi {{name}},\n\n"
        "You signed up to Aether Career Agent a while back but haven't run any "
        "agents recently — is there something that got in the way?\n\n"
        "If the setup felt unclear, reply to this email and I'll personally "
        "help you get your resume in and your first tailored application out. "
        "Your Free plan (5 runs/month) is still active.\n\n"
        "Vik\nAether Career Agent — https://aether.srv1356245.hstgr.cloud",
    ),
    (
        "Demo request response",
        "demo_response",
        "Hi {{name}},\n\n"
        "Thanks for the interest in seeing Aether in action — happy to help "
        "right away.\n\n"
        "The quickest option: create a free account at "
        "https://aether.srv1356245.hstgr.cloud (no card needed, 5 agent runs "
        "included) and upload your resume — you'll see live job discovery, fit "
        "scoring and resume tailoring on your own data within minutes.\n\n"
        "If you'd rather a guided walkthrough, reply with a couple of times "
        "that suit you and I'll set up a short call.\n\n"
        "Vik\nAether Career Agent",
    ),
    (
        "LinkedIn draft — product story",
        "linkedin_draft",
        "Draft a LinkedIn post for the founder of Aether Career Agent "
        "(https://aether.srv1356245.hstgr.cloud). Ground rules: only claim features "
        "the product really has — licensed-API job discovery (no scraping), "
        "deterministic fit scoring, resume tailoring with an anti-fabrication "
        "entailment guard, human approval on every job application, Gmail "
        "triage. Pricing: Free A$0 (5 runs/mo), Starter A$19/mo, Pro A$39/mo, "
        "Power A$69/mo (AUD, GST incl.). Do not invent testimonials, user "
        "counts, or results. Tone: honest builder, first person, no hype "
        "cliches. End with one clear call to action to try the free plan.",
    ),
)
