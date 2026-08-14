# U5b apply-executor fixtures

Provenance for every file in this directory — required by the no-fabrication
mandate (docs/delivery ADR-SEEK-V3 sibling policy: real data only, honestly
labeled when it isn't).

## Real captures (rendered DOM, post-JS)

| File | Source URL | Fetched | Method |
|---|---|---|---|
| `ashby_application_real.html` | `https://jobs.ashbyhq.com/xero/c4019fbe-2f6c-43c8-a310-26dcffdc94db/application` | 2026-08-13 | Playwright chromium headless, `page.content()` after `networkidle` |
| `greenhouse_embed_application_real.html` | `https://boards.greenhouse.io/embed/job_app?for=databricks&token=8569564002` | 2026-08-13 | Playwright chromium headless, `page.content()` after `domcontentloaded` + 3s settle |

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

## Synthetic fixtures (explicitly NOT live captures)

| File | What it represents | Why synthetic |
|---|---|---|
| `captcha_challenge_synthetic.html` | A triggered reCAPTCHA v2 challenge overlay (`#rc-imageselect` iframe, visible challenge frame) | Deliberately forcing a live reCAPTCHA challenge against a real employer's ATS to capture it was judged out of scope for a read-only test-authoring pass and not reliably reproducible on demand. The DOM shape here (a `g-recaptcha` container plus a visible `<iframe title="recaptcha challenge …">`) matches Google's documented reCAPTCHA v2 challenge markup, which is a matter of public record, not a guess about any specific employer's page. |
| `login_wall_synthetic.html` | A "sign in to apply" gate (Workday/Greenhouse-account-gated posting shape) | Same reasoning — this is a commonly-documented ATS pattern (a login form blocking the application form), constructed as a minimal repro rather than captured live. |

Both synthetic files are for pinning the apply-executor's *detection*
contract only (`ManualStepRequired` on CAPTCHA/login-wall) — they are never
asserted to be byte-identical to any specific real site.
