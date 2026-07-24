/**
 * W-E quality sweep — locale regression tests (QUALITY-WE ledger wave).
 *
 * Aether is an Australian product: all user-facing dates must render in
 * en-AU (day-first), never the runtime's default locale (which renders
 * US-style "7/23/2026" on the prod host). These tests pin the shared
 * helpers to en-AU so a locale regression fails CI instead of shipping.
 */
import { describe, expect, it } from "vitest";

import { formatAud, formatDate, formatDateTime } from "../format";

describe("formatDate (en-AU)", () => {
  it("renders day-first Australian dates, not US month-first", () => {
    expect(formatDate("2026-07-23T10:00:00Z")).toBe("23/07/2026");
  });

  it("keeps the em-dash fallback for null/invalid", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not-a-date")).toBe("—");
  });
});

describe("formatDateTime (en-AU)", () => {
  it("renders a day-first date component", () => {
    // Time-of-day varies with host TZ; the date part must be day-first.
    expect(formatDateTime("2026-07-23T10:00:00Z")).toMatch(/^23\/07\/2026/);
  });
});

describe("formatAud", () => {
  it("renders whole dollars without cents", () => {
    expect(formatAud(39)).toBe("$39");
  });
});
