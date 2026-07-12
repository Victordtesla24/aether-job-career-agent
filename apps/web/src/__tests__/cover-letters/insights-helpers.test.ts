/**
 * AGT-COVER — unit coverage for the Cover Letter Studio helpers (wireframe
 * cover-letter-studio.html): claim highlighting, Voice DNA labels, timestamp
 * normalisation and word counting.
 */
import { describe, expect, it } from "vitest";

import type { EvidenceRow } from "../../components/cover-letters/api";
import {
  formalityLabel,
  highlightSegments,
  parseApiDate,
  toneLabel,
  wordCount,
} from "../../components/cover-letters/insights";

function row(claim: string, grounded: boolean): EvidenceRow {
  return {
    claim,
    grounded,
    storyId: grounded ? "s1" : null,
    storyTitle: grounded ? "Story" : null,
  };
}

describe("highlightSegments", () => {
  const letter = "I led large program delivery and platform thinking at scale.";

  it("marks grounded and ungrounded claims and preserves the full text", () => {
    const segments = highlightSegments(letter, [
      row("large program delivery", true),
      row("platform thinking", false),
    ]);
    expect(segments.map((s) => s.text).join("")).toBe(letter);
    expect(segments.find((s) => s.kind === "grounded")?.text).toBe("large program delivery");
    expect(segments.find((s) => s.kind === "ungrounded")?.text).toBe("platform thinking");
  });

  it("matches case-insensitively but keeps the letter's casing", () => {
    const segments = highlightSegments("Delivered AI Delivery outcomes.", [
      row("ai delivery", true),
    ]);
    expect(segments.find((s) => s.kind === "grounded")?.text).toBe("AI Delivery");
  });

  it("skips claims not present and overlapping claims", () => {
    const segments = highlightSegments(letter, [
      row("large program delivery", true),
      row("program delivery and", false), // overlaps the first claim
      row("kubernetes", true), // absent
    ]);
    expect(segments.filter((s) => s.kind !== "plain")).toHaveLength(1);
    expect(segments.map((s) => s.text).join("")).toBe(letter);
  });

  it("returns the whole letter as plain when there is no evidence", () => {
    expect(highlightSegments(letter, [])).toEqual([{ text: letter, kind: "plain" }]);
  });
});

describe("voice DNA labels", () => {
  it("maps slider thirds to tone labels", () => {
    expect(toneLabel(10)).toBe("Confident · Direct");
    expect(toneLabel(60)).toBe("Warm · Professional");
    expect(toneLabel(90)).toBe("Enthusiastic · Personable");
  });

  it("maps slider thirds to formality labels", () => {
    expect(formalityLabel(0)).toBe("Conversational");
    expect(formalityLabel(55)).toBe("Balanced");
    expect(formalityLabel(100)).toBe("Formal");
  });
});

describe("parseApiDate", () => {
  it("treats zone-less API timestamps as UTC", () => {
    expect(parseApiDate("2026-07-10T07:45:50.028000").toISOString()).toBe(
      "2026-07-10T07:45:50.028Z",
    );
  });

  it("leaves explicit zones untouched", () => {
    expect(parseApiDate("2026-07-10T07:45:50Z").toISOString()).toBe("2026-07-10T07:45:50.000Z");
  });
});

describe("wordCount", () => {
  it("counts words across newlines and trims edges", () => {
    expect(wordCount("Dear team,\n\nI am writing today. ")).toBe(6);
    expect(wordCount("")).toBe(0);
  });
});
