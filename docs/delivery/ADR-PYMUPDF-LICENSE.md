# ADR-PYMUPDF-LICENSE — PyMuPDF (fitz) AGPL question

- **Status:** OPEN — operator decision required. This document BLOCKS licensing sign-off only, not
  functionality; the code runs and ships regardless of which option is chosen.
- **Date:** 2026-08-14
- **Recommendation:** Option A (Artifex commercial license) for launch; keep Option B costed as a
  fallback, not executed now.
- **Prior awareness:** this is not a newly-discovered issue. `apps/api/scripts/
  send_missing_pieces_email.py:70` — an operator-facing draft email — already lists it verbatim
  under "AWAITING YOUR DECISIONS": *"PyMuPDF licensing (AGPL in the resume engine core): buy Artifex
  commercial license (recommended for launch) vs Track-2 migration; brief legal advice suggested."*
  This ADR is the technical grounding for that already-flagged decision, not a new alarm.

---

## 1. Where PyMuPDF is actually used (verified, exhaustive)

Grepping `apps/api` for `import fitz` / `from fitz` finds exactly **three** files:

| File | Line | Use |
|---|---|---|
| `apps/api/app/routers/resumes.py` | 145 | `import fitz` (local import inside `_extract_pdf_text`) — flat text extraction from an uploaded résumé |
| `apps/api/app/services/format_verification.py` | 87 | `import fitz` (local import inside `extract_artifact_text`) — flat text extraction to verify a generated artifact's content |
| `apps/api/app/services/resume_pdf.py` | 35 | `import fitz  # PyMuPDF` (module-level) — in-place editing of the user's base résumé PDF to produce a tailored version |

No other production file in `apps/api` imports `fitz`. This is a small, enumerable surface — not a
pervasive dependency.

### 1.1 The two trivial, swappable sites

`resumes.py:145` and `format_verification.py:87` both follow the same pattern: `fitz.open(stream=
data, filetype="pdf")` then join `page.get_text()` across pages — flat text only, no geometry, no
formatting reconstruction. **These are directly swappable** to `pdfplumber`, which is already a
project dependency (`apps/api/requirements.txt:7`, `apps/api/pyproject.toml:12`,
`pdfplumber>=0.11`) and is already used for exactly this purpose elsewhere in the codebase —
`apps/api/app/services/resume_parser.py` uses `pdfplumber` for résumé-ingestion text/contact-field
extraction. Swapping these two sites is a same-day, low-risk change whenever it happens; it does not
need to wait for this ADR's resolution.

### 1.2 The load-bearing site: `resume_pdf.py`

This is the one site where the AGPL question has real technical weight. The module's own docstring
(`apps/api/app/services/resume_pdf.py:1-27`) states the design rationale directly:

> "The base resume (`assets/resume/Vik_Resume_Final.pdf`) has a bespoke two-column layout: a peach
> title panel and coral section-header icons on a left contact/skills rail, with wrapping
> work-experience bullets on the right. Reproducing that from scratch (Story/reportlab) can never be
> pixel-exact — the embedded `HelveticaNeue` subset, the drawn icons, and the panel geometry are
> impossible to reconstruct faithfully. So a tailored PDF is produced by **editing the original
> document in place** with PyMuPDF instead of rebuilding it... The measurements below... were read
> straight off the source PDF with `page.get_text("dict")`."

This is confirmed in the actual code, not just the docstring. `_detect_blocks()`
(`resume_pdf.py:138-207`) calls `page.get_text("dict")["blocks"]` (line 148) and walks each block's
`lines`/`spans` to recover:
- `x0 = min(s["bbox"][0] for s in spans)` — column position, used to distinguish the left rail from
  the right work-experience column
- `size = max(s["size"] for s in spans)` — font-size band, used to identify which text is a body
  bullet vs. a heading
- `spans[0]["origin"][1]` — the exact baseline y-coordinate, later used to re-insert replacement text
  at the identical position
- `_is_coral(spans[0]["color"])` — RGB-tolerance color matching against the document's bullet-marker
  color, and `"Bold" in span["font"]` for bold-run detection

Then, in `render_tailored_pdf` (`resume_pdf.py`, confirmed at lines 419-429): `page.add_redact_annot(
fitz.Rect(...), fill=(1, 1, 1))` followed by `page.apply_redactions()` — a real content-stream
redaction of the *existing* PDF, not an overpaint — then `fitz.TextWriter(page.rect, ...)` and
`fitz.Font("helv")`/`fitz.Font("hebo")` to re-insert the reworded bullet text at the recovered
baseline/x0, matching the original's bold/regular split. The output is `doc.tobytes(garbage=3,
deflate=True)` — the original document's own bytes, minimally edited, not a reconstruction.

**This is genuinely load-bearing.** The `get_text("dict")` block/line/span geometry is not
incidental — it is how the module locates exactly where to redact and exactly where to reinsert
text so that everything the user did not ask to change (panel, icons, contact rail, skills, section
headers, unchanged bullets) stays byte-for-byte identical to their original file. Losing this
capability is a real product regression, not a library-name swap.

### 1.3 The fallback that already exists (important nuance for Option B's honesty)

`resume_pdf.py` also contains a **second**, independent, `reportlab`-based renderer,
`create_branded_resume_pdf`, which builds a from-scratch two-column branded PDF via
`reportlab.pdfgen.canvas.Canvas` — no `fitz` involvement at all. This is real, currently-shipping
production code, wired into `apps/api/app/routers/resumes.py` as the fallback path used when there
is no matching bundled original (e.g. a user-uploaded résumé rather than the bundled base résumé) or
when the in-place splice fails a completeness check. It is covered by its own test suite (tests
named for the `U2B` render-completeness/document-integrity/two-column/flat-text-boundary checks, plus
`test_mon011_honest_format_integrity.py` — see `docs/delivery/MONITORING-LEDGER.md` MON-011). So
**Option B's rendering half is not a from-scratch build — a permissively-licensed alternative
renderer already exists and already ships** — but only as a *lower-fidelity fallback* for cases
where the surgical in-place edit isn't applicable, not as a full replacement for it. Presenting
Option B as "already partly done" without this caveat would overstate how easy full migration is.

---

## 2. Why this matters: AGPL §13 and this deployment's shape

Aether is a server-side SaaS: users interact with it over the network (`https://
5cb5f0620.abacusai.cloud`), never receiving the PyMuPDF binary or its output PDF bytes in a way that
constitutes distribution of the *software* itself — but AGPL §13 (the "network interaction"
clause) extends copyleft obligations to exactly this shape of deployment: offering the AGPL-licensed
program's functionality to users over a network is treated similarly to distribution, triggering an
obligation to make the complete corresponding source available to those users. This is the reason
PyMuPDF's dual-licensing exists at all (AGPL free tier + Artifex commercial tier) — Artifex Software
Inc. is PyMuPDF's/MuPDF's rights holder and sells commercial licenses specifically for organizations
that cannot or do not want to comply with AGPL §13 in a hosted product. This ADR does not attempt to
give legal advice on whether Aether's current architecture does or does not trigger §13 obligations
in practice — that determination belongs to the "brief legal advice suggested" note already flagged
in `send_missing_pieces_email.py:70` — it records the technical facts needed to make that
determination and to act on it either way.

---

## 3. Option A — Artifex commercial license (recommended for launch)

**What it is:** a paid commercial license from Artifex Software Inc. (the MuPDF/PyMuPDF rights
holder) that permits closed-source, network-hosted use without AGPL §13 obligations.

**Practical purchase path:** artifex.com — Artifex sells MuPDF/PyMuPDF commercial licenses directly;
pricing is quote-based (not published as a fixed self-serve price at the time of writing) and
typically scoped to deployment size/seats. The operator (or whoever holds purchasing authority) would
contact Artifex directly to get a quote scoped to this deployment's actual usage (one server-side
SaaS product, three call-sites as enumerated in §1). **This ADR does not have a verified live price
quote** — obtaining one is the next concrete step if Option A is chosen, and is flagged as
UNVERIFIED here rather than guessed at.

**Why recommended for launch:** zero code change, zero risk to the one genuinely load-bearing
capability (`resume_pdf.py`'s in-place editing), and it resolves the licensing question definitively
rather than partially. The two trivial sites (§1.1) could still be migrated to `pdfplumber`
independently at any time for its own sake (reduced dependency surface) without affecting this
decision either way.

**Trade-off:** ongoing/recurring cost (exact figure unverified, see above), and it does not reduce
the codebase's dependency footprint.

---

## 4. Option B — Track-2 migration to permissive alternatives

**What it would look like, per call-site:**

| Site | Migration target | Honest assessment |
|---|---|---|
| `resumes.py:145` (`_extract_pdf_text`) | `pdfplumber` (already a dependency, already used the same way in `resume_parser.py`) | Trivial. Same-day change, no functional loss. |
| `format_verification.py:87` (`extract_artifact_text`) | `pdfplumber` | Trivial. Same pattern as above. |
| `resume_pdf.py` (`_detect_blocks` + `render_tailored_pdf`) | No drop-in equivalent exists in `pypdf` or `reportlab`. `reportlab` (already a dependency) can only draw new PDFs onto a blank canvas — confirmed by its own use in this same file for `create_branded_resume_pdf` — it cannot edit an existing PDF's content stream, redact a specific text run, or recover precise glyph-level geometry (bbox, baseline, font, color) from an existing document the way `page.get_text("dict")` does. `pypdf` is not currently a dependency anywhere in this repo and, even if added, does not offer equivalent redact-and-reinsert-at-recovered-geometry primitives — it is primarily a merge/split/metadata library, not a layout-recovery one. | **Real regression, not a library swap.** A genuine Option-B migration for this file means abandoning in-place editing entirely and routing every tailored résumé through the existing `create_branded_resume_pdf` reportlab fallback (§1.3) — i.e., every tailored PDF becomes a from-scratch reconstruction instead of a surgical edit of the user's own original bytes. The base résumé's bespoke panel/icon/embedded-font layout (per the module's own docstring) "can never be pixel-exact" when rebuilt this way. |

**Honest cost of Option B:** two of three sites are free/trivial; the third is not a drop-in swap —
it is a product-fidelity downgrade for every tailored résumé generated from the bundled base résumé
template, accepted in exchange for removing the AGPL dependency and its associated licensing cost.
No pypdf/weasyprint/pdfkit spike has been performed to validate whether a closer geometry-recovery
substitute could be built — that would be the concrete next step if Option B were chosen, and is
unverified here (recorded as an open estimation task, not a proven dead end).

---

## 5. Decision

**Recommendation: Option A for launch.** The load-bearing site (`resume_pdf.py`) is a genuine
product-differentiating capability — byte-for-byte-faithful tailoring of a hand-designed résumé
layout — and Option B's cost is a real fidelity regression to that capability, not merely an
engineering-hours cost. Option A resolves the licensing question with no functional risk while a
verified Artifex quote is obtained.

**Keep Option B costed, not executed:** the two trivial sites (§1.1) can be migrated to `pdfplumber`
independently of this decision at low cost/risk, and doing so narrows future exposure regardless of
which option is chosen for the third site. The third site's full Track-2 migration should remain a
priced, ready-to-execute fallback (accept the from-scratch-render fidelity trade-off) in case Option
A's actual quoted price is judged not worth it — but is not recommended to execute preemptively while
Option A is viable.

**This ADR does not itself change any code or purchase any license.** It BLOCKS licensing sign-off
only.

---

## 6. Not verified / open follow-ups

- No live Artifex price quote has been obtained — the next concrete step if Option A is chosen.
- No spike has been performed to test whether `pypdf` (not currently a dependency) or another
  library could partially replicate the redact-and-reinsert geometry workflow better than a full
  fallback-to-reportlab migration would — Option B's cost estimate in §4 is the honest worst case
  (full fallback), not necessarily the floor.
- Whether Aether's specific deployment shape actually triggers AGPL §13 in a way that creates real
  legal exposure (vs. theoretical) was not assessed here — this is the "brief legal advice
  suggested" item from `send_missing_pieces_email.py:70`, deliberately left to counsel, not decided
  in this document.
- `PyMuPDF>=1.24` in `apps/api/requirements.txt:9` / `apps/api/pyproject.toml:13` is a floor
  constraint, not a pinned version — the exact version currently installed/running in production was
  not checked as part of this ADR.
