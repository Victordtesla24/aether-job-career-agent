"""Brand-templated artefacts for the Aether Career Job Agent web-app.

The admin Brand tab (``/admin/sales-agent`` → Brand) is the single catalogue.
Every kind listed in ``DOCUMENT_KINDS`` is previewable there. Transactional
Aether-owned email kinds render through ``email_branding`` (bulletproof, no
images). Sales outreach renders through
``sales_branding.render_sales_outreach_html`` (Gmail HTML, raster mark).
Print artefacts (invoice, business card, generated documents) use the same
obsidian-and-gilt tokens. ``allowsImg`` on a kind is an explicit, tested
allow-list — never a silent exemption.

Grounding rules (STRICT — mirrors the sales agent's honesty contract):

* Every price, plan name and GST figure comes from the LIVE ``Plan`` catalog
  row passed in by the caller (``PlanRepository``) plus the single tax source
  :func:`app.repositories.billing.gst_breakdown`. Nothing is hardcoded or
  invented here.
* Customer-specific fields render as EXPLICIT merge fields
  (``{{customer_name}}``, ``{{invoice_number}}``, …) — these are templates for
  admin use, so merge fields are the correct, honest mechanism. NO fabricated
  sample customers, amounts or dates appear anywhere.
* The product name rendered on print/admin chrome is ALWAYS "Aether Career
  Job Agent"; transactional email chrome uses ``email_branding.PRODUCT_NAME``.
* Stripe lifecycle kinds ARE wired into ``routers/billing.py`` after the
  webhook transaction commits. A send failure must not roll back billing.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Optional

from app.repositories.billing import gst_breakdown
from app.services.sales_branding import BRAND, brand_logo_url
from app.services.stripe_gateway import app_base_url

#: Business identity — identical facts to the sales agent's ratified
#: compliance footer (agents/sales_agent.py COMPLIANCE_FOOTER). Single place.
BUSINESS_NAME = "Aether Career Job Agent"
BUSINESS_OPERATOR = "Operated by Vikram Sarkar"
_UNSUBSCRIBE_URL = re.compile(
    r"https://[^\s<>\"']+/[^\s<>\"，。]*unsubscribe[^\s<>\"，。]*",
    re.IGNORECASE,
)

#: Registry of document kinds this module can render. ``needsPlan`` documents
#: are rendered against a LIVE Plan catalog row; the others are plan-free.
DOCUMENT_KINDS: dict[str, dict[str, Any]] = {
    "invoice": {
        "title": "Tax invoice template",
        "description": (
            "GST-inclusive AUD tax invoice for a subscription charge. Prices "
            "and GST split come live from the Plan catalog + gst_breakdown; "
            "customer fields are merge fields. Print chrome includes the "
            "brand mark."
        ),
        "needsPlan": True,
        "allowsImg": True,
    },
    "auto_reply": {
        "title": "Inbound auto-reply email",
        "description": (
            "Acknowledgement sent manually by an admin when someone emails "
            "in — sets response expectations, no marketing claims."
        ),
        "needsPlan": False,
    },
    "subscription_confirmed": {
        "title": "Subscription confirmed (Stripe checkout.session.completed)",
        "description": (
            "Post-checkout confirmation template with the live plan price "
            "and GST breakdown for the chosen interval."
        ),
        "needsPlan": True,
    },
    "payment_failed": {
        "title": "Payment failed (Stripe invoice.payment_failed)",
        "description": (
            "Dunning template for a failed renewal charge — states the live "
            "amount due and how to update the card."
        ),
        "needsPlan": True,
    },
    "cancellation_confirmed": {
        "title": "Cancellation confirmed (Stripe customer.subscription.deleted)",
        "description": (
            "Confirms a cancellation, states the paid-until behaviour and "
            "the Free-plan fallback (5 runs/month) — no retention tricks."
        ),
        "needsPlan": True,
    },
    "subscriber_welcome": {
        "title": "Subscriber welcome email",
        "description": (
            "Onboarding email sent when a subscriber creates an account. "
            "Plan name and monthly run quota come live from the Plan catalog; "
            "the recipient name is a merge field. This is the same renderer "
            "the signup path uses."
        ),
        "needsPlan": True,
    },
    "password_reset": {
        "title": "Password reset email",
        "description": (
            "Self-service password-reset email. The live forgot-password "
            "path uses this same renderer; the reset link is a merge field."
        ),
        "needsPlan": False,
    },
    "founder_digest": {
        "title": "Founder daily digest",
        "description": (
            "Internal sales-pipeline digest sent to the operator. Preview "
            "shows merge fields; live numbers come from the sales-agent run."
        ),
        "needsPlan": False,
    },
    "notification_digest": {
        "title": "Notification digest email",
        "description": (
            "Gilt chrome wrapped around the user-approved digest body "
            "(status updates and new matches) at execute time."
        ),
        "needsPlan": False,
    },
    "trial_ending": {
        "title": "Trial ending (Stripe customer.subscription.trial_will_end)",
        "description": (
            "Reminder that a trial is about to convert to a paid charge. "
            "Amount comes live from the Plan catalog."
        ),
        "needsPlan": True,
    },
    "sales_outreach": {
        "title": "Sales outreach email",
        "description": (
            "Gmail HTML chrome for Aether-owned prospect mail: inbound "
            "replies, welcome, free-to-paid nudge, re-engagement and demo "
            "response. Preview is the live wrapper with merge fields; the "
            "compliance footer is the server-side Spam Act text. Campaign "
            "copy itself is edited under Campaigns."
        ),
        "needsPlan": False,
        "allowsImg": True,
    },
    "ops_alert": {
        "title": "Operator systemd alert",
        "description": (
            "Obsidian-and-gilt alert sent when a production systemd unit "
            "fails. Preview uses merge fields; scripts/ops_alert.sh calls "
            "the same builder with the live unit name and log excerpt."
        ),
        "needsPlan": False,
    },
    "business_card": {
        "title": "Business card",
        "description": (
            "Obsidian-and-gilt calling card. Name, role, email and phone "
            "are merge fields; the mark and URL are the live brand."
        ),
        "needsPlan": False,
    },
    "document": {
        "title": "Branded document",
        "description": (
            "Generated markdown/HTML report chrome — the same wrapper "
            "agents use for Aether-owned documentation."
        ),
        "needsPlan": False,
    },
}


# ------------------------------------------------------------------ helpers
def _esc(value: Any) -> str:
    return _html.escape(str(value if value is not None else ""))


def _merge_field(name: str) -> str:
    """Render a merge field VISIBLY as a merge field (honest template token,
    never a fabricated sample value)."""
    g = BRAND
    return (
        f'<span style="font-family:{g["bodyFont"]};font-size:13px;'
        f'color:{g["goldAccessible"]};background-color:{g["surface2"]};'
        f'border:1px dashed {g["hairline"]};border-radius:3px;'
        f'padding:1px 6px;white-space:nowrap;">{{{{{name}}}}}</span>'
    )


def _plan_price(plan: dict[str, Any], interval: str) -> tuple[float, str]:
    """Live (amount, per-interval label) from a Plan catalog row. Annual
    falls back to monthly when the plan has no annual price (e.g. Free)."""
    if interval == "annual" and plan.get("priceAudAnnual") is not None:
        return float(plan["priceAudAnnual"]), "per year"
    return float(plan.get("priceAudMonthly") or 0), "per month"


def _render_footer_override(footer: str) -> str:
    """Escape editable footer text while preserving a clickable opt-out URL."""
    escaped = _esc(footer).replace("\n", "<br>")

    def link(match: re.Match[str]) -> str:
        url = match.group(0)
        return f'<a href="{url}" style="color:{BRAND["goldAccessible"]};">{url}</a>'

    return _UNSUBSCRIBE_URL.sub(link, escaped)


def _chrome(
    title: str, inner_html: str, footnote: str, footer_override: Optional[str] = None
) -> str:
    """Shared branded document chrome — same DS tokens, gradient bars, logo
    and identity block as the sales email wrapper."""
    g = BRAND
    title_html = _esc(title)
    product_url = app_base_url()
    footer_html = (
        _render_footer_override(footer_override)
        if footer_override is not None
        else (
            f'{BUSINESS_NAME} — {BUSINESS_OPERATOR}<br>\n'
            f'           <a href="{product_url}" '
            f'style="color:{g["goldAccessible"]};\n'
            f'              text-decoration:none;">{product_url}</a>'
        )
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_html}</title>
</head>
<body style="margin:0;padding:0;background-color:{g['bg']};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:{g['bg']};padding:0;margin:0;">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0"
           style="max-width:640px;width:100%;">
      <tr><td style="height:3px;line-height:3px;font-size:0;
                     background:{g['gold']};
                     background-image:{g['gradient']};">&nbsp;</td></tr>
      <tr><td style="background-color:{g['surface']};padding:28px 40px 18px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};" align="center">
        <img src="{brand_logo_url()}" alt="{BUSINESS_NAME}" width="72"
             style="display:block;width:72px;height:auto;margin:0 auto 12px auto;">
        <div style="font-family:{g['bodyFont']};font-size:11px;font-weight:700;
                    letter-spacing:.25em;text-transform:uppercase;
                    color:{g['goldAccessible']};">{BUSINESS_NAME}</div>
      </td></tr>
      <tr><td style="background-color:{g['surface']};padding:0 40px 8px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};" align="center">
        <h1 style="margin:0 0 8px 0;font-family:{g['displayFont']};
                   font-size:24px;font-weight:700;line-height:1.3;
                   color:{g['fg1']};">{title_html}</h1>
        <div style="width:48px;height:1px;margin:12px auto 0 auto;font-size:0;
                    line-height:1px;background-color:{g['hairline']};">&nbsp;</div>
      </td></tr>
      <tr><td style="background-color:{g['surface']};padding:24px 40px 32px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};" align="left">
{inner_html}
      </td></tr>
      <tr><td style="background-color:{g['footerBg']};padding:20px 40px 24px 40px;
                     border-left:1px solid {g['cardBorder']};
                     border-right:1px solid {g['cardBorder']};
                     border-top:1px solid {g['hairline']};" align="center">
        <p style="margin:0 0 6px 0;font-family:{g['bodyFont']};font-size:12px;
                  line-height:1.7;color:{g['fg3']};">{footer_html}</p>
        <p style="margin:0;font-family:{g['bodyFont']};font-size:11px;
                  line-height:1.6;color:{g['fg3']};">{_esc(footnote)}</p>
      </td></tr>
      <tr><td style="height:2px;line-height:2px;font-size:0;
                     background:{g['goldDark']};
                     background-image:{g['gradient']};">&nbsp;</td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _para(text_html: str, size: str = "15px", color: Optional[str] = None) -> str:
    g = BRAND
    return (
        f'<p style="margin:0 0 16px 0;font-family:{g["bodyFont"]};'
        f'font-size:{size};line-height:1.7;color:{color or g["fg2"]};">'
        f"{text_html}</p>"
    )


def _money(amount: float) -> str:
    return f"A${amount:,.2f}"


# ---------------------------------------------------------------- documents
def render_invoice(plan: dict[str, Any], interval: str = "monthly") -> str:
    """GST-inclusive AUD tax-invoice template for a live Plan row. GST split
    comes from :func:`gst_breakdown` — the single tax source of truth."""
    g = BRAND
    amount, per = _plan_price(plan, interval)
    tax = gst_breakdown(amount)
    stripe_price = (
        plan.get("stripePriceIdAnnual")
        if interval == "annual" and plan.get("stripePriceIdAnnual")
        else plan.get("stripePriceIdMonthly")
    )
    label = f'{_esc(plan["name"])} plan — {per}'
    row_style = (
        f'font-family:{g["bodyFont"]};font-size:14px;color:{g["fg2"]};'
        f'padding:10px 0;border-bottom:1px solid {g["hairline"]};'
    )
    stripe_meta = ""
    if plan.get("stripeProductId") or stripe_price:
        stripe_meta = _para(
            "Stripe product: "
            f'<span style="color:{g["fg3"]};">{_esc(plan.get("stripeProductId") or "—")}</span>'
            " &nbsp;·&nbsp; Stripe price: "
            f'<span style="color:{g["fg3"]};">{_esc(stripe_price or "—")}</span>',
            size="12px",
        )
    inner = f"""
{_para(f'Invoice number: {_merge_field("invoice_number")} &nbsp;·&nbsp; '
       f'Invoice date: {_merge_field("invoice_date")}', size='13px')}
{_para(f'Billed to: {_merge_field("customer_name")} '
       f'&lt;{_merge_field("customer_email")}&gt;', size='13px')}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:8px 0 20px 0;">
  <tr>
    <td style="{row_style}">{label}</td>
    <td style="{row_style}" align="right">{_money(amount)}</td>
  </tr>
  <tr>
    <td style="{row_style}">Net (excl. GST)</td>
    <td style="{row_style}" align="right">{_money(tax["net"])}</td>
  </tr>
  <tr>
    <td style="{row_style}">GST (10%, included)</td>
    <td style="{row_style}" align="right">{_money(tax["gst"])}</td>
  </tr>
  <tr>
    <td style="font-family:{g['bodyFont']};font-size:15px;font-weight:700;
               color:{g['fg1']};padding:12px 0;">Total (AUD, GST-inclusive)</td>
    <td style="font-family:{g['bodyFont']};font-size:15px;font-weight:700;
               color:{g['goldAccessible']};padding:12px 0;"
        align="right">{_money(tax['total'])}</td>
  </tr>
</table>
{_para('All prices are in Australian dollars and include GST. '
       'This invoice covers the subscription period '
       + _merge_field('period_start') + ' to ' + _merge_field('period_end') + '.',
       size='13px')}
{stripe_meta}
"""
    return _chrome(
        f"Tax invoice — {plan['name']} plan",
        inner,
        "Payment processed securely by Stripe. "
        "Merge fields ({{…}}) are filled per customer at issue time.",
    )


def render_auto_reply() -> str:
    """Inbound auto-reply acknowledgement — gilt email chrome, no images."""
    from app.services.email_branding import build_auto_reply_bodies

    html, _text = build_auto_reply_bodies(
        "Hi {{name}},\n\n"
        "Thanks for reaching out — your message has been received. "
        "A real person reviews every email; you can expect a reply "
        "within 1–2 business days (Melbourne time).\n\n"
        "If your question is about your account or subscription, "
        "including your reference or the email you signed up with "
        "helps us respond faster.\n\n"
        "— The Aether CareerAI Agent team"
    )
    return html


def render_subscription_confirmed(
    plan: dict[str, Any], interval: str = "monthly"
) -> str:
    """Post-checkout confirmation — same HTML the Stripe webhook sends."""
    from app.services.email_branding import build_subscription_confirmed_bodies
    from app.services.stripe_gateway import app_base_url

    html, _text = build_subscription_confirmed_bodies(
        "{{name}}", plan, interval, f"{app_base_url()}/dashboard"
    )
    return html


def render_payment_failed(plan: dict[str, Any], interval: str = "monthly") -> str:
    """Dunning template — same HTML the Stripe webhook sends."""
    from app.services.email_branding import build_payment_failed_bodies
    from app.services.stripe_gateway import app_base_url

    html, _text = build_payment_failed_bodies(
        "{{name}}", plan, interval, f"{app_base_url()}/dashboard/settings"
    )
    return html


def render_cancellation_confirmed(
    plan: dict[str, Any], interval: str = "monthly"
) -> str:
    """Cancellation confirmation — same HTML the Stripe webhook sends."""
    from app.services.email_branding import build_cancellation_confirmed_bodies
    from app.services.stripe_gateway import app_base_url

    _ = interval
    html, _text = build_cancellation_confirmed_bodies(
        "{{name}}", plan, "{{paid_until}}", f"{app_base_url()}/pricing"
    )
    return html


def render_trial_ending(plan: dict[str, Any], interval: str = "monthly") -> str:
    """Trial-ending reminder — same HTML the Stripe webhook sends."""
    from app.services.email_branding import build_trial_ending_bodies
    from app.services.stripe_gateway import app_base_url

    html, _text = build_trial_ending_bodies(
        "{{name}}", plan, interval, f"{app_base_url()}/dashboard/settings"
    )
    return html


def render_subscriber_welcome(
    plan: dict[str, Any], interval: str = "monthly"
) -> str:
    """New-account welcome — the same HTML the signup path sends.

    Uses ``email_branding`` (bulletproof, no images) rather than the admin
    document chrome, so the operator preview matches the subscriber inbox.
    """
    from app.services.email_branding import build_subscriber_welcome_bodies
    from app.services.stripe_gateway import app_base_url

    _ = interval
    html, _text = build_subscriber_welcome_bodies(
        name="{{name}}",
        plan_name=str(plan["name"]),
        runs_per_month=int(plan["runsPerMonth"]),
        dashboard_url=f"{app_base_url()}/dashboard",
    )
    return html


def render_password_reset() -> str:
    """Same HTML ``POST /auth/forgot-password`` sends."""
    from app.services.password_reset import build_reset_email_bodies

    _text, html = build_reset_email_bodies("{{reset_url}}")
    return html


def render_founder_digest() -> str:
    from app.services.email_branding import build_founder_digest_preview_bodies

    html, _text = build_founder_digest_preview_bodies()
    return html


def render_notification_digest() -> str:
    from app.services.email_branding import build_notification_digest_bodies

    html, _text = build_notification_digest_bodies(
        "Your Aether digest", "{{digest_body}}"
    )
    return html


def render_business_card() -> str:
    from app.services.brand_artifacts import render_business_card_preview_html

    return render_business_card_preview_html()


def render_document_artefact() -> str:
    from app.services.branded_artefacts import render_branded_markdown_html

    return render_branded_markdown_html("{{title}}", "{{body}}")


def render_sales_outreach() -> str:
    """Same HTML the sales agent hands to Gmail as ``html_body``.

    Merge fields stay visible. The compliance footer is the live server-side
    footer, not a placeholder — that text is not editable.
    """
    from app.agents.sales_agent import append_compliance_footer
    from app.services.sales_branding import render_sales_outreach_html

    body = append_compliance_footer("Hi {{name}},\n\n{{body}}")
    return render_sales_outreach_html("{{subject}}", body)


def render_ops_alert() -> str:
    """Same HTML ``scripts/ops_alert.sh`` posts to Resend."""
    from app.services.email_branding import build_ops_alert_bodies

    html, _text = build_ops_alert_bodies(
        unit="{{unit}}",
        timestamp="{{timestamp}}",
        log_excerpt="{{log_excerpt}}",
        log_path="{{log_path}}",
    )
    return html


# --------------------------------------------------------------- dispatcher
def render_document(
    kind: str,
    plan: Optional[dict[str, Any]] = None,
    interval: str = "monthly",
    editable_template: Optional[dict[str, Any]] = None,
) -> str:
    """Render a registered document kind. Plan-backed kinds REQUIRE a live
    Plan row (the router resolves it via PlanRepository); rendering never
    invents plan data."""
    if kind not in DOCUMENT_KINDS:
        raise KeyError(f"Unknown document kind: {kind}")
    if DOCUMENT_KINDS[kind]["needsPlan"] and plan is None:
        raise ValueError(f"Document kind '{kind}' requires a plan row.")
    if editable_template is not None:
        if kind != "auto_reply":
            raise ValueError("Only auto_reply supports persistent template overrides.")
        from app.services.email_branding import build_auto_reply_bodies

        html, _text = build_auto_reply_bodies(
            editable_template["body"],
            footnote=editable_template["footnote"],
            footer=editable_template["footer"],
        )
        return html
    dispatch = {
        "invoice": lambda: render_invoice(plan, interval),  # type: ignore[arg-type]
        "auto_reply": render_auto_reply,
        "subscription_confirmed": lambda: render_subscription_confirmed(
            plan, interval  # type: ignore[arg-type]
        ),
        "payment_failed": lambda: render_payment_failed(plan, interval),  # type: ignore[arg-type]
        "cancellation_confirmed": lambda: render_cancellation_confirmed(
            plan, interval  # type: ignore[arg-type]
        ),
        "subscriber_welcome": lambda: render_subscriber_welcome(plan, interval),  # type: ignore[arg-type]
        "password_reset": render_password_reset,
        "founder_digest": render_founder_digest,
        "notification_digest": render_notification_digest,
        "trial_ending": lambda: render_trial_ending(plan, interval),  # type: ignore[arg-type]
        "business_card": render_business_card,
        "document": render_document_artefact,
        "sales_outreach": render_sales_outreach,
        "ops_alert": render_ops_alert,
    }
    return dispatch[kind]()
