# EMAIL-SETUP — outbound mail (password reset, welcome, Stripe lifecycle)

**Status:** code-complete. The ONE remaining step is an operator input — pick
a provider below, set its env vars, restart the API. Nothing else changes.

## Why this exists

`POST /auth/forgot-password` and `POST /auth/reset-password` are live in
every environment today, and `POST /auth/register` sends the branded
subscriber welcome when a provider is configured. Stripe webhooks send the
same Brand-tab templates (subscription confirmed, payment failed,
cancellation, trial ending) after billing has committed. Without an outbound-email
provider configured, those flows still work end-to-end and are still safe
(anti-enumeration, hashed single-use tokens, rate-limited; registration
and billing never depend on mail) — they just cannot **deliver** the message, so
`/forgot-password` honestly tells the visitor self-service reset isn't
enabled yet. Setting ONE of the two env-var groups below turns delivery
on with no code change and no restart of anything except the API process.

## Pick ONE provider

Set **either** group. If both are set, SMTP wins (deterministic, documented
in `apps/api/app/services/email_sender.py::active_provider`).

### Option A — SMTP (any provider: your existing mailbox, SES, Mailgun, Postmark's SMTP endpoint, etc.)

Add to the repo-root `.env` (same file `start-api.sh` / the API's `env_file`
already load):

```bash
AETHER_SMTP_HOST=smtp.yourprovider.com
AETHER_SMTP_PORT=587
AETHER_SMTP_USER=your-smtp-username
AETHER_SMTP_PASS=your-smtp-password
AETHER_SMTP_FROM=noreply@yourdomain.com   # optional — defaults to AETHER_SMTP_USER
```

Requires STARTTLS on the given port (587 is standard); the connection is
upgraded automatically. Authenticates with `AETHER_SMTP_USER`/`AETHER_SMTP_PASS`
only when both are set (an open-relay SMTP host with no auth is also
supported by leaving them blank).

### Option B — Resend-style HTTPS API

Any provider that speaks the Resend `POST /emails` API shape (a bearer API
key, JSON body with `from`/`to`/`subject`/`text`) — this includes Resend
itself directly:

```bash
AETHER_EMAIL_API_KEY=re_your_api_key
AETHER_EMAIL_FROM=noreply@yourdomain.com
```

Requires a verified sending domain on the provider's side (standard for any
transactional-email service — otherwise the provider itself will reject the
send, which surfaces as a logged, non-fatal failure per below).

## The 5-minute setup

1. Choose Option A or B above.
2. Add the 2–5 env vars to the repo-root `.env`.
3. Restart the API process (`sudo systemctl restart aether-api` or the
   equivalent for this deployment — see `docs/delivery/DEPLOYMENT-RUNBOOK.md`).
4. Verify: `POST /auth/forgot-password {"email": "<a real test account>"}`
   should return `{"ok": true, "emailSendingEnabled": true}` (was `false`
   before). Check the test account's inbox for the reset link.

No database migration, no frontend deploy, no other config — the frontend
already renders whichever state the backend reports.

## What happens with neither configured (current default)

* `POST /auth/forgot-password` still returns `200 {"ok": true,
  "emailSendingEnabled": false}` for every request (anti-enumeration is
  unconditional — this is never skipped).
* A reset token IS still minted and stored (hashed) for a real account, so
  turning on a provider later works retroactively for any link an operator
  might relay manually in the meantime — but nothing is emailed.
* One `INFO`-level log line is written per request:
  `forgot-password: no outbound email provider configured — a reset token
  was minted for userId=<id> but NOT delivered. See
  docs/delivery/EMAIL-SETUP.md to enable self-service reset.`
* `/forgot-password` renders the existing honest copy: "Self-service password
  reset isn't enabled yet" + the operator's support mailto (from
  `AETHER_SUPPORT_EMAIL` — see `.env.example`), so a locked-out user still has
  a path to recovery today.

## What happens with a provider configured but a send fails

(Wrong credentials, provider outage, unverified sending domain, etc.)
`send_email` never raises — the endpoint still returns `200
{"emailSendingEnabled": true}` (that flag reflects **configuration**, not
per-request delivery success) and logs the failure at `WARNING`/`ERROR` with
the provider's own response so the operator can diagnose it
(`apps/api/app/services/email_sender.py::_send_via_smtp` / `_send_via_api`).

**MF-3 correction:** a per-*address* result genuinely cannot be surfaced
without breaking anti-enumeration (an unknown address never even attempts a
send), but a **deployment-level** one can — a provider outage is independent
of whether the requested account exists. `email_sender.delivery_degraded()`
tracks whether the most recently ATTEMPTED send in this process succeeded,
and `POST /auth/forgot-password` returns it as a second response field,
`deliveryDegraded`. Every request (known address or not) reads the same
shared, process-global value at response time, so it never reveals whether
THIS request's address actually triggered a send attempt — anti-enumeration
holds. The frontend uses it: `emailSendingEnabled: true, deliveryDegraded:
true` renders an honest "we're having trouble delivering emails right now"
state instead of the false-success "check your inbox" copy. Provider
correctness should still be verified with a real test send (step 4 above)
rather than trusted blind — `deliveryDegraded` only reflects live traffic,
not a pre-flight check.

## Scope

This closes O-4's password-reset half only. Billing/renewal/trial-ending
notification emails and a welcome/receipt email from Aether itself are
explicitly out of scope here (see the original finding,
`apps/api/app/routers/billing.py::_handle_trial_will_end`) — they can reuse
`app.services.email_sender.send_email` directly once a provider is
configured, but sending them is a separate change.
