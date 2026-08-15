"""Native Sales AI Agent — admin-only growth engine (in-app replacement for
the external Perplexity-based cron).

Pipeline of one run (timer every 30 min, or admin ``POST /run-now``):

1. Feature gate — ``AETHER_SALES_AGENT_ENABLED`` (read at RUN time, default
   off ⇒ honest no-op, nothing recorded). ``AETHER_SALES_AGENT_DRY_RUN``
   (default ON) is the shadow mode: every send is logged verbatim with
   outcome ``dry_run`` and NO email leaves the machine.
2. Inbound polling (watermark-based) of every Gmail account the admin flagged
   ``usedForSalesAgent``: an inbound "unsubscribe" permanently suppresses the
   sender; genuine interest signals become ``SalesLead`` rows (consent type
   ``inbound_signal`` with the real Gmail message id as evidence) and get a
   templated, personalized reply.
3. Existing-user lifecycle: free→paid nudge (near the Free plan's run cap)
   and re-engagement (signed up, inactive ≥ 14 days) — max ONE lifecycle
   email per user per billing cycle, enforced by a DB check.
4. LinkedIn: DRAFTS ONLY (channel ``linkedin_draft``, outcome
   ``draft_queued``). There is deliberately no LinkedIn API code path
   anywhere — the founder posts manually.
5. Daily digest to ``AETHER_ADMIN_EMAIL`` — sent even on zero-activity days,
   with "not observable" stated where a metric genuinely isn't measurable.

HARD GATES honoured before any send (all DB-enforced in
:mod:`app.repositories.sales`): suppression check, one-send-per-thread
idempotency, ratified consent provenance, per-cycle lifecycle rate limit, and
the compliance footer is appended SERVER-SIDE here (never part of an editable
template), satisfying the Spam Act 2003 requirements (sender identification +
functional unsubscribe instruction).

Honesty rules: no metric is ever fabricated — LLM failures are recorded as
outcome ``error`` with the reason, and personalization falls back to the
human-authored template with ``{{name}}`` substitution only (which is not
fabrication) when the LLM is unavailable.

Model routing: the reasoning model is resolved DYNAMICALLY per run —
AgentConfig override (admin user, agentKey ``salesAgent``) → flagship
Anthropic model from the live static catalog (tier ``premium``) →
``get_model("REASONING")``. No model id is hardcoded here.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.db import get_connection
from app.repositories.agent_run import AgentRunRepository
from app.repositories.sales import (
    DuplicateSendError,
    SalesRepository,
)
from app.services.gmail_service import (
    GmailError,
    GmailNotConnectedError,
    GmailService,
    _split_address,
)
from app.services.llm_client import (
    _STATIC_MODEL_CATALOG,
    LLMClient,
    LLMUnavailableError,
    get_model,
)

logger = logging.getLogger("aether.sales_agent")

AGENT_KEY = "salesAgent"

#: Server-side compliance footer (Spam Act 2003: sender identification +
#: functional unsubscribe). Appended to EVERY outbound sales email by
#: :func:`append_compliance_footer` — it is not part of any editable template,
#: so no template edit can strip it.
COMPLIANCE_FOOTER = (
    "\n\n--\n"
    "Aether Career Agent — operated by Vikram Sarkar\n"
    "https://5cb5f0620.abacusai.cloud\n"
    "You received this email because you contacted us or hold an Aether "
    "account. Reply 'unsubscribe' to stop receiving these emails."
)

#: Phrases that permanently suppress a sender (checked case-insensitively in
#: subject + body of inbound mail).
UNSUBSCRIBE_PHRASES = (
    "unsubscribe",
    "opt out",
    "opt-out",
    "stop emailing",
    "remove me from",
)

#: Inbound interest signals → demo_response campaign.
DEMO_PHRASES = ("demo", "walkthrough", "walk-through", "show me", "trial")

#: Inbound interest signals → welcome campaign reply.
INTEREST_PHRASES = (
    "pricing",
    "interested",
    "how does",
    "how do i",
    "question about",
    "sign up",
    "signed up",
    "aether",
)

#: Free plan monthly run cap (mirrors the seeded Free plan) — used only to
#: decide "near the cap", never to report usage.
FREE_PLAN_RUN_CAP = 5


# --------------------------------------------------------------------- flags
def sales_agent_enabled() -> bool:
    """Feature flag, read at RUN time (no restart needed for timer runs)."""
    return os.environ.get("AETHER_SALES_AGENT_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def sales_agent_dry_run() -> bool:
    """Shadow mode flag. DEFAULTS TO ON — going live requires the explicit
    one-line switch ``AETHER_SALES_AGENT_DRY_RUN=false`` in ``.env``."""
    raw = os.environ.get("AETHER_SALES_AGENT_DRY_RUN", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


# ------------------------------------------------------------------- helpers
def append_compliance_footer(body: str) -> str:
    """Server-side footer appender — the compliance gate for EVERY send."""
    body = (body or "").rstrip()
    if COMPLIANCE_FOOTER.strip() in body:
        return body
    return body + COMPLIANCE_FOOTER


def personalize_template(template: str, name: str | None) -> str:
    """Deterministic ``{{name}}`` substitution (human-authored template only —
    never fabrication)."""
    safe_name = (name or "").strip().split(" ")[0] if name else ""
    return (template or "").replace("{{name}}", safe_name or "there")


def resolve_model() -> tuple[str, str]:
    """Resolve the reasoning model DYNAMICALLY: AgentConfig override →
    flagship Anthropic (tier ``premium`` in the live static catalog) →
    ``get_model("REASONING")``. Returns ``(model_id, source)``."""
    admin_id = resolve_admin_user_id()
    if admin_id:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "model" FROM "AgentConfig" '
                    'WHERE "userId" = %s AND "agentKey" = %s',
                    (admin_id, AGENT_KEY),
                )
                row = cur.fetchone()
        if row and row[0]:
            return str(row[0]), "agent_config"
    for entry in _STATIC_MODEL_CATALOG.get("anthropic", []):
        if entry.get("tier") == "premium" and entry.get("reasoning"):
            return str(entry["id"]), "anthropic_flagship"
    return get_model("REASONING"), "reasoning_tier"


def resolve_admin_user_id() -> str | None:
    """The operator account the agent acts as (``AETHER_ADMIN_EMAIL``)."""
    email = (
        os.environ.get("AETHER_ADMIN_EMAIL")
        or os.environ.get("LOGIN_EMAIL")
        or ""
    ).strip()
    if not email:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "User" WHERE LOWER("email") = LOWER(%s) '
                'AND "isAdmin" = true LIMIT 1',
                (email,),
            )
            row = cur.fetchone()
    return row[0] if row else None


def ensure_agent_config(user_id: str) -> None:
    """Seed the admin-only AgentConfig row (model NULL ⇒ dynamic routing)."""
    # "AgentConfig" is created lazily by the agents router; a timer-triggered
    # run (or a fresh test schema) may reach this point before any /agents
    # request has ever run, so make sure the table exists first.
    from app.routers.agents import _ensure_agents_tables

    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "AgentConfig" ("userId","agentKey","enabled") '
                "VALUES (%s,%s,true) "
                'ON CONFLICT ("userId","agentKey") DO NOTHING',
                (user_id, AGENT_KEY),
            )
        conn.commit()


def _default_gmail_factory(user_id: str, account_id: str) -> GmailService:
    return GmailService(user_id, account_id=account_id)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


class SalesAgent:
    """One run of the sales pipeline. All collaborators injectable for tests."""

    def __init__(
        self,
        repo: SalesRepository | None = None,
        gmail_factory: Callable[[str, str], Any] | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.repo = repo or SalesRepository()
        self.gmail_factory = gmail_factory or _default_gmail_factory
        self._llm = llm

    # ---------------------------------------------------------------- LLM
    def _llm_client(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _llm_personalize(
        self, template_body: str, name: str | None, inbound_text: str, model: str
    ) -> tuple[str, str]:
        """Personalize a reply with the LLM; on ANY LLM failure fall back to
        the deterministic template substitution (honest, human-authored copy).
        Returns ``(body, mode)`` where mode is ``llm`` or ``template``."""
        base = personalize_template(template_body, name)
        try:
            out = self._llm_client().complete(
                "sales_agent_reply",
                system=(
                    "You adapt an approved outreach template into a short reply "
                    "to a specific inbound email. HARD RULES: keep every factual "
                    "claim, price and URL from the template EXACTLY as written; "
                    "do not invent features, numbers, testimonials or promises; "
                    "do not add links; no more than 180 words; plain text only; "
                    "do not add a signature beyond the template's."
                ),
                user=(
                    f"Approved template:\n---\n{base}\n---\n"
                    f"Inbound email (reply to this):\n---\n{inbound_text[:2000]}\n---"
                ),
                model=model,
                temperature=0.3,
                fixture_key="sales_reply",
            )
            out = (out or "").strip()
            if out:
                return out, "llm"
        except LLMUnavailableError as exc:
            logger.warning("sales agent: LLM unavailable, template fallback: %s", exc)
        except Exception as exc:  # noqa: BLE001 — never let polish break a run
            logger.warning("sales agent: LLM personalize failed, template fallback: %s", exc)
        return base, "template"

    # ------------------------------------------------------------- inbound
    def _classify_inbound(self, subject: str, text: str) -> str | None:
        blob = f"{subject}\n{text}".lower()
        if _contains_any(blob, UNSUBSCRIBE_PHRASES):
            return "unsubscribe"
        if _contains_any(blob, DEMO_PHRASES):
            return "demo"
        if _contains_any(blob, INTEREST_PHRASES):
            return "interest"
        return None

    def _poll_account(
        self,
        admin_id: str,
        account: dict[str, Any],
        *,
        dry_run: bool,
        model: str,
        result: dict[str, Any],
    ) -> None:
        account_id = account["id"]
        account_email = (account.get("accountEmail") or "").lower()
        wm = self.repo.get_watermark(account_id)
        since_epoch = int(wm.get("lastEpoch") or (time.time() - 86400))
        run_epoch = int(time.time())
        gmail = self.gmail_factory(admin_id, account_id)
        try:
            headers = gmail.list_message_headers(
                query=f"in:inbox after:{since_epoch}", max_results=50
            )
        except (GmailNotConnectedError, GmailError) as exc:
            result["errors"].append(f"inbound poll failed for {account_email}: {exc}")
            return
        for header in headers:
            mid = header.get("id")
            if not mid or self.repo.message_already_processed(mid):
                continue
            result["inboundScanned"] += 1
            sender_name, sender_email = _split_address(header.get("from") or "")
            sender_email = (sender_email or "").lower()
            if not sender_email or "@" not in sender_email:
                continue
            if sender_email == account_email:
                continue  # our own outbound mail
            try:
                msg = gmail.get_message_bodies(mid)
            except GmailError as exc:
                result["errors"].append(f"fetch {mid} failed: {exc}")
                continue
            subject = msg.get("subject") or header.get("subject") or ""
            text = msg.get("text") or ""
            thread_id = msg.get("threadId") or header.get("threadId")
            kind = self._classify_inbound(subject, text)
            if kind is None:
                continue  # not a sales signal — leave untouched, no log row
            if kind == "unsubscribe":
                self._handle_unsubscribe(
                    sender_email, mid, thread_id, subject, result
                )
                continue
            self._handle_interest(
                admin_id,
                account,
                gmail,
                kind=kind,
                sender_email=sender_email,
                sender_name=sender_name,
                message_id=mid,
                thread_id=thread_id,
                subject=subject,
                inbound_text=text,
                dry_run=dry_run,
                model=model,
                result=result,
            )
        self.repo.set_watermark(
            account_id, {"lastEpoch": run_epoch, "lastRunAt": _iso_now()}
        )

    def _handle_unsubscribe(
        self,
        sender_email: str,
        message_id: str,
        thread_id: str | None,
        subject: str,
        result: dict[str, Any],
    ) -> None:
        """Inbound 'unsubscribe' → PERMANENT suppression, no reply ever."""
        self.repo.suppress(
            sender_email, "inbound_unsubscribe_request", source_thread_id=thread_id
        )
        lead = self.repo.get_lead_by_email(sender_email)
        if lead:
            self.repo.set_lead_status(lead["id"], "unsubscribed")
        try:
            self.repo.record_outreach(
                channel="email",
                outcome="unsubscribed",
                lead_id=lead["id"] if lead else None,
                gmail_message_id=message_id,
                gmail_thread_id=thread_id,
                subject=subject,
                recipient=sender_email,
                detail="inbound unsubscribe request — permanently suppressed",
            )
        except DuplicateSendError:
            pass
        result["suppressed"] += 1

    def _handle_interest(
        self,
        admin_id: str,
        account: dict[str, Any],
        gmail: Any,
        *,
        kind: str,
        sender_email: str,
        sender_name: str,
        message_id: str,
        thread_id: str | None,
        subject: str,
        inbound_text: str,
        dry_run: bool,
        model: str,
        result: dict[str, Any],
    ) -> None:
        """Inbound interest → lead (ratified consent) → gated templated reply."""
        try:
            lead = self.repo.create_lead(
                email=sender_email,
                name=sender_name or None,
                consent_type="inbound_signal",
                consent_evidence=f"gmail message {message_id} to {account.get('accountEmail')}",
                source="inbound_email",
                source_thread_id=thread_id or message_id,
            )
        except Exception as exc:  # noqa: BLE001 — consent refusal is a gate, not a crash
            result["errors"].append(f"lead refused for {sender_email}: {exc}")
            return
        if lead.get("status") == "new":
            result["leadsCreated"] += 1
        # --- hard gates, in order -----------------------------------------
        if self.repo.is_suppressed(sender_email):
            self.repo.record_outreach(
                channel="email",
                outcome="blocked",
                lead_id=lead["id"],
                gmail_message_id=message_id,
                gmail_thread_id=thread_id,
                recipient=sender_email,
                detail="suppression list hit — send refused",
            )
            result["blocked"] += 1
            return
        if thread_id and self.repo.thread_already_sent(thread_id):
            return  # DB idempotency: this thread was already really replied to
        ctype = "demo_response" if kind == "demo" else "welcome"
        campaign = self.repo.active_campaign_by_type(ctype) or (
            self.repo.active_campaign_by_type("welcome")
        )
        if campaign is None:
            result["errors"].append(f"no active campaign of type {ctype}")
            return
        body, mode = self._llm_personalize(
            campaign["templateBody"], sender_name, inbound_text, model
        )
        body = append_compliance_footer(body)
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()
        if dry_run:
            self.repo.record_outreach(
                channel="email",
                outcome="dry_run",
                lead_id=lead["id"],
                campaign_id=campaign["id"],
                gmail_message_id=message_id,
                gmail_thread_id=thread_id,
                subject=reply_subject,
                body=body,
                recipient=sender_email,
                detail=f"shadow mode — would send ({mode} personalization)",
            )
            result["dryRunLogged"] += 1
            return
        try:
            sent = gmail.send(
                to=sender_email, subject=reply_subject, body=body,
                thread_id=thread_id,
            )
        except (GmailNotConnectedError, GmailError) as exc:
            self.repo.record_outreach(
                channel="email",
                outcome="error",
                lead_id=lead["id"],
                campaign_id=campaign["id"],
                gmail_thread_id=thread_id,
                recipient=sender_email,
                detail=f"gmail send failed: {exc}",
            )
            result["errors"].append(f"send to {sender_email} failed: {exc}")
            return
        try:
            self.repo.record_outreach(
                channel="email",
                outcome="sent",
                lead_id=lead["id"],
                campaign_id=campaign["id"],
                gmail_message_id=sent.get("id"),
                gmail_thread_id=sent.get("threadId") or thread_id,
                subject=reply_subject,
                body=body,
                recipient=sender_email,
                sent_at=_now(),
                detail=f"{mode} personalization",
            )
        except DuplicateSendError:
            result["errors"].append(
                f"idempotency race on thread {thread_id} — logged once only"
            )
        self.repo.set_lead_status(lead["id"], "contacted")
        result["sent"] += 1

    # ------------------------------------------------------------ lifecycle
    def _lifecycle_candidates(self) -> list[dict[str, Any]]:
        """Existing free-plan users eligible for ONE lifecycle email/cycle.

        Two honest signals straight from production tables:
        * ``free_to_paid_nudge`` — ≥ ``FREE_PLAN_RUN_CAP - 1`` agent runs since
          the current period start (genuinely near the Free cap).
        * ``reengagement`` — account older than 14 days with no agent run in
          the last 14 days.
        """
        sql = '''
            SELECT u."id", u."email", u."name",
                   COALESCE(s."currentPeriodStart", NOW() - interval '30 days')
                       AS cycle_start,
                   COUNT(r."id") FILTER (
                       WHERE r."startedAt" >= COALESCE(
                           s."currentPeriodStart", NOW() - interval '30 days')
                   ) AS runs_this_cycle,
                   MAX(r."startedAt") AS last_run_at,
                   u."createdAt"
            FROM "User" u
            JOIN "Subscription" s ON s."userId" = u."id"
            JOIN "Plan" p ON p."id" = s."planId"
            LEFT JOIN "AgentRun" r ON r."userId" = u."id"
            WHERE LOWER(p."name") = 'free'
              AND u."email" IS NOT NULL
            GROUP BY u."id", u."email", u."name", s."currentPeriodStart",
                     u."createdAt"
        '''
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        out: list[dict[str, Any]] = []
        now = _now()
        for row in rows:
            runs = int(row.get("runs_this_cycle") or 0)
            last_run = row.get("last_run_at")
            created = row.get("createdAt")
            if runs >= FREE_PLAN_RUN_CAP - 1:
                row["campaignType"] = "free_to_paid_nudge"
                out.append(row)
            elif (
                created is not None
                and (now - _as_utc(created)) > timedelta(days=14)
                and (last_run is None or (now - _as_utc(last_run)) > timedelta(days=14))
            ):
                row["campaignType"] = "reengagement"
                out.append(row)
        return out

    def _run_lifecycle(
        self,
        admin_id: str,
        accounts: list[dict[str, Any]],
        *,
        dry_run: bool,
        result: dict[str, Any],
    ) -> None:
        protected = {
            (os.environ.get("AETHER_ADMIN_EMAIL") or "").lower(),
            (os.environ.get("LOGIN_EMAIL") or "").lower(),
            (os.environ.get("AETHER_CRON_EMAIL") or "").lower(),
        } | {(a.get("accountEmail") or "").lower() for a in accounts}
        if not dry_run and not accounts:
            result["errors"].append("lifecycle skipped: no sending account (live mode)")
            return
        gmail = None
        if not dry_run and accounts:
            gmail = self.gmail_factory(admin_id, accounts[0]["id"])
        for cand in self._lifecycle_candidates():
            email = (cand.get("email") or "").lower()
            if not email or email in protected:
                continue
            if self.repo.is_suppressed(email):
                continue
            cycle_start = _as_utc(cand["cycle_start"])
            if self.repo.lifecycle_email_sent_since(email, cycle_start):
                continue  # one lifecycle email per user per billing cycle
            campaign = self.repo.active_campaign_by_type(cand["campaignType"])
            if campaign is None:
                continue
            lead = self.repo.create_lead(
                email=email,
                name=cand.get("name"),
                consent_type="existing_user_lifecycle",
                consent_evidence=f"existing Aether account {cand['id']}",
                source="existing_user",
            )
            body = append_compliance_footer(
                personalize_template(campaign["templateBody"], cand.get("name"))
            )
            subject = campaign["name"]
            if dry_run:
                self.repo.record_outreach(
                    channel="email",
                    outcome="dry_run",
                    lead_id=lead["id"],
                    campaign_id=campaign["id"],
                    subject=subject,
                    body=body,
                    recipient=email,
                    detail="shadow mode — lifecycle email would send",
                )
                result["dryRunLogged"] += 1
                continue
            try:
                sent = gmail.send(to=email, subject=subject, body=body)  # type: ignore[union-attr]
            except (GmailNotConnectedError, GmailError) as exc:
                self.repo.record_outreach(
                    channel="email", outcome="error", lead_id=lead["id"],
                    campaign_id=campaign["id"], recipient=email,
                    detail=f"gmail send failed: {exc}",
                )
                result["errors"].append(f"lifecycle send to {email} failed: {exc}")
                continue
            try:
                self.repo.record_outreach(
                    channel="email",
                    outcome="sent",
                    lead_id=lead["id"],
                    campaign_id=campaign["id"],
                    gmail_message_id=sent.get("id"),
                    gmail_thread_id=sent.get("threadId"),
                    subject=subject,
                    body=body,
                    recipient=email,
                    sent_at=_now(),
                )
            except DuplicateSendError:
                continue
            self.repo.set_lead_status(lead["id"], "contacted")
            result["sent"] += 1

    # -------------------------------------------------------- LinkedIn draft
    def _run_linkedin_draft(
        self, *, model: str, result: dict[str, Any]
    ) -> None:
        """Queue at most one LinkedIn DRAFT per 24 h. Never posts anywhere."""
        campaign = self.repo.active_campaign_by_type("linkedin_draft")
        if campaign is None:
            return
        recent, _total = self.repo.list_outreach(
            channel="linkedin_draft",
            outcome="draft_queued",
            since=_now() - timedelta(hours=24),
            limit=1,
        )
        if recent:
            return
        try:
            post = self._llm_client().complete(
                "sales_agent_linkedin_draft",
                system=(
                    "You draft ONE LinkedIn post. Follow the brief exactly. "
                    "Never invent testimonials, user counts, revenue or "
                    "results. Plain text, no hashtag spam (max 3), under 1300 "
                    "characters."
                ),
                user=campaign["templateBody"],
                model=model,
                temperature=0.7,
                fixture_key="sales_linkedin",
            ).strip()
        except Exception as exc:  # noqa: BLE001 — honest: record the failure, draft nothing
            self.repo.record_outreach(
                channel="linkedin_draft", outcome="error",
                campaign_id=campaign["id"],
                detail=f"LLM unavailable — no draft generated: {exc}",
            )
            result["errors"].append(f"linkedin draft failed: {exc}")
            return
        if not post:
            return
        self.repo.record_outreach(
            channel="linkedin_draft",
            outcome="draft_queued",
            campaign_id=campaign["id"],
            subject="LinkedIn draft (manual posting only)",
            body=post,
            detail="queued for manual review — the agent never posts to LinkedIn",
        )
        result["linkedinDrafts"] += 1

    # --------------------------------------------------------------- digest
    def _run_digest(
        self,
        admin_id: str,
        accounts: list[dict[str, Any]],
        *,
        dry_run: bool,
        result: dict[str, Any],
    ) -> None:
        """Daily founder digest — sent even on zero-activity days (UTC-keyed)."""
        from app.repositories.admin import get_setting, set_setting

        today = _now().strftime("%Y-%m-%d")
        if get_setting("salesAgent.lastDigestDate", None) == today:
            return
        overview = self.repo.overview()
        _rows, today_total = self.repo.list_outreach(
            since=_now().replace(hour=0, minute=0, second=0, microsecond=0), limit=1
        )
        reply_rate = overview.get("replyRate")
        reply_rate_str = (
            f"{reply_rate * 100:.1f}%"
            if reply_rate is not None
            else "not observable (no real sends yet)"
        )
        body = (
            f"Aether Sales Agent — daily digest ({today} UTC)\n\n"
            f"Mode: {'DRY-RUN (shadow)' if dry_run else 'LIVE'}\n"
            f"Signups (total users): {overview['signups']}\n"
            f"Paid conversions (active/trialing/past_due, non-free): "
            f"{overview['paidConversions']}\n"
            f"MRR (AUD, billingInterval-aware): ${overview['mrrAud']:.2f}\n"
            f"Leads: {overview['leads']}\n"
            f"Emails really sent (all time): {overview['emailsSent']}\n"
            f"Dry-run emails logged (all time): {overview['dryRunLogged']}\n"
            f"Reply rate: {reply_rate_str}\n"
            f"LinkedIn drafts queued: {overview['linkedinDraftsQueued']}\n"
            f"Suppression list size: {overview['suppressionCount']}\n"
            f"Outreach log rows today: {today_total}\n\n"
            "All numbers above are live database queries — nothing is estimated."
        )
        recipient = (
            os.environ.get("AETHER_ADMIN_EMAIL")
            or os.environ.get("LOGIN_EMAIL")
            or ""
        ).strip()
        if not recipient:
            result["errors"].append("digest skipped: AETHER_ADMIN_EMAIL not set")
            return
        subject = f"Aether sales digest — {today}"
        if dry_run or not accounts:
            self.repo.record_outreach(
                channel="email",
                outcome="dry_run",
                subject=subject,
                body=body,
                recipient=recipient,
                detail=(
                    "daily digest — shadow mode"
                    if dry_run
                    else "daily digest — no sending account configured, logged only"
                ),
            )
            result["dryRunLogged"] += 1
        else:
            gmail = self.gmail_factory(admin_id, accounts[0]["id"])
            try:
                sent = gmail.send(to=recipient, subject=subject, body=body)
            except (GmailNotConnectedError, GmailError) as exc:
                result["errors"].append(f"digest send failed: {exc}")
                return
            self.repo.record_outreach(
                channel="email",
                outcome="sent",
                gmail_message_id=sent.get("id"),
                gmail_thread_id=sent.get("threadId"),
                subject=subject,
                body=body,
                recipient=recipient,
                sent_at=_now(),
                detail="daily digest",
            )
            result["sent"] += 1
        set_setting("salesAgent.lastDigestDate", today)
        result["digest"] = True

    # ------------------------------------------------------------------ run
    def run(self, trigger: str = "timer", dry_run: bool | None = None) -> dict[str, Any]:
        if not sales_agent_enabled():
            return {
                "ran": False,
                "reason": "AETHER_SALES_AGENT_ENABLED is not true — honest no-op",
            }
        if dry_run is None:
            dry_run = sales_agent_dry_run()
        admin_id = resolve_admin_user_id()
        if admin_id is None:
            return {
                "ran": False,
                "reason": "no admin user matches AETHER_ADMIN_EMAIL — cannot run",
            }
        runs = AgentRunRepository()
        run_row = runs.start(admin_id, AGENT_KEY, {"trigger": trigger, "dryRun": dry_run})
        result: dict[str, Any] = {
            "ran": True,
            "trigger": trigger,
            "dryRun": dry_run,
            "inboundScanned": 0,
            "leadsCreated": 0,
            "sent": 0,
            "dryRunLogged": 0,
            "blocked": 0,
            "suppressed": 0,
            "linkedinDrafts": 0,
            "digest": False,
            "noSendingAccount": False,
            "errors": [],
        }
        try:
            self.repo.seed_default_campaigns()
            ensure_agent_config(admin_id)
            model, model_source = resolve_model()
            result["model"] = model
            result["modelSource"] = model_source
            accounts = self.repo.sales_sending_accounts(admin_id)
            if not accounts:
                result["noSendingAccount"] = True
                logger.info(
                    "sales agent: no Gmail account is flagged usedForSalesAgent — "
                    "inbound polling and live sending honestly skipped"
                )
            for account in accounts:
                self._poll_account(
                    admin_id, account, dry_run=dry_run, model=model, result=result
                )
            self._run_lifecycle(admin_id, accounts, dry_run=dry_run, result=result)
            self._run_linkedin_draft(model=model, result=result)
            self._run_digest(admin_id, accounts, dry_run=dry_run, result=result)
        except Exception as exc:  # noqa: BLE001 — the run row must go terminal
            logger.exception("sales agent run failed")
            result["errors"].append(str(exc))
            runs.finish(run_row["id"], "failed", output=result, error=str(exc))
            return result
        runs.finish(run_row["id"], "completed", output=result)
        return result


def run_sales_agent(
    trigger: str = "timer", dry_run: bool | None = None
) -> dict[str, Any]:
    """Module-level entrypoint used by the systemd timer CLI and /run-now."""
    return SalesAgent().run(trigger=trigger, dry_run=dry_run)


# ------------------------------------------------------------------ time utc
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
