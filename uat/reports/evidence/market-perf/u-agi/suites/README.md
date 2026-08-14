# U-AGI P1-B — checked-in suite evidence

Round-1 adversarial review of the P1-B conductor-band slice raised two must-fixes
(`reviews/P1B-REVIEW-ROUND-1-20260814T222512Z.md`). Must-fix #2 was that this campaign
had produced **no on-disk RED-first evidence** — the commit message claimed it, but nothing
was verifiable from disk, unlike this repo's own convention elsewhere
(`uat/reports/evidence/gold-master-v4/suites/GMV4-*-RED-*.txt`).

This directory is that convention, applied. Everything here is raw runner output with a
provenance header; nothing is transcribed or summarised by hand.

> Note on tracking: `uat/reports/evidence/` matches the `evidence/` rule in `.gitignore`, so
> files here are added with `git add -f`, exactly as the 211 already-tracked evidence files were.

## Round 2 — must-fix #1 (`state-err` is not a defined Tailwind token)

| Artifact | What it proves |
| --- | --- |
| `P1B-R2-tailwind-emission-BEFORE-*.txt` | A **real** `tailwindcss` build using the real `apps/web/tailwind.config.ts`, content-scoped to `ConductorBand.tsx`: `state-err` emits **0** rules; `state-ok` / `state-warn` emit 3 each (the sanity control that proves the probe works). The halted/failed banner had no red tint at all. |
| `P1B-R2-statebanner-token-RED-*.txt` | `vitest run conductor-band.test.tsx`, exit **1**, **5 failed / 27 passed** — the new section-8 guards run against the component held at the defect. Fail-before. |
| `P1B-R2-statebanner-token-GREEN-*.txt` | The **same test file**, exit **0**, **32 passed** — only `ConductorBand.tsx:328` changed between the two runs. Pass-after. |
| `P1B-R2-tailwind-emission-AFTER-*.txt` | The same tailwind build after the fix: `state-danger` now emits `border-color: rgb(248 113 113 / 0.4)` and `background-color: rgb(248 113 113 / 0.1)`. The failure is painted, not merely worded. |

The RED and GREEN runs use byte-identical test code; the *only* delta is the one-line class
name. That is what makes the pair evidence rather than assertion.

## Round 2 — merge-induced citation drift (found by the full suite, not by the fix)

`P1B-R2-linkage-drift-repoint-*.txt`. Merging `origin/main@3f707a4` (ORCH-EXEC's
Stop-All async-enqueue guard) inserted 14 lines at `apps/api/app/routers/agents.py:2630`,
pushing two anchors the U-STORY-3a linkage table cites down by exactly 14 lines. The
provenance test caught it — the drift alarm doing its job — and the citation was re-pointed
`3675,3697 → 3689,3711`. Anchor strings unchanged; `discoveryEvidence` deliberately left
frozen (it is the artefact's original discovery-time citation by design). ORCH-EXEC's
`apps/api` change is preserved verbatim — `apps/api` is byte-identical to `origin/main`
on this branch.

## Round 2 — gates on the final tree

| Artifact | Gate |
| --- | --- |
| `P1B-R2-vitest-FULL-*.txt` | Full `apps/web` vitest suite |
| `P1B-R2-typecheck-*.txt` | `tsc --noEmit` |
| `P1B-R2-lint-*.txt` | `next lint --dir src --dir __tests__` |

## Why the new guards are generic

The round-1 defect survived 79 passing tests because every run-state assertion read
`textContent`, and a class naming a token Tailwind does not define keeps the *words* right
while emitting no CSS. The new guards therefore do not pin the string `state-danger`:
they read the `state` palette out of the real `tailwind.config.ts` at test time and require
that every `state-*` utility `ConductorBand.tsx` / `ConductorRail.tsx` can paint with — on
every branch, whether or not a test renders it — names a token that file actually defines.
Any future invented token fails here, whatever it is called.
