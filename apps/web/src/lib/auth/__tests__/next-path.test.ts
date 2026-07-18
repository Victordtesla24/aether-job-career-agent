/**
 * safeNextPath — open-redirect-safe post-login return path (MV-login-002).
 * RED first: lib/auth/next-path.ts does not exist yet.
 */
import { describe, expect, it } from "vitest";

import { safeNextPath } from "../next-path";

describe("safeNextPath", () => {
  it("defaults to /dashboard for empty/absent input", () => {
    expect(safeNextPath(null)).toBe("/dashboard");
    expect(safeNextPath(undefined)).toBe("/dashboard");
    expect(safeNextPath("")).toBe("/dashboard");
  });

  it("preserves dashboard sub-routes and query strings", () => {
    expect(safeNextPath("/dashboard")).toBe("/dashboard");
    expect(safeNextPath("/dashboard/jobs")).toBe("/dashboard/jobs");
    expect(safeNextPath("/dashboard/resume-studio?tab=ats")).toBe(
      "/dashboard/resume-studio?tab=ats",
    );
    expect(safeNextPath("/dashboard?view=x")).toBe("/dashboard?view=x");
  });

  it("decodes an encoded dashboard path", () => {
    expect(safeNextPath(encodeURIComponent("/dashboard/jobs"))).toBe("/dashboard/jobs");
  });

  it("rejects open-redirect and out-of-scope targets", () => {
    for (const evil of [
      "//evil.com",
      "https://evil.com",
      "http://evil.com/dashboard",
      "\\\\evil.com",
      "/dashboardevil.com", // prefix-boundary bypass
      "/dashboard-admin",
      "/admin",
      "/etc/passwd",
      "/login",
      "javascript:alert(1)",
    ]) {
      expect(safeNextPath(evil)).toBe("/dashboard");
    }
  });

  it("rejects path traversal (encoded or literal)", () => {
    expect(safeNextPath("/dashboard/../../admin")).toBe("/dashboard");
    expect(safeNextPath("/dashboard/..%2f..%2fadmin")).toBe("/dashboard");
  });

  it("falls back on malformed percent-encoding without throwing", () => {
    expect(safeNextPath("%E0%A4")).toBe("/dashboard");
  });
});
