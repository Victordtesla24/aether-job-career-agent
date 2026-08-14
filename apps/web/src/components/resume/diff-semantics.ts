/**
 * The renderer's OWN diff semantics, mirrored for the screen.
 *
 * WHY THIS EXISTS. Resume Studio's job is to show a subscriber what their
 * tailored résumé actually became. The document is drawn by
 * `apps/api/app/services/resume_pdf.py::create_branded_resume_pdf`, which
 * decides which bullets COUNT AS REWORDED with two rules and a tolerant text
 * normaliser — and, in its diff PREVIEW variant (`highlight=True`, RFMT-2),
 * washes exactly those bullets in coral `#FF6B35`. The employer-facing
 * download carries no wash at all; what the screen mirrors is the "which lines
 * changed" decision, which is identical in both variants:
 *
 *   swaps    = { normalize(before): after   for (before, after) in changes if before and after }
 *   tailored = { normalize(after)            for (_before, after) in changes if after }
 *   drawn    = swaps.get(normalize(text), text)
 *   washed   = normalize(drawn) in tailored or normalize(text) in swaps
 *
 * If the screen invented its own idea of "changed" (say, index-pairing the
 * diff against the bullet list, or matching on raw string equality), the
 * highlighted lines on screen and the washed lines in the PDF would drift
 * apart the first time punctuation or whitespace differed — and the studio
 * would be making a claim about the file that the file does not make about
 * itself. So this module reproduces those four lines exactly, and nothing
 * else. It derives no scores, invents no changes, and returns "not changed"
 * whenever the renderer would not have washed the line.
 *
 * Pure data — no React, no fetch. Ported from Python, kept deliberately
 * literal so the two can be diffed by eye.
 */

/** `_PUNCT_FOLD` from resume_pdf.py — the exact same character map. */
const PUNCT_FOLD: Record<string, string> = {
  "‐": "-", // ‐ hyphen
  "‑": "-", // ‑ non-breaking hyphen
  "‒": "-", // ‒ figure dash
  "–": "-", // – en dash
  "—": "-", // — em dash
  "―": "-", // ― horizontal bar
  "−": "-", // − minus sign
  "‘": "'", // ‘
  "’": "'", // ’
  "“": '"', // “
  "”": '"', // ”
  " ": " ", // non-breaking space
};

/**
 * `_normalize` from resume_pdf.py: fold the punctuation the extractor is
 * known to mangle, then collapse every run of whitespace to one space.
 */
export function normalizeLine(text: string): string {
  let folded = "";
  for (const ch of text) folded += PUNCT_FOLD[ch] ?? ch;
  return folded.split(/\s+/).filter(Boolean).join(" ");
}

/** One entry of `GET /resumes/{id}/diff`'s `changes` array. */
export interface DiffChange {
  before: string;
  after?: string | null;
  evidenceRef?: string | null;
}

/**
 * The renderer's two lookup structures, built once per version so a bullet
 * list of any length costs one pass.
 */
export interface RenderDiffIndex {
  /** normalize(before) -> after, for changes that carry both halves. */
  swaps: Map<string, string>;
  /** normalize(after) for every change that produced tailored wording. */
  tailored: Set<string>;
}

export function buildRenderDiffIndex(changes: readonly DiffChange[] | null | undefined): RenderDiffIndex {
  const swaps = new Map<string, string>();
  const tailored = new Set<string>();
  for (const change of changes ?? []) {
    const after = change.after ?? "";
    if (change.before && after) swaps.set(normalizeLine(change.before), after);
    if (after) tailored.add(normalizeLine(after));
  }
  return { swaps, tailored };
}

/** What the renderer would do with one stored bullet. */
export interface RenderedBullet {
  /** The text the PDF draws — the tailored wording when a swap applies. */
  text: string;
  /**
   * True exactly when `_draw_flow_bullet(..., washed=True)` would run in the
   * renderer's diff PREVIEW — the line the tailoring reworded. The downloaded
   * document draws that same wording with NO wash behind it (RFMT-2); this
   * flag is about which line changed, never about a tint in the download.
   */
  changed: boolean;
  /** The baseline wording this line replaced, when a swap fired. */
  replaced: string | null;
}

/**
 * Resolve one stored bullet through the renderer's rules.
 *
 * Mirrors `render_branded_resume`'s bullet branch line for line:
 * `drawn = swaps.get(normalize(text), text)` then
 * `tailored=normalize(drawn) in tailored or normalize(text) in swaps`.
 */
export function renderBullet(text: string, index: RenderDiffIndex): RenderedBullet {
  const key = normalizeLine(text);
  const swapped = index.swaps.get(key);
  const drawn = swapped ?? text;
  const changed = index.tailored.has(normalizeLine(drawn)) || index.swaps.has(key);
  return { text: drawn, changed, replaced: swapped != null ? text : null };
}

/** Resolve a whole bullet list. Order is preserved — it is the document order. */
export function renderBullets(
  bullets: readonly string[],
  changes: readonly DiffChange[] | null | undefined,
): RenderedBullet[] {
  const index = buildRenderDiffIndex(changes);
  return bullets.map((b) => renderBullet(b, index));
}

/**
 * The two counts the Studio already states verbatim ("N rewrites · M
 * additions"). A change with a `before` is a rewrite; one without is an
 * addition. Kept here so the strip and the change list can never disagree.
 */
export function changeCounts(changes: readonly DiffChange[] | null | undefined): {
  rewrites: number;
  additions: number;
} {
  const list = changes ?? [];
  return {
    rewrites: list.filter((c) => c.before).length,
    additions: list.filter((c) => !c.before).length,
  };
}

/**
 * Word-level segmentation of a rewrite, for the wash.
 *
 * The renderer washes the WHOLE bullet — it draws one rectangle behind the
 * line — so the wash on screen is on the whole line too. Within that line we
 * additionally mark the words that are new relative to the baseline wording,
 * which is a strictly weaker, presentational claim: it says "these words were
 * not in your original sentence", which is verifiable from the two strings in
 * hand and nothing else.
 *
 * A word counts as carried-over when the SAME normalised token appears in the
 * baseline. Repeats are consumed once each (a multiset), so a sentence that
 * genuinely repeats a word twice does not get the second one silently
 * absolved by the first.
 */
export interface WordSegment {
  text: string;
  added: boolean;
}

/** Strip leading/trailing punctuation so "products." matches "products". */
function wordKey(word: string): string {
  return normalizeLine(word)
    .toLowerCase()
    .replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
}

export function segmentRewrite(before: string, after: string): WordSegment[] {
  const pool = new Map<string, number>();
  for (const token of normalizeLine(before).toLowerCase().split(" ")) {
    const key = wordKey(token);
    if (!key) continue;
    pool.set(key, (pool.get(key) ?? 0) + 1);
  }

  // Tokenise into words and the whitespace between them, keeping both.
  const tokens = after.split(/(\s+)/).filter((t) => t.length > 0);
  const flags: (boolean | null)[] = tokens.map((token) => {
    if (/^\s+$/.test(token)) return null; // whitespace: decided in pass 2
    const key = wordKey(token);
    if (!key) return false; // pure punctuation is never "a new word"
    const remaining = pool.get(key) ?? 0;
    if (remaining > 0) {
      pool.set(key, remaining - 1);
      return false;
    }
    return true;
  });

  // Whitespace joins its neighbours only when both sides agree, so a run of
  // new words reads as ONE phrase and a boundary space is never washed.
  for (let i = 0; i < flags.length; i += 1) {
    if (flags[i] !== null) continue;
    const prev = flags[i - 1] ?? false;
    const next = flags[i + 1] ?? false;
    flags[i] = prev === true && next === true;
  }

  // Merge runs so the DOM carries one <mark> per contiguous new phrase rather
  // than one per word (a per-word mark reads as a ransom note).
  const merged: WordSegment[] = [];
  tokens.forEach((text, i) => {
    const added = flags[i] === true;
    const last = merged[merged.length - 1];
    if (last && last.added === added) last.text += text;
    else merged.push({ text, added });
  });
  return merged;
}
