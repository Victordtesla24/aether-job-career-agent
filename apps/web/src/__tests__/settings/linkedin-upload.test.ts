/**
 * B7 — Settings → Career Data LinkedIn data-export upload.
 *
 * `POST /workspaces/career-data/linkedin-upload` reports honest per-section
 * ingested counts (a partial export — e.g. only `Positions.csv` — still
 * ingests) plus the same `CareerDataSource` shape the paste path returns.
 * These pin the pure copy-building helpers the Settings panel renders.
 *
 * RED before the fix: `components/settings/linkedin-upload` did not exist.
 */
import { describe, expect, it } from "vitest";

import { buildLinkedinUploadNotice, summarizeIngestedCounts } from "../../components/settings/linkedin-upload";
import type { LinkedinExportUploadResult } from "../../lib/api/workspaces";

describe("summarizeIngestedCounts", () => {
  it("lists every non-zero section, singular/plural correctly", () => {
    expect(summarizeIngestedCounts({ profile: 1, positions: 2, education: 1, skills: 3 })).toBe(
      "2 positions, 1 education entry, 3 skills, 1 profile summary",
    );
  });

  it("omits sections that ingested nothing", () => {
    expect(summarizeIngestedCounts({ profile: 0, positions: 2, education: 0, skills: 0 })).toBe(
      "2 positions",
    );
  });

  it("is honest when nothing at all ingested", () => {
    expect(summarizeIngestedCounts({ profile: 0, positions: 0, education: 0, skills: 0 })).toBe(
      "nothing recognizable",
    );
  });

  it("singularizes a count of exactly one", () => {
    expect(summarizeIngestedCounts({ profile: 0, positions: 1, education: 0, skills: 1 })).toBe(
      "1 position, 1 skill",
    );
  });
});

describe("buildLinkedinUploadNotice", () => {
  const okResult: LinkedinExportUploadResult = {
    source: {
      source: "linkedin",
      status: "ok",
      url: null,
      summary: "LinkedIn summary (provided by the candidate):\n...",
      error: null,
      lastSynced: "2026-08-14T10:00:00",
    },
    ingestedCounts: { profile: 1, positions: 2, education: 1, skills: 3 },
    linkedinNote: "note",
  };

  it("states what was actually ingested on success", () => {
    const notice = buildLinkedinUploadNotice(okResult);
    expect(notice).toContain("2 positions");
    expect(notice).toContain("ingested");
  });

  it("reports a partial-only export honestly (only Positions.csv)", () => {
    const partial: LinkedinExportUploadResult = {
      ...okResult,
      ingestedCounts: { profile: 0, positions: 2, education: 0, skills: 0 },
    };
    const notice = buildLinkedinUploadNotice(partial);
    expect(notice).toContain("2 positions");
    expect(notice).not.toMatch(/education/i);
    expect(notice).not.toMatch(/skill/i);
  });

  it("surfaces the server's real error verbatim for a non-ok status, never a fabricated success", () => {
    const empty: LinkedinExportUploadResult = {
      source: { ...okResult.source, status: "empty", summary: null, error: "No usable data found." },
      ingestedCounts: { profile: 0, positions: 0, education: 0, skills: 0 },
      linkedinNote: "note",
    };
    expect(buildLinkedinUploadNotice(empty)).toBe("No usable data found.");
  });
});

describe("describeUploadError re-export", () => {
  it("re-exports the same helper /resumes/upload uses (shared rejection shape)", async () => {
    const { describeUploadError } = await import("../../components/settings/linkedin-upload");
    const { describeUploadError: original } = await import("../../components/settings/resume-upload");
    expect(describeUploadError).toBe(original);
  });
});
