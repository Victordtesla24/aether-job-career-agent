# RFMT-5 FIX — outbound résumé renders the user's PRESERVED format

**Branch:** `feat/rfmt5-outbound-format` (worktree `/home/ubuntu/github_repos/aether-wt-rfmt5`, off `origin/main` @ `d4d2c63`)
**Scout input:** `uat/reports/evidence/models-live/resume-format/RFMT5-SCOUT.md`
**Date:** 2026-08-15

---

## 1. HISTORICAL-HONESTY DISCLOSURE (plain statement)

Outbound email/submit résumé (and cover-letter) attachments were rendered branded
due to FastAPI `Query`-default truthiness on in-process route-handler calls; past
sends since U5 went live were branded; fixed from THIS sha forward.

Precisely, and without softening it:

- `services/email_attachments.py` called the ROUTE HANDLER
  `download_resume(resume_id, current_user)` directly, in-process.
- FastAPI resolves `Query` defaults only for a real HTTP request. On a direct
  call, `branded: bool = _BRANDED_OPTIN` received the `Query` OBJECT, which is
  truthy, so `if branded:` took the EXPLICIT-OPT-IN branch.
- Every outbound résumé was therefore rendered as the single-column Aether
  branded template (`create_branded_resume_pdf`) instead of the user's own
  preserved document, and the fidelity report was stamped `branded-optin` —
  a claim that the user had asked to be re-styled, which they had not.

**Cover letter: NOT affected.** `export_cover_letter_pdf(letter_id, current_user)`
declares no defaulted `Query` parameter, so an in-process call is identical to
the plain HTTP export. [VERIFIED — signature read at
`apps/api/app/routers/cover_letters.py:1198-1199`, and pinned by the new
class-level test so adding one later cannot slip through.]

### Affected-send census

| Item | Value | Status |
|---|---|---|
| Outbound code paths that produced a branded résumé | **3** — Gmail approval send (`routers/approvals.py:620`), application email submission (`services/application_submission.py:595`), company-website auto-submit (`workers/apply_sweep.py:545` → `_render_resume_pdf`) | [VERIFIED] code census on this tree |
| Shared choke point | **1** — `services/email_attachments.resolve_email_attachments` | [VERIFIED] |
| Count of real employer-facing transmissions affected | **UNVERIFIED — not determinable from this VM** | scout §7 |

The scout's transmission-count query requires the PRODUCTION database, which is
not reachable from this VM and which this agent did not query. The count is
therefore **not** stated as a number here, rather than guessed. The owner can run
the scout's query (`RFMT5-SCOUT.md` §7) to obtain it.

**Remediation of past sends is the owner's decision. Nothing was resent,
withdrawn or contacted by this agent.**

---

## 2. FIX

Four files, additive, no behaviour change to any HTTP route.

### 2.1 `apps/api/app/routers/resumes.py` — kill the bug class at the handler

Added `_branded_requested(value) -> bool: return value is True`, an exact mirror
of the shipped `_diff_requested` (RFMT-2's proven fix for the identical hazard on
the same handler), and applied it at BOTH render call sites:

- `resume_fidelity()` → `branded=_branded_requested(branded)`
- `download_resume()` → `branded=_branded_requested(branded)`

Any in-process caller — present or future — now gets the preserved render.
`?branded=true` over HTTP is untouched: FastAPI resolves it to a genuine `True`.

### 2.2 `apps/api/app/services/email_attachments.py` — render authority, literal options

The outbound choke point no longer calls the route handler at all. It calls the
render authority with LITERAL arguments:

```python
rendered = _render_resume(resume_id, current_user["id"], branded=False, highlight=False)
```

so no parameter-resolution rule anywhere can decide what an employer opens.
Belt and braces with §2.1 — either layer alone closes the defect.

The attachment is also labelled for what it ACTUALLY is (`rendered.filename`,
`rendered.media_type`) instead of hard-coded `.pdf` / `application/pdf`. This is
a CONSEQUENCE of the fix, not scope creep: while the defect was live the render
was always the branded template and therefore always a PDF, so the hard-coded
name was accidentally correct. A preserved render is whatever the user uploaded —
it can legitimately be a natively rewritten `.docx` or a `.txt` — and shipping
one to an employer named `.pdf` would be a file they cannot open.

### 2.3 `apps/api/app/services/apply_executor.py` — name the portal upload honestly

`playwright_form_submitter` wrote the file it uploads to the employer's portal as
`resume-<id>.pdf` unconditionally. Added `_resume_suffix(data)`, which derives the
extension from the bytes' own magic number (`%PDF-` → `.pdf`, `PK\x03\x04` →
`.docx`, otherwise UTF-8-decodable → `.txt`, empty → `.pdf` as before). Sniffed
from content, never from a caller's label, so the name on disk cannot disagree
with what is in the file. No signature changed; no submitter contract changed.

### 2.4 `apps/api/app/workers/apply_sweep.py` — docstring accuracy only

`_render_resume_pdf`'s docstring now states what it actually produces (the
preserved document, which is not necessarily a PDF) instead of implying the
branded PDF that the defect was producing. No code change.

---

## 3. TESTS — `apps/api/tests/test_rfmt5_outbound_preserved_format.py` (new, 9 tests)

The headline test pins the **bug CLASS**, not the `branded` parameter:

`test_in_process_handlers_behave_as_if_fastapi_resolved_every_query_default`
introspects each in-process-called handler for EVERY parameter defaulted to a
`fastapi.params.Param`, then asserts that calling the handler with no keyword
arguments produces the same document AND the same headers as calling it with
those defaults resolved to their literal values. Any future defaulted parameter
whose truthiness can alter an outbound artifact fails here, whatever it is
called. Both `download_resume` and `export_cover_letter_pdf` are probed, and the
test asserts at least one defaulted parameter still exists so it can never pass
vacuously.

The remaining tests pin the outcome end to end: the `resolve_email_attachments`
résumé equals the `branded=False, highlight=False` render and demonstrably does
NOT equal the branded one; the auto-apply portal upload likewise; no peach/coral
diff wash on any page (RFMT-2 stays closed at the choke point); the emailed cover
letter equals the plain HTTP export; `?branded=true` still returns
`branded-optin` / `formatPreserved: false`; a plain download and its fidelity
report still agree on `pdf-in-place-splice`.

**Comparison method.** Renders are compared by DOCUMENT fingerprint (per page:
geometry, text, drawn-shape count), not raw bytes. [VERIFIED on this tree by
probe] two consecutive `_render_resume(..., branded=False)` calls differ in
exactly 59 bytes, all inside `trailer <</ID[<…><…>]` — PyMuPDF stamps a fresh
random `/ID` on every write, and its serialised length varies, so even
`Content-Length` moves. Byte equality would have been a flaky test, not a
stronger one; `Content-Length` is excluded from the header comparison for the
same reason.

### RED → GREEN

`pytest-fail-before.txt` — the FINAL test file against UNMODIFIED `origin/main`
source (fix stashed): **5 failed, 4 passed**, including

```
AssertionError: an in-process download reported 'branded-optin' — the Query
object's truthiness sent it down the branded-opt-in branch
```

`pytest-pass-after-rfmt5-rfmt2.txt` — same file with the fix: **all green**,
run twice for stability.

---

## 4. GATES

| Gate | Command | Result |
|---|---|---|
| New RFMT-5 suite | `scripts/run-tests.sh tests/test_rfmt5_outbound_preserved_format.py` | **9 passed** (x2 runs) |
| Résumé/format suites (21 files incl. RFMT-2, U2b x9, MON-011, MV studio/grounding) | see §5 | **236 passed, 1 failed** — the 1 failure is PRE-EXISTING, see §4.1 |
| Email / submission / approval / U5 suites (22 files) | see §5 | **303 passed, 0 failed** |
| ruff (CI invocation) | `ruff check app/ tests/` | **All checks passed** |
| mypy (CI invocation) | `mypy app/ --ignore-missing-imports` | **Success: no issues found in 163 source files** |
| vitest | not run — **no web files touched** (diff is 4 backend files + 1 test) | n/a |

### 4.1 The one red, and why it is not ours

`tests/test_mv_resume_studio.py::TestTailorApprovalIsReal::test_tailored_version_is_pending_until_approved`
— `assert 409 == 200`.

[VERIFIED-WITH-FRESH-EVIDENCE] It fails IDENTICALLY with this branch's source
stashed, i.e. on unmodified `origin/main` @ `d4d2c63`, run in isolation:
`1 failed, 10 passed` — artifact `pytest-preexisting-red-on-origin-main.txt`.
Pre-existing on main; not introduced or influenced by this change. Not fixed here
— out of this slice's scope and it belongs to whoever owns the tailor-approval
path.

### 4.2 Artifacts in this directory

| File | What it proves |
|---|---|
| `pytest-fail-before.txt` | RED: final test file vs unmodified `origin/main` source — 5 failed, 4 passed |
| `pytest-pass-after-rfmt5-rfmt2.txt` | GREEN: same file + RFMT-2 suite with the fix |
| `pytest-preexisting-red-on-origin-main.txt` | The one red in §4.1 is pre-existing on `origin/main` |
| `ruff-check.txt` | `ruff check app/ tests/` — All checks passed |
| `mypy.txt` | `mypy app/ --ignore-missing-imports` — no issues, 163 files |

---

## 5. REPRODUCTION

```bash
cd /home/ubuntu/github_repos/aether-wt-rfmt5

# the slice
flock /tmp/aether-pytest.lock scripts/run-tests.sh \
  tests/test_rfmt5_outbound_preserved_format.py -q -p no:randomly

# résumé / format regression
flock /tmp/aether-pytest.lock scripts/run-tests.sh \
  tests/test_rfmt5_outbound_preserved_format.py tests/test_rfmt2_clean_download.py \
  tests/test_resume_format_preserve.py tests/test_resume_ingest.py tests/test_resume_upload.py \
  tests/test_resume_pdf_layout.py tests/test_resume_parser.py tests/test_resume_bullet_extraction.py \
  tests/test_u2b_baseline_merge.py tests/test_u2b_document_integrity.py \
  tests/test_u2b_fidelity_coherence.py tests/test_u2b_fidelity_verification.py \
  tests/test_u2b_flat_text_boundary.py tests/test_u2b_format_engine.py \
  tests/test_u2b_format_engine_paths.py tests/test_u2b_live_two_column_document.py \
  tests/test_u2b_render_completeness.py tests/test_u2b_repair_census.py \
  tests/test_mon011_honest_format_integrity.py tests/test_mv_resume_studio.py \
  tests/test_mv_resume_grounding.py -q -p no:randomly

# email / submission regression
flock /tmp/aether-pytest.lock scripts/run-tests.sh \
  tests/test_email_send_gate.py tests/test_email_sender.py tests/test_email_agent.py \
  tests/test_emails.py tests/test_approvals.py tests/test_approval_modal.py \
  tests/test_approvals_delete.py tests/test_u5_invariant_sweep.py tests/test_u5_email_retry.py \
  tests/test_u5_stale_approval_and_batch.py tests/test_u5_applications_read_manual_step.py \
  tests/test_u5_close_apply_sweep_status_endpoint.py tests/test_u5a_apply_channel_resolver.py \
  tests/test_u5b_apply_executor.py tests/test_u5d2_dry_run_e2e.py \
  tests/test_u5d2_per_card_submission.py tests/test_u5d2_agent_reaches_u5_engine.py \
  tests/test_u5d3_answer_bank_capture.py tests/test_u5d3_answer_bank_api.py \
  tests/test_u5d3_answer_bank_matching.py tests/test_gm2_s15_stored_signoff_leak_paths.py \
  tests/test_cover_letter_studio.py -q -p no:randomly

cd apps/api && ruff check app/ tests/ && mypy app/ --ignore-missing-imports
```

---

## 6. INVARIANTS HELD

- No real employer send, submission or outreach was performed anywhere in this work.
- No production database was read or written.
- Additive only: no column, table, endpoint, response field or function signature
  removed or renamed; no DDL of any kind.
- No format / completeness / U2b CRITICAL guard weakened; the tailored-wording
  splice is untouched; `_render_resume`'s branches are unchanged.
- No silent fallback and no silent substitution introduced — the branded template
  remains reachable only by explicit opt-in and is still reported honestly.
- No secret read, printed, or committed.
