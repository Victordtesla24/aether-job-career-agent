/**
 * Pure helpers for the Cover Letter Studio (wireframe cover-letter-studio.html):
 * evidence-claim highlighting inside the letter page, Voice DNA slider labels
 * and timestamp normalisation. Kept side-effect free for unit testing.
 */
import type { EvidenceRow } from "./api";

export type SegmentKind = "plain" | "grounded" | "ungrounded";

export interface Segment {
  text: string;
  kind: SegmentKind;
}

/**
 * Split the letter into segments, marking the first occurrence of each
 * evidence claim (case-insensitive, non-overlapping) so the preview can
 * highlight grounded (green) vs unsourced (amber) phrases like the wireframe.
 */
export function highlightSegments(letter: string, evidence: EvidenceRow[]): Segment[] {
  const lower = letter.toLowerCase();
  const marks: { start: number; end: number; kind: SegmentKind }[] = [];
  for (const row of evidence) {
    const claim = row.claim.trim();
    if (!claim) continue;
    const start = lower.indexOf(claim.toLowerCase());
    if (start < 0) continue;
    const end = start + claim.length;
    if (marks.some((m) => start < m.end && end > m.start)) continue;
    marks.push({ start, end, kind: row.grounded ? "grounded" : "ungrounded" });
  }
  marks.sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let pos = 0;
  for (const mark of marks) {
    if (mark.start > pos) segments.push({ text: letter.slice(pos, mark.start), kind: "plain" });
    segments.push({ text: letter.slice(mark.start, mark.end), kind: mark.kind });
    pos = mark.end;
  }
  if (pos < letter.length) segments.push({ text: letter.slice(pos), kind: "plain" });
  return segments;
}

/** Voice DNA slider value → tone label (wireframe: "Warm · Professional"). */
export function toneLabel(value: number): string {
  if (value < 34) return "Confident · Direct";
  if (value < 67) return "Warm · Professional";
  return "Enthusiastic · Personable";
}

/** Voice DNA slider value → formality label (wireframe: "Balanced"). */
export function formalityLabel(value: number): string {
  if (value < 34) return "Conversational";
  if (value < 67) return "Balanced";
  return "Formal";
}

/** API timestamps lack a timezone suffix; they are UTC — normalise before parsing. */
export function parseApiDate(value: string): Date {
  const hasZone = /Z$|[+-]\d{2}:\d{2}$/.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}
