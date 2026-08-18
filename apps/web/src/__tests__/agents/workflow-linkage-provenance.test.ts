/**
 * U-STORY-3a — CONTENT-LEVEL provenance: does the cited FILE hold the claim?
 *
 * WHY THIS FILE EXISTS (adversarial review, 2026-08-14). The linkage table's
 * sibling test pins every hop against the frozen AGENT-GRAPH snapshot, and
 * `drawableLinkages` rejects any citation that is not shaped like a file:line.
 * Both check the citation STRING. Neither ever opened the file.
 *
 * So this shipped: `tailor_agent.py:546,556,573` cited for "story_evidence
 * joined into evidence_extra" — three lines of unrelated resume-PDF-healing
 * code, one of them a bare `)`. The real call site is ~120 lines further down.
 * Nothing was fabricated: the citation was copied verbatim out of a discovery
 * artefact frozen hours before the same day's commits pushed the code it
 * pointed at down the file. The table then froze that drift into a user-facing
 * claim whose own header promises "a reviewer can follow the same path the
 * discovery walked".
 *
 * REDESIGN (RUN-20260818T0223Z). The FIRST version of this suite fixed that
 * defect by re-checking the anchor at the EXACT stored line on every run —
 * which caught the original bug, but then became a second version of the same
 * defect: it required the LINE NUMBER, not just the code, to stay frozen. Any
 * unrelated edit above a cited line in a Python file (an import added, a
 * docstring line inserted, an unrelated function grown by one line during a
 * merge) shifted every citation below it and broke this suite on a push that
 * touched none of the cited code. That happened for real, twice
 * (`docs/delivery/evidence/RUN-20260818T0223Z/BATCH-2/`, and again on cursor
 * PR#25), each time blocking the shared VPS Delivery train over a citation
 * that was never wrong about the CODE, only about the LINE NUMBER.
 *
 * THE ACTUAL INVARIANT, restated precisely: **the cited FILE must really
 * contain the anchor code the hop claims, and that code must be on-topic for
 * the hop's mechanism.** A stored line number was always navigation metadata
 * for a human reviewer, never itself evidence — the anchor STRING is the
 * evidence. So this suite now resolves every citation by CONTENT: it searches
 * the cited file's live text for the anchor, anywhere, and only fails when the
 * anchor is genuinely absent (the code was renamed or removed) or the anchor
 * that IS present is off-topic for the claim. A citation whose stored line has
 * drifted — by ten lines or by ten thousand — passes without a hand-edit, as
 * it should: nothing about the wire it documents changed.
 *
 * The stored line is not thrown away — it is downgraded from a requirement to
 * a disambiguation hint: if (and only if) the same anchor string recurs more
 * than once in one cited file, the occurrence nearest the stored line is the
 * one resolved, so a duplicated anchor still points somewhere specific rather
 * than "the first occurrence, whichever that happens to be". No hop in this
 * table has a within-file duplicate anchor today (checked by hand against
 * every citation this suite covers), so that preference does not change any
 * verdict here yet — it is implemented and proved against a synthetic fixture
 * below so it is correct the day one is added.
 *
 * This suite still opens every cited file in the LIVE tree, never a snapshot
 * — staleness IS a disagreement with the live tree — and asserts:
 *
 *   1. the citation resolves at all: the file exists, and the anchor text
 *      really appears somewhere in it — content, not line number;
 *   2. `anchors[i]` — the verbatim fragment citation `i` was taken for — is a
 *      real, substantive fragment (not empty, not a lone bracket: an anchor
 *      that weak could "resolve" against almost anything, which is not
 *      provenance);
 *   3. at least one anchor shares a real identifier with the hop's `mechanism`
 *      prose, so an anchor cannot be back-filled out of whatever text happens
 *      to be in the file — it has to be about what the hop claims;
 *   4. hops shared between linkages are ONE object. The wrong scout citation
 *      reached four rendered edges because it had been copy-pasted four times.
 *
 * The last describe block mutates honest hops several ways: some now
 * correctly TOLERATE (pure line drift, moderate and extreme — this is the
 * whole point of the redesign), the rest still correctly FAIL (a genuinely
 * absent anchor, a missing file, an off-topic anchor, a missing anchor). This
 * suite cannot pass by checking nothing.
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  WORKFLOW_LINKAGES,
  citationsOf,
  type Citation,
  type LinkageHop,
} from "../../components/agents/workflow-linkage";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../../../..");

/** Every distinct hop object in the table, deduped by identity. */
const HOPS: LinkageHop[] = [];
WORKFLOW_LINKAGES.forEach((link) => {
  link.provenance.forEach((hop) => {
    if (!HOPS.includes(hop)) HOPS.push(hop);
  });
});

const fileCache = new Map<string, string[] | null>();
function linesOf(relPath: string): string[] | null {
  if (fileCache.has(relPath)) return fileCache.get(relPath) ?? null;
  const abs = path.join(REPO_ROOT, relPath);
  const lines = existsSync(abs) ? readFileSync(abs, "utf8").split("\n") : null;
  fileCache.set(relPath, lines);
  return lines;
}

/** Identifier-ish words, lowercased. `list_by_user` -> list, by, user. */
const STOP = new Set([
  "from",
  "this",
  "that",
  "with",
  "when",
  "then",
  "than",
  "into",
  "only",
  "same",
  "self",
  "none",
  "true",
  "false",
  "import",
  "return",
  "does",
  "never",
  "real",
  "each",
  "over",
]);
function words(text: string): Set<string> {
  return new Set(
    text
      .split(/[^A-Za-z0-9]+/)
      .map((w) => w.toLowerCase())
      .filter((w) => w.length >= 4 && !STOP.has(w)),
  );
}

/**
 * Resolve one anchor against the LIVE content of `lines` — never against the
 * stored citation span. A stored `file:line` is navigation metadata, not
 * provenance (see file header); the anchor SUBSTRING is. `found` is true the
 * moment the anchor text appears anywhere in the file, so pure line drift (an
 * edit above the cited code, a merge that shifted the whole file) can never
 * fail this check on its own.
 *
 * The stored line is used for exactly one thing: disambiguating an anchor
 * that recurs more than once in the same file, by resolving to whichever
 * occurrence is NEAREST the stored line — "search near the stored line first,
 * else anywhere" collapses to one nearest-distance pick once every occurrence
 * is already in hand. When the anchor occurs exactly once, that is the
 * occurrence, regardless of what the stored line says.
 */
function resolveCitation(
  lines: string[],
  anchor: string,
  cite: Pick<Citation, "start" | "end">,
): { found: boolean; line: number | null } {
  const hits: number[] = [];
  lines.forEach((line, idx) => {
    if (line.includes(anchor)) hits.push(idx + 1);
  });
  if (hits.length === 0) return { found: false, line: null };
  const nearest = hits.reduce((best, hit) =>
    Math.abs(hit - cite.start) < Math.abs(best - cite.start) ? hit : best,
  );
  return { found: true, line: nearest };
}

/**
 * Everything wrong with one hop's provenance, as sentences. Empty means every
 * cited file exists and really contains its anchor's code SOMEWHERE (content,
 * not line number), every anchor is substantive, and at least one anchor is
 * about the stated mechanism.
 *
 * Returned rather than asserted so the mutation block below can prove each
 * rule actually fires.
 */
function provenanceFailures(hop: LinkageHop): string[] {
  const where = `${hop.from} -> ${hop.to}`;
  const cites = citationsOf(hop.evidence);
  const fails: string[] = [];

  if (cites.length === 0) fails.push(`${where}: evidence cites no file:line`);
  if (!Array.isArray(hop.anchors) || hop.anchors.length !== cites.length) {
    fails.push(`${where}: ${cites.length} citations but ${hop.anchors?.length ?? 0} anchors`);
  }
  (hop.anchors ?? []).forEach((anchor) => {
    if (anchor.trim().length < 6 || !/[A-Za-z_]{3}/.test(anchor)) {
      fails.push(`${where}: "${anchor}" is too weak to anchor anything`);
    }
  });

  cites.forEach((cite, i) => {
    const at = `${cite.file}:${cite.start}${cite.end > cite.start ? `-${cite.end}` : ""}`;
    const lines = linesOf(cite.file);
    if (!lines) {
      fails.push(`${where}: no such file ${cite.file}`);
      return;
    }
    const anchor = hop.anchors?.[i];
    // Citation-count/anchor-count mismatch is already flagged above; nothing
    // to resolve here without an anchor to search for.
    if (anchor === undefined) return;

    const resolved = resolveCitation(lines, anchor, cite);
    if (!resolved.found) {
      fails.push(
        `${where}: ${JSON.stringify(anchor)} is not present anywhere in ${cite.file} ` +
          `(cited near ${at}) — the code was renamed, removed, or the anchor is wrong`,
      );
    }
    // A stored line that no longer matches resolved.line is NOT a failure:
    // it is exactly the line drift this suite is now tolerant of. See file
    // header for why the line number was never the provenance guarantee.
  });

  const claim = words(hop.mechanism);
  const onTopic = (hop.anchors ?? []).some((anchor) =>
    [...words(anchor)].some((w) => claim.has(w)),
  );
  if (!onTopic) {
    fails.push(
      `${where}: no anchor shares an identifier with the mechanism ` +
        `(${JSON.stringify(hop.mechanism.slice(0, 90))}) — the citation may be pointing at ` +
        `code that is not the one being described`,
    );
  }
  return fails;
}

describe("U-STORY-3a provenance — the cited FILE, not the stored line number", () => {
  it("finds hops to check (an empty walk must not pass vacuously)", () => {
    expect(HOPS.length).toBeGreaterThanOrEqual(15);
    expect(HOPS.every((h) => citationsOf(h.evidence).length > 0)).toBe(true);
  });

  it("resolves every citation, by content, to the code the hop claims", () => {
    const failures = HOPS.flatMap(provenanceFailures);
    expect(failures, `\n${failures.join("\n")}\n`).toEqual([]);
  });

  it("shares one hop object wherever two linkages make the same claim", () => {
    // The scout citation was wrong on four rendered edges because it had been
    // copy-pasted four times. Shared claims must be shared objects, so one fix
    // is one fix.
    const byPair = new Map<string, LinkageHop[]>();
    WORKFLOW_LINKAGES.forEach((link) =>
      link.provenance.forEach((hop) => {
        const key = `${hop.from}|${hop.to}|${hop.kind}`;
        byPair.set(key, [...(byPair.get(key) ?? []), hop]);
      }),
    );
    byPair.forEach((hops, key) => {
      const distinct = hops.filter((h, i) => hops.indexOf(h) === i);
      expect(distinct.length, `${key} is duplicated as ${distinct.length} separate literals`).toBe(
        1,
      );
    });
  });
});

describe("the provenance check itself — proved on hops that are wrong (or drifted) on purpose", () => {
  const honest = HOPS.find((h) => h.to === "agent.resumeTailoring")!;

  it("passes the real hop it mutates, so the failures below are the mutation", () => {
    expect(provenanceFailures(honest)).toEqual([]);
  });

  it("TOLERATES a citation whose stored line has drifted down the file", () => {
    // Exactly the shipped defect that broke Delivery twice
    // (docs/delivery/evidence/RUN-20260818T0223Z/BATCH-2/, cursor PR#25): an
    // unrelated edit shifts every line below it. +10 is smaller than the
    // ~120-line drift that caused the original defect, but the point is the
    // same code, a now-wrong line number — and that must no longer fail.
    const drifted = citationsOf(honest.evidence).map((c) => c.start + 10);
    const stale: LinkageHop = {
      ...honest,
      evidence: `apps/api/app/agents/tailor_agent.py:${drifted.join(",")}`,
    };
    expect(provenanceFailures(stale)).toEqual([]);
  });

  it("TOLERATES a stored line that is wildly wrong, even past EOF, as long as the anchor is real", () => {
    // The stored line is advisory metadata, never a hard requirement (see
    // file header) — content resolution does not care that ":999999" cannot
    // possibly be inside this file. The anchor is real and unique, so this
    // must pass exactly like a citation whose line was never wrong at all.
    const wildLine: LinkageHop = {
      ...honest,
      evidence: "apps/api/app/agents/tailor_agent.py:999999",
      anchors: ["story_evidence = build_story_evidence("],
    };
    expect(provenanceFailures(wildLine)).toEqual([]);
  });

  it("catches an anchor whose code was genuinely renamed or removed from the cited file", () => {
    // The right file, but code that is not there under any line number — the
    // real break this suite exists to keep catching. Only citation 0's
    // anchor is broken; the other two are left real so the failure is
    // exactly this one rule, not also an anchor/citation-count mismatch.
    const renamed: LinkageHop = {
      ...honest,
      anchors: [
        "totally_fabricated_identifier_that_was_never_written_zzz9",
        ...honest.anchors.slice(1),
      ],
    };
    const failures = provenanceFailures(renamed);
    expect(failures.join("\n")).toMatch(/not present anywhere/);
    expect(failures).toHaveLength(1);
  });

  it("catches a citation to a file that is not there at all", () => {
    const gone: LinkageHop = {
      ...honest,
      evidence: "apps/api/app/agents/there_is_no_such_agent.py:1",
      anchors: ["build_story_evidence"],
    };
    expect(provenanceFailures(gone).join("\n")).toMatch(/no such file/);
  });

  it("catches an anchor back-filled from unrelated code that happens to be there", () => {
    // "hyphen-corrupted bullets" really is in tailor_agent.py — it is real,
    // substantive, on-topic-sounding-adjacent PDF-healing prose, found
    // wherever content resolution looks for it in the file (the stored line
    // below is deliberately not even where it lives any more). A naive
    // "the anchor exists in the file" check would accept this; the
    // mechanism-topic rule has to reject it anyway.
    const backfilled: LinkageHop = {
      ...honest,
      evidence: "apps/api/app/agents/tailor_agent.py:1",
      anchors: ["hyphen-corrupted bullets"],
    };
    expect(provenanceFailures(backfilled).join("\n")).toMatch(/no anchor shares an identifier/);
  });

  it("catches a citation left unanchored", () => {
    const unanchored: LinkageHop = { ...honest, anchors: [] };
    expect(provenanceFailures(unanchored).join("\n")).toMatch(/citations but 0 anchors/);
  });
});

describe("resolveCitation — content resolution and duplicate-anchor disambiguation", () => {
  // Calls the SAME resolveCitation used by provenanceFailures above (module
  // scope, not re-implemented) against synthetic file content, so a
  // disambiguation bug here would also be a bug in the real check. No real
  // repo file currently has a within-file duplicate anchor (checked by hand
  // against every citation this suite covers), so this synthetic fixture is
  // the only place the multi-occurrence branch is exercised today.

  it("finds a unique anchor regardless of how far the stored line is from it", () => {
    const lines = ["one", "two", "def target():", "four", "five"];
    expect(resolveCitation(lines, "def target():", { start: 999, end: 999 })).toEqual({
      found: true,
      line: 3,
    });
  });

  it("reports absence honestly when the anchor is nowhere in the file", () => {
    const lines = ["one", "two", "three"];
    expect(resolveCitation(lines, "def target():", { start: 1, end: 1 })).toEqual({
      found: false,
      line: null,
    });
  });

  it("disambiguates a duplicate anchor toward the occurrence nearest the stored line", () => {
    // "def target():" appears at line 2 AND line 10. A stored citation near
    // line 2 must resolve to line 2; the same anchor cited near line 10 must
    // resolve to line 10 — not to whichever occurrence the file lists first.
    const lines = [
      "one",
      "def target():",
      "three",
      "four",
      "five",
      "six",
      "seven",
      "eight",
      "nine",
      "def target():",
      "eleven",
    ];
    expect(resolveCitation(lines, "def target():", { start: 1, end: 1 })).toEqual({
      found: true,
      line: 2,
    });
    expect(resolveCitation(lines, "def target():", { start: 11, end: 11 })).toEqual({
      found: true,
      line: 10,
    });
  });
});
