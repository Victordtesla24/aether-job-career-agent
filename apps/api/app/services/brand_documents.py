"""Brand-templated admin documents for the Aether Career Job Agent web-app —
invoice template, auto-reply and Stripe-lifecycle email templates — all built
from the SAME design-system tokens as the sales emails (``sales_branding.BRAND``)
so every artefact an admin exports carries one consistent brand.

Grounding rules (STRICT — mirrors the sales agent's honesty contract):

* Every price, plan name and GST figure comes from the LIVE ``Plan`` catalog
  row passed in by the caller (``PlanRepository``) plus the single tax source
  :func:`app.repositories.billing.gst_breakdown`. Nothing is hardcoded or
  invented here.
* Customer-specific fields render as EXPLICIT merge fields
  (``{{customer_name}}``, ``{{invoice_number}}``, …) — these are templates for
  admin use, so merge fields are the correct, honest mechanism. NO fabricated
  sample customers, amounts or dates appear anywhere.
* The product name rendered is ALWAYS "Aether Career Job Agent"; the business
  identity block matches the ratified compliance footer (operated by
  Vikram Sarkar, https://5cb5f0620.abacusai.cloud).
* These are admin-facing documents. They are deliberately NOT wired into the
  Stripe webhook (``routers/billing.py`` documents that no outbound-email
  infrastructure is used by webhooks — a ratified design decision this module
  must not regress).
"""
from __future__ import annotations

import html as _html
from typing import Any, Optional

from app.repositories.billing import gst_breakdown
from app.services.sales_branding import BRAND, brand_logo_url

#: Business identity — identical facts to the sales agent's ratified
#: compliance footer (agents/sales_agent.py COMPLIANCE_FOOTER). Single place.
BUSINESS_NAME = "Aether Career Job Agent"
BUSINESS_OPERATOR = "Operated by Vikram Sarkar"
BUSINESS_URL = "https://5cb5f0620.abacusai.cloud"

#: Registry of document kinds this module can render. ``needsPlan`` documents
#: are rendered against a LIVE Plan catalog row; the others are plan-free.
DOCUMENT_KINDS: dict[str, dict[str, Any]] = {
    "invoice": {
        "title": "Tax invoice template",
        "description": (
            "GST-inclusive AUD tax invoice for a subscription charge. Prices "
            "and GST split come live from the Plan catalog + gst_breakdown; "
            "customer fields are merge fields."
        ),
        "needsPlan": True,
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


def _chrome(title: str, inner_html: str, footnote: str) -> str:
    """Shared branded document chrome — same DS tokens, gradient bars, logo
    and identity block as the sales email wrapper."""
    g = BRAND
    title_html = _esc(title)
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
                  line-height:1.7;color:{g['fg3']};">{BUSINESS_NAME} — {BUSINESS_OPERATOR}<br>
           <a href="{BUSINESS_URL}" style="color:{g['goldAccessible']};
              text-decoration:none;">{BUSINESS_URL}</a></p>
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
    """Inbound auto-reply acknowledgement — no marketing claims, honest
    expectations only."""
    inner = (
        _para(f"Hi {_merge_field('name')},")
        + _para(
            "Thanks for reaching out — your message has been received. "
            "A real person reviews every email; you can expect a reply "
            "within 1–2 business days (Melbourne time)."
        )
        + _para(
            "If your question is about your account or subscription, "
            "including your reference or the email you signed up with "
            "helps us respond faster."
        )
        + _para("— The Aether Career Job Agent team")
    )
    return _chrome(
        "We've received your message",
        inner,
        "You are receiving this one-time acknowledgement because you emailed "
        "us. It is not a marketing email.",
    )


def render_subscription_confirmed(
    plan: dict[str, Any], interval: str = "monthly"
) -> str:
    """Post-checkout confirmation (checkout.session.completed) with the live
    plan price and GST breakdown."""
    amount, per = _plan_price(plan, interval)
    tax = gst_breakdown(amount)
    runs = plan.get("runsPerMonth")
    inner = (
        _para(f"Hi {_merge_field('name')},")
        + _para(
            f"Your <strong>{_esc(plan['name'])}</strong> subscription is "
            f"active. You'll be charged {_money(tax['total'])} {per} "
            f"(AUD, GST-inclusive — GST component {_money(tax['gst'])}), "
            f"which includes {_esc(runs)} agent runs per month."
        )
        + _para(
            "You can manage or cancel your subscription anytime from the "
            f'billing page at <a href="{BUSINESS_URL}" style="color:'
            f'{BRAND["goldAccessible"]};">{BUSINESS_URL}</a>. '
            "A tax invoice is available for every charge."
        )
        + _para("— The Aether Career Job Agent team")
    )
    return _chrome(
        f"Your {plan['name']} subscription is active",
        inner,
        "Transactional notice about a purchase you made — "
        "not a marketing email.",
    )


def render_payment_failed(plan: dict[str, Any], interval: str = "monthly") -> str:
    """Dunning template (invoice.payment_failed) — states the live amount due
    and the fix, nothing else."""
    amount, per = _plan_price(plan, interval)
    inner = (
        _para(f"Hi {_merge_field('name')},")
        + _para(
            f"The renewal charge of {_money(amount)} {per} (AUD, "
            f"GST-inclusive) for your <strong>{_esc(plan['name'])}</strong> "
            "plan didn't go through. This is usually an expired or "
            "declined card."
        )
        + _para(
            "To keep your subscription active, please update your payment "
            f'method from the billing page at <a href="{BUSINESS_URL}" '
            f'style="color:{BRAND["goldAccessible"]};">{BUSINESS_URL}</a>. '
            "Stripe will retry the charge automatically."
        )
        + _para("— The Aether Career Job Agent team")
    )
    return _chrome(
        "Action needed: payment didn't go through",
        inner,
        "Transactional billing notice for your active subscription — "
        "not a marketing email.",
    )


def render_cancellation_confirmed(
    plan: dict[str, Any], interval: str = "monthly"
) -> str:
    """Cancellation confirmation (customer.subscription.deleted) — honest
    paid-until behaviour and the Free-plan fallback, no retention tricks."""
    inner = (
        _para(f"Hi {_merge_field('name')},")
        + _para(
            f"Your <strong>{_esc(plan['name'])}</strong> subscription has "
            "been cancelled — you won't be charged again. Access continues "
            f"until the end of the period you've paid for "
            f"({_merge_field('paid_until')})."
        )
        + _para(
            "After that, your account moves to the Free plan (5 agent runs "
            "per month) and your data stays intact. You can resubscribe "
            f'anytime at <a href="{BUSINESS_URL}" style="color:'
            f'{BRAND["goldAccessible"]};">{BUSINESS_URL}</a>.'
        )
        + _para("— The Aether Career Job Agent team")
    )
    return _chrome(
        "Your subscription is cancelled",
        inner,
        "Transactional confirmation of a cancellation you requested — "
        "not a marketing email.",
    )


# --------------------------------------------------------------- dispatcher
def render_document(
    kind: str, plan: Optional[dict[str, Any]] = None, interval: str = "monthly"
) -> str:
    """Render a registered document kind. Plan-backed kinds REQUIRE a live
    Plan row (the router resolves it via PlanRepository); rendering never
    invents plan data."""
    if kind not in DOCUMENT_KINDS:
        raise KeyError(f"Unknown document kind: {kind}")
    if DOCUMENT_KINDS[kind]["needsPlan"] and plan is None:
        raise ValueError(f"Document kind '{kind}' requires a plan row.")
    if kind == "invoice":
        assert plan is not None
        return render_invoice(plan, interval)
    if kind == "auto_reply":
        return render_auto_reply()
    if kind == "subscription_confirmed":
        assert plan is not None
        return render_subscription_confirmed(plan, interval)
    if kind == "payment_failed":
        assert plan is not None
        return render_payment_failed(plan, interval)
    assert plan is not None
    return render_cancellation_confirmed(plan, interval)
