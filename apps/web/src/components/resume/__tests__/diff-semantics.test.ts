/**
 * S-UI B3 — the studio's "changed bullet" rule must be the RENDERER's rule.
 *
 * These tests pin `diff-semantics.ts` against the four load-bearing lines of
 * `apps/api/app/services/resume_pdf.py::render_branded_resume`:
 *
 *   swaps    = {_normalize(before): after for before, after in changes if before and after}
 *   tailored = {_normalize(after) for _before, after in changes if after}
 *   drawn    = swaps.get(_normalize(text), text)
 *   tailored=_normalize(drawn) in tailored or _normalize(text) in swaps
 *
 * If any of these drift, the coral wash on screen stops meaning the coral wash
 * in the downloaded PDF — which is a claim about a file the file does not make
 * about itself. That is the defect class this file exists to catch.
 */
import { describe, expect, it } from "vitest";

import {
  buildRenderDiffIndex,
  changeCounts,
  normalizeLine,
  renderBullet,
  renderBullets,
  segmentRewrite,
} from "../diff-semantics";

describe("normalizeLine — the renderer's _normalize, character for character", () => {
  it("folds the dash family, both quote families and the non-breaking space", () => {
    expect(normalizeLine("AC6–AC19")).toBe("AC6-AC19"); // en dash
    expect(normalizeLine("AC6—AC19")).toBe("AC6-AC19"); // em dash
    expect(normalizeLine("AC6−AC19")).toBe("AC6-AC19"); // minus sign
    expect(normalizeLine("the team’s")).toBe("the team's");
    expect(normalizeLine("“quoted”")).toBe('"quoted"');
    expect(normalizeLine("a b")).toBe("a b");
  });

  it("collapses every run of whitespace, including newlines and tabs", () => {
    expect(normalizeLine("  Directed a\n\tprogram   portfolio  ")).toBe(
      "Directed a program portfolio",
    );
  });
});

describe("renderBullet — the swap + wash decision", () => {
  const changes = [
    { before: "Managed the team.", after: "Led the team of 9.", evidenceRef: "bullet-1" },
    { before: "", after: "Shipped a new onboarding flow.", evidenceRef: "bullet-2" },
  ];

  it("swaps a stored BASELINE bullet for the tailored wording and washes it", () => {
    const out = renderBullet("Managed the team.", buildRenderDiffIndex(changes));
    expect(out.text).toBe("Led the team of 9.");
    expect(out.changed).toBe(true);
    expect(out.replaced).toBe("Managed the team.");
  });

  it("washes a stored TAILORED bullet without swapping it (the version stores the rewrite)", () => {
    const out = renderBullet("Led the team of 9.", buildRenderDiffIndex(changes));
    expect(out.text).toBe("Led the team of 9.");
    expect(out.changed).toBe(true);
    expect(out.replaced).toBeNull();
  });

  it("leaves an untouched bullet alone — no wash, no swap", () => {
    const out = renderBullet("Ran the weekly release train.", buildRenderDiffIndex(changes));
    expect(out.changed).toBe(false);
    expect(out.replaced).toBeNull();
    expect(out.text).toBe("Ran the weekly release train.");
  });

  it("matches through punctuation/whitespace mangling, exactly as the renderer does", () => {
    // The extractor commonly returns an em dash where the diff carried a
    // hyphen, and doubles a space. Raw equality would miss this; _normalize
    // does not, so the PDF washes it — and so must the screen.
    const out = renderBullet("Managed  the team.", buildRenderDiffIndex(changes));
    expect(out.changed).toBe(true);
    expect(out.text).toBe("Led the team of 9.");
  });

  it("treats an addition (no `before`) as tailored wording only", () => {
    const index = buildRenderDiffIndex(changes);
    expect(renderBullet("Shipped a new onboarding flow.", index).changed).toBe(true);
    // ...and it creates no swap key, so nothing is rewritten into it.
    expect(index.swaps.has(normalizeLine("Shipped a new onboarding flow."))).toBe(false);
  });

  it("ignores a change whose `after` is null — there is no tailored wording to draw", () => {
    const index = buildRenderDiffIndex([{ before: "Managed the team.", after: null }]);
    const out = renderBullet("Managed the team.", index);
    expect(out.changed).toBe(false);
    expect(out.text).toBe("Managed the team.");
  });

  it("preserves document order across a whole bullet list", () => {
    const out = renderBullets(
      ["First bullet.", "Managed the team.", "Last bullet."],
      changes,
    );
    expect(out.map((b) => b.text)).toEqual([
      "First bullet.",
      "Led the team of 9.",
      "Last bullet.",
    ]);
    expect(out.map((b) => b.changed)).toEqual([false, true, false]);
  });

  it("returns an empty index for a null/absent change list (no version selected)", () => {
    expect(renderBullets(["A bullet."], null)).toEqual([
      { text: "A bullet.", changed: false, replaced: null },
    ]);
  });
});

describe("changeCounts — rewrites vs additions", () => {
  it("counts a change with a `before` as a rewrite and one without as an addition", () => {
    expect(
      changeCounts([
        { before: "a", after: "A" },
        { before: "b", after: "B" },
        { before: "", after: "new" },
      ]),
    ).toEqual({ rewrites: 2, additions: 1 });
  });

  it("is zero/zero for no changes at all", () => {
    expect(changeCounts([])).toEqual({ rewrites: 0, additions: 0 });
    expect(changeCounts(null)).toEqual({ rewrites: 0, additions: 0 });
  });
});

describe("segmentRewrite — which words are genuinely new", () => {
  it("marks only the words absent from the baseline sentence", () => {
    const segs = segmentRewrite(
      "Managed the team.",
      "Led the team of 9 engineers.",
    );
    const added = segs
      .filter((s) => s.added)
      .map((s) => s.text)
      .join("|");
    expect(added).toContain("Led");
    expect(added).toContain("9 engineers");
    expect(segs.filter((s) => !s.added).map((s) => s.text).join("")).toContain("the team");
  });

  it("reconstructs the tailored sentence exactly when the segments are concatenated", () => {
    const after =
      "Directed a program portfolio with budget stewardship over $5M, leading 5+ squads.";
    const segs = segmentRewrite("Directed a program portfolio valued at over $5M.", after);
    expect(segs.map((s) => s.text).join("")).toBe(after);
  });

  it("does not absolve a repeated word twice (multiset, not set)", () => {
    const segs = segmentRewrite("cost control", "cost cost control");
    // The baseline has ONE "cost"; the second occurrence is genuinely new.
    expect(segs.filter((s) => s.added).map((s) => s.text).join("")).toContain("cost");
  });

  it("marks nothing when the tailored wording only reorders baseline words", () => {
    const segs = segmentRewrite("alpha beta gamma", "gamma beta alpha");
    expect(segs.some((s) => s.added)).toBe(false);
  });

  it("does not wash the space at the boundary between kept and new words", () => {
    const segs = segmentRewrite("the team", "the excellent team");
    const addedText = segs.filter((s) => s.added).map((s) => s.text).join("");
    expect(addedText).toBe("excellent");
  });
});
