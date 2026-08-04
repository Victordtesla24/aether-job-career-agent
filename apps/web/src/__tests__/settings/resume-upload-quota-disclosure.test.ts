/**
 * F-03 — Settings → Resume Management must disclose the extraction run cost
 * BEFORE the upload, and must describe afterwards only what actually happened.
 *
 * PROD-UAT-2026-08-03 finding F-03 (MAJOR): the panel's only mention of story
 * extraction was the post-upload notice
 *   `Uploaded and parsed — registered as v3 (“…”); story extraction ran.`
 * which (a) appeared only after the fact, (b) never said the extraction was
 * billable, and (c) claimed the run happened unconditionally — including when
 * the server had reported `storyExtraction.error`.
 *
 * RED before the fix: `components/settings/resume-upload` did not exist; the
 * copy was a template literal inlined in settings-client.tsx with no
 * conditional on what the server reported and no cost anywhere on the screen.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildUploadNotice,
  EXTRACTION_COST_HINT,
  EXTRACTION_OPT_IN_LABEL,
  STORY_EXTRACTION_RUN_COST,
} from "../../components/settings/resume-upload";

describe("F-03 pre-upload cost disclosure", () => {
  it("states the run cost in the opt-in label the user reads before committing", () => {
    expect(EXTRACTION_OPT_IN_LABEL).toMatch(/Story Extractor/);
    expect(EXTRACTION_OPT_IN_LABEL).toMatch(/uses 1 of your monthly agent runs/);
  });

  it("states that uploading alone costs nothing", () => {
    expect(EXTRACTION_COST_HINT).toMatch(/free and uses no agent runs/);
  });

  it("prices one extraction at exactly one metered run", () => {
    expect(STORY_EXTRACTION_RUN_COST).toBe(1);
  });
});

describe("F-03 post-upload notice is truthful", () => {
  it("says no run was used when extraction was not requested", () => {
    const notice = buildUploadNotice({
      version: 3,
      label: "Uploaded — vik_resume",
      storyExtractionRequested: false,
      storyExtraction: null,
    });
    expect(notice).toContain("v3");
    expect(notice).toContain("No agent run was used");
    expect(notice).not.toMatch(/extraction ran/i);
  });

  it("never claims extraction ran when the server reported an error", () => {
    const notice = buildUploadNotice({
      version: 4,
      label: "Uploaded — vik_resume",
      storyExtractionRequested: true,
      storyExtraction: { error: "LLM unavailable" },
    });
    expect(notice).toContain("Story extraction failed: LLM unavailable");
    expect(notice).toContain("no stories were added");
    expect(notice).not.toMatch(/extraction ran/i);
  });

  it("reports the real story count AND the run charge when it did run", () => {
    const notice = buildUploadNotice({
      version: 5,
      label: "Uploaded — vik_resume",
      storyExtractionRequested: true,
      storyExtraction: { created: 6, bullets: 9 },
    });
    expect(notice).toContain("added 6 stories");
    expect(notice).toContain("used 1 of your monthly agent runs");
  });

  it("singularises one story and still states the charge", () => {
    const notice = buildUploadNotice({
      version: 6,
      storyExtractionRequested: true,
      storyExtraction: { created: 1 },
    });
    expect(notice).toContain("added 1 story ");
    expect(notice).toContain("used 1 of your monthly agent runs");
  });
});

/**
 * The helpers above are only worth having if the shipped screen actually uses
 * them — the defect was the screen's own inlined copy. These pin the real
 * Settings client (same source-reading convention as
 * `__tests__/dashboard/live-stats.test.ts`).
 */
describe("F-03 the Settings screen itself", () => {
  const source = readFileSync(
    join(__dirname, "../../app/dashboard/settings/settings-client.tsx"),
    "utf8",
  );

  it("no longer claims unconditionally that story extraction ran", () => {
    expect(source).not.toContain("story extraction ran.");
  });

  it("renders the pre-upload cost disclosure and builds the notice from the response", () => {
    expect(source).toContain("EXTRACTION_OPT_IN_LABEL");
    expect(source).toContain("buildUploadNotice");
  });

  it("only asks the server to extract when the user opted in", () => {
    expect(source).toContain('form.append("extract_stories"');
    expect(source).toContain("extractStories");
  });
});
