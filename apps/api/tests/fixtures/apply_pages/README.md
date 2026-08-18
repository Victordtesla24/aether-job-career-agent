# U5b apply-executor fixtures

Provenance for every file in this directory — required by the no-fabrication
mandate (docs/delivery ADR-SEEK-V3 sibling policy: real data only, honestly
labeled when it isn't).

## Real captures (rendered DOM, post-JS)

| File | Source URL | Fetched | Method |
|---|---|---|---|
| `ashby_application_real.html` | `https://jobs.ashbyhq.com/xero/c4019fbe-2f6c-43c8-a310-26dcffdc94db/application` | 2026-08-13 | Playwright chromium headless, `page.content()` after `networkidle` |
| `greenhouse_embed_application_real.html` | `https://boards.greenhouse.io/embed/job_app?for=databricks&token=8569564002` | 2026-08-13 | Playwright chromium headless, `page.content()` after `domcontentloaded` + 3s settle |
| `lever_application_real.html` | `https://jobs.lever.co/whiterabbit/c4333d64-7fcf-4862-9cf0-c6b090ca8ca1/apply` | 2026-08-18 | Playwright chromium headless, `page.content()` after `networkidle` + 2s settle |
| `lever_custom_question_real.html` | `https://jobs.lever.co/theex/80d6ce8b-7736-4433-8d8a-0e1a0d1a3fde/apply` | 2026-08-18 | Playwright chromium headless, `page.content()` after `networkidle` + 2s settle |

Both URLs come from the `Application.sourceUrl` domain histogram produced by
the submission-flow-automation-feasibility scout
(`uat/reports/evidence/agents-uplift/discovery/submission-flow-domain-histogram-2026-08-13.json`)
— Ashby (102/512 applications) and Greenhouse-embedded-on-employer-domain
(99/512) are the #2 and #3 largest direct-ATS channels after Adzuna's own
redirector. These are real, currently-live public job-application pages;
nothing in them was authored or altered by an agent. Both pages are read-only
GETs of a public job posting — no account, no submission, no PII was created
or touched.

Confirmed real field shapes present (useful for U5b test design):

- Ashby: `_systemfield_name` (required text), `_systemfield_email` (required
  email), `_systemfield_resume` (required file upload), a required `tel`
  field, several REQUIRED custom questions with no stable name (UUID-keyed
  radio/checkbox groups — Australian diversity/EEO questions), OPTIONAL
  free-text questions, and a `g-recaptcha-response` widget mounted (present
  but not in a "challenge" state at capture time — see the synthetic CAPTCHA
  fixture below for that state).
- Greenhouse (embed): `first_name`/`last_name`/`email`/`phone` (required),
  `resume`/`cover_letter` file-or-manual-text fields, several
  `question_<id>` custom fields with real `aria-required="true|false"`
  attributes (e.g. `question_36740801002` required, `question_36740798002`
  "LinkedIn Profile" optional), EEO `<select>` fields (gender, veteran
  status, disability status), and the same `g-recaptcha-response` widget.
- Lever: one `li.application-question` block per question. `lever_
  application_real.html` (whiterabbit posting) carries `resume` (file,
  required — the ONLY requiredness signal is the label's `<span
  class="required">✱</span>`, U+2731 HEAVY ASTERISK, not the ASCII `*`),
  `name`/`email` (required, real `required` HTML attribute), `phone`/
  `location`/`org`/`urls[LinkedIn]` (optional), a three-question demographic
  survey keyed `surveysResponses[<surveyId>][responses][field<N>]` (all
  optional on this posting) and a marketing-consent checkbox
  (`consent[marketing]`, paired with an unchecked-by-default hidden decoy
  input of the SAME name — Lever's own "unchecked = 0" pattern). `lever_
  custom_question_real.html` (theex posting) additionally carries TWO
  required employer-authored "card" questions,
  `cards[<cardId>][field0]` (`<select required>`), to pin that distinct
  name/required shape. Both pages mount an hCaptcha widget
  (`#h-captcha` + a hidden `h-captcha-response` input) — present on every
  real Lever `/apply` page captured so far, and NOT solved or bypassed by
  the apply-executor (see `_hcaptcha_widget_mounted` /
  `"captcha_challenge"` in `apply_executor.py`).

## Synthetic fixtures (explicitly NOT live captures)

| File | What it represents | Why synthetic |
|---|---|---|
| `captcha_challenge_synthetic.html` | A triggered reCAPTCHA v2 challenge overlay (`#rc-imageselect` iframe, visible challenge frame) | Deliberately forcing a live reCAPTCHA challenge against a real employer's ATS to capture it was judged out of scope for a read-only test-authoring pass and not reliably reproducible on demand. The DOM shape here (a `g-recaptcha` container plus a visible `<iframe title="recaptcha challenge …">`) matches Google's documented reCAPTCHA v2 challenge markup, which is a matter of public record, not a guess about any specific employer's page. |
| `login_wall_synthetic.html` | A "sign in to apply" gate (Workday/Greenhouse-account-gated posting shape) | Same reasoning — this is a commonly-documented ATS pattern (a login form blocking the application form), constructed as a minimal repro rather than captured live. |
| `greenhouse_employer_microsite_synthetic.html` | The employer-domain `?gh_jid=` page: HTTP 200, **0 `<form>` elements**, application UI is a `div#grnhse_app` mount point, board slug absent from the served HTML | MINIMISED, not invented. The three structural facts above were measured on the live page by a read-only GET on 2026-08-17 (`https://www.databricks.com/company/careers/open-positions/job?gh_jid=8569564002` → 200, 700,675 bytes, 0 forms — see `uat/reports/evidence/models-live/sub-006-gh-canonical/live-probe-2026-08-17.json`). Checking in 700KB of an employer's marketing markup to assert "there is no form here" would be 700KB of noise, so the fixture carries the shape and the evidence file carries the measurement. |

Both CAPTCHA/login-wall synthetic files are for pinning the apply-executor's
*detection* contract only (`ManualStepRequired` on CAPTCHA/login-wall), and
the microsite file pins the apply-channel resolver's Greenhouse verification
GATE (`greenhouse_form_unresolvable`) — none of them is asserted to be
byte-identical to any specific real site.
