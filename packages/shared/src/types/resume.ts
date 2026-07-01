/**
 * Resume domain types.
 *
 * GUARDRAIL: resume content is sourced only from the user's real resume PDF.
 * `evidenceRefs` link every generated/tailored bullet back to a source span so
 * nothing is fabricated. `formatHash` is a SHA-256 of the raw PDF bytes and must
 * never change once computed for a given source file.
 */

/** A reference back to source evidence for a generated/tailored bullet. */
export interface EvidenceRef {
  /** Identifier of the source (e.g. resume section id or story entry id). */
  sourceId: string;
  /** Optional character span within the source text. */
  span?: { start: number; end: number };
  /** Verbatim snippet supporting the claim. */
  snippet?: string;
}

/** A single entry (job, project, education item) within a resume section. */
export interface ResumeEntry {
  id: string;
  title: string;
  organization?: string;
  location?: string;
  startDate?: string;
  endDate?: string;
  bullets: string[];
  /** Evidence backing each bullet, index-aligned with `bullets`. */
  evidenceRefs?: EvidenceRef[][];
}

/** A logical section of a resume (experience, education, skills, etc.). */
export interface ResumeSection {
  id: string;
  heading: string;
  entries: ResumeEntry[];
}

/** A parsed, structured resume. */
export interface Resume {
  id: string;
  userId: string;
  /** Original file name of the uploaded PDF. */
  fileName: string;
  /** SHA-256 hash of the raw PDF bytes; immutable per source file. */
  formatHash: string;
  /** Full extracted plain text, format-preserving. */
  rawText: string;
  sections: ResumeSection[];
  createdAt: string;
  updatedAt: string;
}
