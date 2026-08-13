/**
 * U2a — pure helpers backing the Settings → Resume Management baseline copy
 * (R-F1/R-F3/MON-012). Side-effect-free, so tested without a DOM (same
 * convention as `resume-upload-quota-disclosure.test.ts`).
 */
import { describe, expect, it } from "vitest";

import {
  BASELINE_HELP_TEXT,
  describeUploadError,
  ORIGINAL_NOT_STORED_LABEL,
  ORIGINAL_STORED_LABEL,
} from "../../components/settings/resume-upload";

describe("U2a baseline help text", () => {
  it("names every format Aether genuinely reads", () => {
    expect(BASELINE_HELP_TEXT).toMatch(/PDF \(\.pdf\)/);
    expect(BASELINE_HELP_TEXT).toMatch(/Word \(\.docx\)/);
    expect(BASELINE_HELP_TEXT).toMatch(/plain text \(\.txt\/\.md\)/);
  });

  it("states the immutable-baseline guarantee", () => {
    expect(BASELINE_HELP_TEXT).toMatch(/immutable baseline/i);
    expect(BASELINE_HELP_TEXT).toMatch(/tailoring never alters it/i);
  });

  it("honestly flags that pre-existing uploads have no stored original", () => {
    expect(BASELINE_HELP_TEXT).toMatch(/before this feature existed/i);
    expect(BASELINE_HELP_TEXT).toMatch(/re-upload it to enable format preservation/i);
  });
});

describe("U2a original-stored badge labels", () => {
  it("the positive label reads as a genuine confirmation", () => {
    expect(ORIGINAL_STORED_LABEL).toMatch(/Original stored/);
  });

  it("the negative label tells the user the exact remedy", () => {
    expect(ORIGINAL_NOT_STORED_LABEL).toMatch(/Re-upload/);
    expect(ORIGINAL_NOT_STORED_LABEL).toMatch(/format preservation/);
  });
});

describe("U2a describeUploadError (MON-012 verbatim rejection copy)", () => {
  it("returns a plain-string detail verbatim, unmodified", () => {
    const detail = "Unsupported file format. Aether reads PDF (.pdf), Word (.docx)...";
    expect(describeUploadError(422, JSON.stringify({ detail }))).toBe(detail);
  });

  it("bounds an unexpectedly long detail rather than rendering it unbounded", () => {
    const longDetail = "x".repeat(500);
    const result = describeUploadError(422, JSON.stringify({ detail: longDetail }));
    expect(result.length).toBeLessThanOrEqual(300);
    expect(result.endsWith("…")).toBe(true);
    expect(longDetail.startsWith(result.slice(0, -1))).toBe(true);
  });

  it("falls back to an honest status-only message for a non-JSON body", () => {
    expect(describeUploadError(413, "")).toBe("Upload failed (HTTP 413). Please try again.");
    expect(describeUploadError(502, "<html>Bad Gateway</html>")).toBe(
      "Upload failed (HTTP 502). Please try again.",
    );
  });

  it("falls back honestly when detail is present but not a string (e.g. a Pydantic array)", () => {
    const result = describeUploadError(422, JSON.stringify({ detail: [{ msg: "field required" }] }));
    expect(result).toBe("Upload failed (HTTP 422). Please try again.");
  });
});
