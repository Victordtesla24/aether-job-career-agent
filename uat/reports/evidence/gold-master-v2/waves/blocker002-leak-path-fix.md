# BLOCKER-002 — closing the two OPEN leak paths for contaminated stored letters (d1 + d2)

**Scope: CODE ONLY.** No production DB write, no remediation of the 8 contaminated rows (that data half
needs risk-officer approval and is explicitly out of scope), no deploy, no push.

- **Run:** GOLD-MASTER-V2 §15, fixer-hard
- **Input:** `uat/reports/evidence/gold-master-v2/waves/blocker002-remediation-plan.md` (§4 option (d), §5
  verification recipe) and `blocker002-live-pdf-probe-20260731T1126Z.txt`
- **Window:** 2026-07-31T11:32:21Z → 2026-07-31T11:49:52Z
- **Branch/base:** `481cc44` (`docs(gm-v2): ORCH-CORR-005 + refusal ordering verified 68/68`)
- **Artifact:** this file

Claim tags: **[VERIFIED]** = command run THIS session, output + timestamp given. **[INFERRED]** = reasoned
from verified facts. **[DEVIATION]** = differs from the brief, with the reason.

---

## 1. What was wrong (restated from the plan, re-confirmed by code read)

All three shipped placeholder-signer guards test the **live profile name at call time**; not one inspects
the **stored letter body**:

| # | path | file:line (pre-fix) | guarded on |
|---|---|---|---|
| 1 | generation | `apps/api/app/agents/cover_letter_agent.py:1302` | `user["name"]` |
| 2 | refine | `apps/api/app/routers/cover_letters.py:692` | `current_user["name"]` |
| 3 | PDF export | `apps/api/app/routers/cover_letters.py:1000` | `current_user["name"]` |
| 4 | **apply-copy** | `apps/api/app/routers/jobs.py:487-500` (+ the promote `UPDATE` at `:504-523`) | **nothing** |

Consequence, verified live on production 2026-07-31T11:26:25Z by the plan: correcting `User.name` at
01:12:27Z flipped `GET /cover-letters/{id}/pdf` from 422 to **200** for 8 already-contaminated letters —
clean live letterhead (`Vikram Deshpande`) over a contaminated stored sign-off
(`GAP-P7-DEF-B Probe 1785452243543`), served as
`attachment; filename="cover-letter-<company>.pdf"`.

Two fixture variants exist (`…1785452243543` ×5, `…1784823962960` ×3). **Nothing in this fix is keyed to a
single literal** — detection is the shared structural rule, and both variants are in the test matrix.

---

## 2. The fix

### 2.1 Shared detection — one implementation, sign-off scoped

`apps/api/app/agents/cover_letter_agent.py` (after `_looks_like_placeholder_name`):

- `_SIGNOFF_CLOSINGS` — derived from the **existing** `_CLOSINGS` tuple that
  `strip_letter_scaffolding` already uses. No second list of closings.
- `_closing_line_signer(line)` — `None` when the line is not a closing line; the inline signer
  (`"Sincerely, Ada Lovelace"`) or `""` when the signer is on the next line (`compose_letter`'s shape).
- `stored_signoff_name(letter_text) -> str` — scans **upward from the end** so the letter's final sign-off
  wins; returns `""` when there is no closing block at all.
- `stored_letter_has_placeholder_signer(letter_text) -> bool` — `stored_signoff_name(...)` fed into the
  **existing** `_looks_like_placeholder_name`. §13.1 respected: **no second detection implementation** —
  the name rule (whole-token `test`/`probe`/`gap` + 8-digit run, as tightened in `1f6f6a5`) is untouched.

### 2.2 d1 — PDF export and refine inspect the stored sign-off

- `apps/api/app/routers/cover_letters.py:1027` (export) and `:705` (refine): after the existing
  profile-name check, refuse 422 when `stored_letter_has_placeholder_signer(letter["coverLetter"])`.
- The refine check sits **before any LLM call**, inside `_refine_cover_letter_body`, so `_record_run`'s
  `except HTTPException` still finishes the run as failed and **refunds the reserved quota**.
- The existing profile-name guards are **unchanged** — the new check is additive.

### 2.3 d2 — the apply-copy path

`apps/api/app/routers/jobs.py`: new `_guard_apply_cover_letter_source(user_id, job_id,
reuse_application_id)` called from `submit_application_for_job` immediately after the existing
"a cover letter is required" gate and **before either write shape**, so a refusal leaves the job
un-applied with no row created or promoted. `POST /jobs/{id}/apply` and `SubmissionAgent` share this
single write function, so both are covered by construction.

**Correction to the plan's §3.6 mechanism [VERIFIED by code read + test]:** the plan names the
`INSERT … SELECT` at `jobs.py:487-500` as the vector. In practice that branch is **unreachable** for a
draft copy: it only runs when `existing_application is None`, but the gate above it requires a non-empty
**draft** `Application` to exist for the job — and `_existing_application` returns the newest row of *any*
status, so whenever a draft exists the code takes `application_id = existing_application[0]` and reaches
the **in-place promote `UPDATE` at `:504-523`** instead. Proof from the pre-existing suite:
`test_gmv2_wh_apply_contract.py::test_success_creates_application_and_advances_job_together` asserts
`_application_count_for_job(job_id) == 1` after applying to a job that had one draft — i.e. no new row was
inserted; the draft was promoted. **The live leak is therefore the promote `UPDATE`, not the
`INSERT … SELECT`.** The guard checks **both** candidate bodies (the row that would be promoted *and* the
row the `INSERT … SELECT` would pick), so the conclusion does not depend on which analysis is right.

---

## 3. Decisions

### 3.1 Sign-off-only scoping — `signoff_only_scoping = true`

**Decision: only the sign-off line is inspected; body prose is never inspected.**

The guard now runs over **model-generated prose**, not a short profile field. A whole-body scan would
refuse a legitimate letter whose prose says "I led **testing** for three squads", "closed the capability
**gap**", or quotes an 8-digit figure — every one of those trips `_looks_like_placeholder_name`'s raw
signals. That is the exact false-positive class commit `1f6f6a5` already had to repair once (Probert,
Testa, Testard, Probst), and denying a paying user their own letters is a worse defect than the one being
fixed. §1.4 of the plan verifies the scoping is also **sufficient**: in all 8 production rows the fixture
appears exactly once, as the final line after the valediction, never in prose, with no stored letterhead.

Two guards keep prose out:
1. a line is a closing line only when it **is** a closing (`Sincerely` / `Regards.`) or a closing followed
   immediately by a comma (`Sincerely, <name>`) — not merely a line containing one;
2. the extracted signer must be **≤ 8 whitespace tokens**, so a sentence that happens to open with a
   closing word ("Best, I want to add that our test suite passed.") is never read as an identity.

**Residual false negative (accepted, documented in code):** a stored body with no valediction, or with a
>8-token sign-off line, yields no signer and is not inspected. Those bodies are covered on the *write*
side by the generation-time guard. Abstaining is the honest boundary — the alternative (guessing at the
last prose line) is exactly the false-positive machine this scoping exists to avoid.

### 3.2 Apply-copy behaviour — **REFUSE (422)**, never substitute

`apply_copy_behaviour = refuse_with_422`.

Justification:
- **Substituting the newest CLEAN draft would be a silent substitution.** The Studio and
  `GET /cover-letters` show the **newest** draft; submitting a different, older body than the one the user
  is looking at changes the content of a real job application without telling them — on the single most
  consequential action in the product. My standing rules forbid silent fallbacks/substitutions.
- **The plan's cheaper form — a `WHERE` predicate on the copy source — is actively unsafe.** With the
  contaminated draft excluded and no clean draft left, the `INSERT … SELECT` matches **zero rows**, yet
  the caller still returns an `applicationId` and `update_status(job_id, "applied")` still runs: an
  applied job with an `applicationId` pointing at an Application that was never inserted. A silent
  data-integrity failure traded for a silent substitution.
- Refusing is consistent with the two gates already on this path (missing tailored resume → 422, missing
  cover letter → 422) and with the honest-failure contract
  `test_gmv2_wh_apply_contract.py::TestApplyIsAtomic` pins: on refusal the job stays un-applied and no
  Application row is created or promoted (asserted by the new tests).
- The user's remedy is in their hands and is stated in the message: regenerate the letter.

### 3.3 [DEVIATION] The 422 detail string

The brief's acceptance criterion says the export "must return 422 with `PLACEHOLDER_SIGNER_DETAIL`". The
**status, the guard, the shared detection rule and the reachability are exactly as specified**, but the
detail string is a new constant:

```
STORED_PLACEHOLDER_SIGNER_DETAIL = (
    "This letter's stored sign-off is a placeholder or test value, not your "
    "real name — regenerate the letter before exporting, refining or "
    "applying with it."
)
```

Reason: `PLACEHOLDER_SIGNER_DETAIL` reads *"Your profile name looks like a placeholder or test value …
set your real name in Settings"*. In this scenario the profile name is **already correct** — that is the
whole point of the finding — so reusing it sends the user to Settings to fix a name that is not broken,
a dead end that leaves them unable to clear the block. The recognisable phrase
`"placeholder or test value"` is kept **identical** in both constants so a QA grep on it still matches
either message. If the orchestrator wants the literal shared constant instead, it is a three-line revert
(`STORED_PLACEHOLDER_SIGNER_DETAIL` → `PLACEHOLDER_SIGNER_DETAIL` at the three raise sites) plus the
`"sign-off" in detail` assertions in the new tests. **Flagged for an orchestrator ruling; not decided
unilaterally as final.**

---

## 4. False-positive test matrix

Every seeded letter in the leak-path suite carries this prose **in the clean cases too** — a bare `test`
token, a bare `gap` token and an 8-digit run — so any body-wide scan fails the clean-path tests:

> "I led testing for three squads and closed the capability gap between platform and product. In one gap
> analysis I ran a test of the ingestion pipeline that processed 12345678 events without a dropped record."

| # | case | expected | where |
|---|---|---|---|
| 1 | sign-off `Jordan Rivera`, hazardous prose | accept | `…false_positives.py::test_clean_stored_letter_is_not_refused` |
| 2 | sign-off `MV Tester` (a real person named Tester) | accept | same |
| 3 | sign-off `Sarah Probert` | accept | same |
| 4 | sign-off `Jean-Baptiste Testard` under `Kind regards,` | accept | same |
| 5 | sign-off `Marco Testa` under `Best regards,` | accept | same |
| 6 | sign-off `田中健一` (non-Latin script) | accept | same |
| 7 | inline `Sincerely, Jordan Rivera` | accept | same |
| 8 | prose line `Best, I want to add that our test suite passed and the gap closed.` | **not read as a signer** | `test_prose_line_opening_with_a_closing_word_is_not_read_as_a_signer` |
| 9 | body with no valediction at all | abstain (`""`) | `test_letter_with_no_signoff_yields_no_signer` |
| 10 | empty / whitespace-only / missing body | abstain | `test_empty_and_missing_bodies_are_safe` |
| 11 | scoping asserted directly: extracted signer == `Jordan Rivera` while the body contains `test`/`gap` | scoping | `test_only_the_signoff_line_is_inspected_never_the_prose` |
| 12 | PDF export of a clean letter with hazardous prose | **HTTP 200**, `%PDF`, attachment | `…leak_paths.py::test_pdf_export_still_serves_a_clean_letter` |
| 13 | PDF export signed `MV Tester` / `Sarah Probert` | HTTP 200 | `test_pdf_export_serves_a_letter_signed_by_a_real_person` |
| 14 | refine of a cleanly generated letter (real replay generation, end-to-end) | HTTP 200 | `test_refine_still_works_on_a_clean_generated_letter` |
| 15 | apply with a clean draft (hazardous prose) | HTTP 200, job applied, one `submitted` row | `test_apply_still_works_for_a_clean_draft` |
| 16 | apply with a draft signed `Sarah Probert` | HTTP 200 | `test_apply_still_works_for_a_draft_signed_by_a_real_person` |

True-positive matrix (both variants, so nothing is keyed to one literal): sign-off
`GAP-P7-DEF-B Probe 1785452243543` and `…1784823962960` under `Sincerely,`, under `Kind regards,`, and
inline; plus `QA Probe` and `probe_user_20260731093000`; each asserted refused at the unit level and at
HTTP level on all three paths. The pre-existing profile-name matrices in
`test_gm2_s15_placeholder_name_false_positives.py` and `test_wb1_blocker002_placeholder_signer_name.py`
are unchanged and still green.

---

## 5. Verbatim evidence

### 5.1 FAIL BEFORE — `2026-07-31T11:39:02Z`

`flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gm2_s15_stored_signoff_leak_paths.py -v"`
(the false-positive file could not even be collected before the fix:
`ImportError: cannot import name 'stored_letter_has_placeholder_signer'`, run at
`2026-07-31T11:38:55Z`).

```
E       AssertionError: PDF export must refuse a letter whose STORED sign-off is a placeholder/test artefact ('GAP-P7-DEF-B Probe 1785452243543') even though the live profile name is clean — this is the exact HTTP 200 verified on production 2026-07-31T11:26:25Z. Got 200.
E       assert 200 == 422
E        +  where 200 = <Response [200 OK]>.status_code
```

```
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_pdf_export_refuses_contaminated_stored_signoff[GAP-P7-DEF-B Probe 1785452243543]
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_pdf_export_refuses_contaminated_stored_signoff[GAP-P7-DEF-B Probe 1784823962960]
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_refine_refuses_contaminated_stored_letter[GAP-P7-DEF-B Probe 1785452243543]
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_refine_refuses_contaminated_stored_letter[GAP-P7-DEF-B Probe 1784823962960]
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_apply_refuses_to_submit_a_contaminated_draft[GAP-P7-DEF-B Probe 1785452243543]
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_apply_refuses_to_submit_a_contaminated_draft[GAP-P7-DEF-B Probe 1784823962960]
FAILED tests/test_gm2_s15_stored_signoff_leak_paths.py::test_apply_refuses_rather_than_silently_substituting_an_older_clean_draft
=================== 7 failed, 6 passed, 8 warnings in 32.12s ===================
```

The 6 that passed pre-fix are the false-positive regression guards (clean PDF export, real-name sign-offs,
clean apply, clean refine) — they exist to prove the fix does not break the legitimate path, so passing
before **and** after is the correct outcome for them.

Full log: `/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/b002fix/before-leakpaths.txt`

### 5.2 PASS AFTER — new + extended tests, `2026-07-31T11:41:22Z`

`flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gm2_s15_stored_signoff_leak_paths.py tests/test_gm2_s15_placeholder_name_false_positives.py -v"`

```
======================= 42 passed, 10 warnings in 31.95s =======================
```

### 5.3 PASS AFTER — full required regression list, `2026-07-31T11:46:41Z → 11:49:52Z`

`flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gm2_s15_placeholder_name_false_positives.py tests/test_wb1_blocker002_placeholder_signer_name.py tests/test_cover_letter_agent.py tests/test_gap_p6_cov2.py tests/test_gap_p6_cover_fabrication.py tests/test_mv_cluster_a_cover_letter.py tests/test_mv_resume_grounding.py tests/test_gm2_email_agents_findings.py tests/test_gmv2_wh_apply_contract.py tests/test_gm2_s15_stored_signoff_leak_paths.py -q"`

```
[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=aether_test — safe to proceed.
........................................................................ [ 68%]
.................................                                        [100%]
105 passed, 18 warnings in 189.49s (0:03:09)
```

**105 passed, 0 failed, 0 errors. No regressions.** Full log:
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/b002fix/after-regression-final.txt`

### 5.4 Lint / import integrity — `2026-07-31T11:46Z`

```
$ python3 -m ruff check app/routers/cover_letters.py app/routers/jobs.py app/agents/cover_letter_agent.py \
      tests/test_gm2_s15_stored_signoff_leak_paths.py tests/test_gm2_s15_placeholder_name_false_positives.py
All checks passed!
$ python3 -c "import app.agents.submission_agent, app.workers.tasks; print('deep import OK')"
deep import OK
```
(`jobs.py` now imports from `app.agents.cover_letter_agent`, and `app.agents.submission_agent` imports
from `app.routers.jobs` — the deep import above proves no cycle.)

---

## 6. The `Administrator` sign-offs (7 letters) — assessment, NOT fixed

**Verdict: out of scope for this guard; a separate finding. [INFERRED, high confidence]**

- **It is not detected today and should not be.** `Administrator` has no bare `test`/`probe`/`gap` token
  and no 8-digit run, so `_looks_like_placeholder_name` correctly ignores it. It is not a test artefact —
  it is a real, if generic, display name. The product itself treats it as a legitimate profile name:
  `tests/test_mv_cluster_a_cover_letter.py` pins MV-cover-letter-studio-001 with `name == "Administrator"`
  and `cover_letter_agent.py:889-892` carries dedicated logic for it as an ordinary common noun. Adding
  it as a literal to the placeholder rule would be exactly the "key on a single literal" mistake §1.2 of
  the plan warns against, in the other direction.
- **Catching it would require a fundamentally different and far more dangerous rule** — "the stored
  sign-off must equal the current `User.name`". That rule has a large, legitimate false-positive
  population: anyone who changes their legal name (marriage, deed poll), signs with a preferred or
  professional form (`Vik Deshpande` vs `Vikram Deshpande`), or adds/removes a middle name would have
  **every historical letter** blocked from export. Letters are point-in-time documents; a name-drift
  mismatch is information, not a defect.
- **Recommended disposition:** file separately as a *stale display name* data finding for the same user
  (same remediation family as §4(b): a targeted sign-off `UPDATE`, risk-officer approved), and — if a
  forward-path product change is wanted — a **display-time, non-blocking advisory** ("this letter is
  signed *Administrator*, which is not your current profile name — regenerate?"), never a hard 422. The
  deeper forward fix is at onboarding: do not let a generic seeded display name reach a customer-facing
  document in the first place.
- **Not touched by this commit**, by design: the new guard leaves all 7 `Administrator` letters
  exportable, refinable and applyable exactly as before.

---

## 7. Residual risks

1. **[DEVIATION §3.3] the detail string** is `STORED_PLACEHOLDER_SIGNER_DETAIL`, not
   `PLACEHOLDER_SIGNER_DETAIL`. Status (422), guard reachability and detection are per spec. Awaiting an
   orchestrator ruling; trivially revertible.
2. **Documented false negatives of the sign-off scoping:** a stored body with no valediction, or a
   sign-off line longer than 8 tokens, is not inspected. Deliberate — the alternative reintroduces prose
   false positives. Write-path generation guards still cover new letters.
3. **`_looks_like_placeholder_name`'s own residual FP** is unchanged and inherited: a real human whose
   *bare* first or last name is exactly `Test`, `Probe` or `Gap` would be refused. Unchanged by this
   commit (documented at `cover_letter_agent.py:1093-1095`); no such name observed in real data.
4. **The 8 contaminated rows are still contaminated.** This commit makes them **unreachable through
   export, refine and apply**; it does **not** clean them. The list endpoint `GET /api/cover-letters`
   still returns their bodies, so the Studio still *displays* the contaminated sign-off on screen — that
   surface was not in this task's scope (it is a read of `Application.coverLetter`, remediable only by the
   d3 data fix or a `apps/web/**` change, both owned elsewhere).
5. **Newly blocked users are blocked until they regenerate.** Anyone holding a contaminated letter now
   gets a 422 on export/refine/apply. That is the intended honest refusal (a blocked export beats a
   contaminated submission), but it means the d3 data remediation is now on the critical path for that
   single account's usability, not merely for tidiness.
6. **Not deployed.** Everything above is verified against the test suite on `aether_test`, not against
   production. The §5.5 production check (`…/pdf` → 422 with the block message) can only be re-run after a
   deploy, which is out of scope here.
7. **Only the 10 named test files were run** (per the brief's explicit instruction). Files outside that
   list that touch these paths — notably `tests/test_cover_letter_studio.py` (refine + PDF export) — were
   not executed this session. The new suite covers the same three behaviours (clean export 200, clean
   refine 200, clean apply 200) as its own regression guard, but a full-suite run before merge is still
   the honest gate.

---

## 8. Files changed

| file | change |
|---|---|
| `apps/api/app/agents/cover_letter_agent.py` | `+STORED_PLACEHOLDER_SIGNER_DETAIL`, `_SIGNOFF_CLOSINGS`, `_MAX_SIGNOFF_NAME_TOKENS`, `_closing_line_signer`, `stored_signoff_name`, `stored_letter_has_placeholder_signer`. `_looks_like_placeholder_name` **unchanged**. |
| `apps/api/app/routers/cover_letters.py` | stored-sign-off 422 in `_refine_cover_letter_body` and `export_cover_letter_pdf`; both existing profile-name guards unchanged. |
| `apps/api/app/routers/jobs.py` | `+_guard_apply_cover_letter_source`, called in `submit_application_for_job` before either write shape. |
| `apps/api/tests/test_gm2_s15_placeholder_name_false_positives.py` | +18 sign-off scoping / FP / TP cases. |
| `apps/api/tests/test_gm2_s15_stored_signoff_leak_paths.py` | **new** — 13 HTTP-level tests across the three paths, both fixture variants. |

No prohibited patterns: no `Math.random`, no hardcoded metrics, no placeholder strings, no TODO stubs, no
`@ts-ignore`/`eslint-disable`, no broad `any`, no `--no-verify`, no secrets, no test weakened or deleted.
No files outside the owned set were modified (`analytics.py`, `applications.py`, `approvals.py`,
`repositories/approval.py`, `approval_service.py`, `stage_transitions.py`, `apps/web/**` untouched).
