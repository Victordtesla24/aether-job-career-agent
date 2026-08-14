/**
 * U-STORY-3a — CONTENT-LEVEL provenance: does the cited LINE hold the claim?
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
 * A line number is not provenance. Provenance is the CODE at that line. This
 * suite opens every cited file at every cited line — in the LIVE tree, never a
 * snapshot, because staleness IS a disagreement with the live tree — and
 * asserts:
 *
 *   1. the citation resolves at all: the file exists, the line is inside it;
 *   2. the cited span is SUBSTANTIVE — not blank, not a lone bracket. `:42`
 *      pointing at an empty line taught a reviewer nothing;
 *   3. `anchors[i]` — the verbatim fragment citation `i` was taken for — is
 *      really inside citation `i`'s span. This is the drift alarm: move the
 *      code, and CI fails here instead of the table silently pointing at
 *      whatever slid into that line number;
 *   4. at least one anchor shares a real identifier with the hop's `mechanism`
 *      prose, so an anchor cannot be back-filled out of whatever text happens
 *      to sit at a stale line — it has to be about what the hop claims;
 *   5. hops shared between linkages are ONE object. The wrong scout citation
 *      reached four rendered edges because it had been copy-pasted four times.
 *
 * The last describe block mutates honest hops the four ways a citation goes
 * stale, so this suite cannot pass by checking nothing.
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  WORKFLOW_LINKAGES,
  citationsOf,
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
 * Everything wrong with one hop's provenance, as sentences. Empty means the
 * citations resolve, the cited code is substantive, every anchor is at the
 * line that cites it, and at least one anchor is about the stated mechanism.
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
    if (cite.end > lines.length) {
      fails.push(`${where}: ${at} is past EOF (${lines.length} lines)`);
      return;
    }
    const span = lines.slice(cite.start - 1, cite.end);
    if (!span.some((l) => l.replace(/[^A-Za-z0-9_"']/g, "").length >= 3)) {
      fails.push(`${where}: ${at} is blank or punctuation only — ${JSON.stringify(span.join("|"))}`);
    }
    const anchor = hop.anchors?.[i];
    if (anchor !== undefined && !span.join("\n").includes(anchor)) {
      fails.push(
        `${where}: ${at} does not contain ${JSON.stringify(anchor)} — the citation is stale, ` +
          `or the anchor is wrong. Found: ${JSON.stringify(span.join("\n").slice(0, 160))}`,
      );
    }
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

describe("U-STORY-3a provenance — the cited LINE, not just the citation string", () => {
  it("finds hops to check (an empty walk must not pass vacuously)", () => {
    expect(HOPS.length).toBeGreaterThanOrEqual(15);
    expect(HOPS.every((h) => citationsOf(h.evidence).length > 0)).toBe(true);
  });

  it("resolves every citation, at the line, to the code the hop claims", () => {
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

describe("the provenance check itself — proved on hops that are wrong on purpose", () => {
  const honest = HOPS.find((h) => h.to === "agent.resumeTailoring")!;

  it("passes the real hop it mutates, so the failures below are the mutation", () => {
    expect(provenanceFailures(honest)).toEqual([]);
  });

  it("catches a citation whose code has drifted down the file", () => {
    // Exactly the shipped defect: the right file, a plausible line, code that
    // has since moved. +10 is smaller than the ~120-line drift that caused it.
    const drifted = citationsOf(honest.evidence).map((c) => c.start + 10);
    const stale: LinkageHop = {
      ...honest,
      evidence: `apps/api/app/agents/tailor_agent.py:${drifted.join(",")}`,
    };
    expect(provenanceFailures(stale).join("\n")).toMatch(/does not contain/);
  });

  it("catches a citation pointing at a blank line or a bare bracket", () => {
    const blank: LinkageHop = {
      ...honest,
      evidence: "apps/api/app/agents/submission_agent.py:42",
      anchors: ["submit_application_for_job"],
    };
    expect(provenanceFailures(blank).join("\n")).toMatch(/blank or punctuation only/);
  });

  it("catches a citation past the end of the file", () => {
    const past: LinkageHop = {
      ...honest,
      evidence: "apps/api/app/agents/tailor_agent.py:999999",
      anchors: ["build_story_evidence"],
    };
    expect(provenanceFailures(past).join("\n")).toMatch(/past EOF/);
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
    // The stale line 546 really does hold this comment — anchoring on it would
    // satisfy a naive "the anchor is at the line" check, so the mechanism-topic
    // rule has to reject it.
    const backfilled: LinkageHop = {
      ...honest,
      evidence: "apps/api/app/agents/tailor_agent.py:546",
      anchors: ["hyphen-corrupted bullets"],
    };
    expect(provenanceFailures(backfilled).join("\n")).toMatch(/no anchor shares an identifier/);
  });

  it("catches a citation left unanchored", () => {
    const unanchored: LinkageHop = { ...honest, anchors: [] };
    expect(provenanceFailures(unanchored).join("\n")).toMatch(/citations but 0 anchors/);
  });
});
