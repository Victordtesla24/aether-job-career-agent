import { describe, expect, it } from "vitest";

import type { Approval } from "../../../lib/api/approvals";
import {
  EXPIRY_HOURS,
  companyInitials,
  isExpired,
  metaLine,
  parseApprovalPayload,
  summarize,
} from "../lib";

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "a1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: {},
    createdAt: new Date().toISOString(),
    resolvedAt: null,
    ...overrides,
  };
}

describe("parseApprovalPayload", () => {
  it("returns type-based defaults for an empty payload", () => {
    const details = parseApprovalPayload(approval());
    expect(details.agent).toBe("Application Agent");
    expect(details.action).toBe("submit an application");
    expect(details.confidence).toBeNull();
    expect(details.reasoning).toEqual([]);
    expect(details.preview).toBeNull();
    expect(details.initials).toBe("CV");
  });

  it("uses per-type defaults for email and offer approvals", () => {
    expect(parseApprovalPayload(approval({ type: "email_send" })).action).toBe("send an email");
    expect(parseApprovalPayload(approval({ type: "offer_response" })).agent).toBe(
      "Negotiation Agent",
    );
  });

  it("reads the full wireframe payload", () => {
    const details = parseApprovalPayload(
      approval({
        payload: {
          agent: "Tailoring Agent",
          action: "submit an application",
          job_title: "Senior ML Engineer",
          company: "Canva",
          location: "Sydney",
          source: "LinkedIn",
          initials: "CV",
          confidence: 0.91,
          why: "Above salary target.",
          reasoning: [
            { kind: "check", text: "7 of 8 required skills matched" },
            { kind: "warning", text: "One claim is inferred" },
          ],
          preview: "Dear Canva Hiring Team…",
        },
      }),
    );
    expect(details.agent).toBe("Tailoring Agent");
    expect(details.jobTitle).toBe("Senior ML Engineer");
    expect(details.confidence).toBe(91);
    expect(details.reasoning).toHaveLength(2);
    expect(details.reasoning[1].kind).toBe("warning");
    expect(details.initials).toBe("CV");
  });

  it("normalizes confidence from fractions and percentages, rejecting junk", () => {
    const conf = (confidence: unknown) =>
      parseApprovalPayload(approval({ payload: { confidence } })).confidence;
    expect(conf(0.876)).toBe(88);
    expect(conf(96)).toBe(96);
    expect(conf(1)).toBe(100);
    expect(conf(140)).toBeNull();
    expect(conf(-2)).toBeNull();
    expect(conf("91%")).toBeNull();
    expect(conf(NaN)).toBeNull();
  });

  it("clamps out-of-range confidence to null instead of a nonsensical percentage (MV-approval-modal-004)", () => {
    const conf = (confidence: unknown) =>
      parseApprovalPayload(approval({ payload: { confidence } })).confidence;
    // 1.5 is neither a valid [0,1] fraction (>1) nor a genuine already-scaled
    // percentage (real percentages are always whole numbers) — must not
    // render as a misleading "2%".
    expect(conf(1.5)).toBeNull();
    expect(conf(2.3)).toBeNull();
    // Whole-number percentages just above 1 remain valid.
    expect(conf(2)).toBe(2);
  });

  it("accepts plain-string reasoning items and drops malformed entries", () => {
    const details = parseApprovalPayload(
      approval({ payload: { reasoning: ["ATS score 96", { kind: "warning" }, 42, { text: "ok" }] } }),
    );
    expect(details.reasoning).toEqual([
      { kind: "check", text: "ATS score 96" },
      { kind: "check", text: "ok" },
    ]);
  });
});

describe("companyInitials", () => {
  it("takes two letters from single-word companies", () => {
    expect(companyInitials("Canva")).toBe("CA");
  });
  it("takes first letters of two-word companies", () => {
    expect(companyInitials("Atlassian Corp")).toBe("AC");
  });
  it("falls back to CV without a company", () => {
    expect(companyInitials(null)).toBe("CV");
  });
});

describe("isExpired", () => {
  const now = Date.parse("2026-07-10T12:00:00Z");
  it("is false just inside the window and true just outside", () => {
    const fresh = approval({
      createdAt: new Date(now - (EXPIRY_HOURS * 3600 * 1000 - 60_000)).toISOString(),
    });
    const stale = approval({
      createdAt: new Date(now - (EXPIRY_HOURS * 3600 * 1000 + 60_000)).toISOString(),
    });
    expect(isExpired(fresh, now)).toBe(false);
    expect(isExpired(stale, now)).toBe(true);
  });
  it("never marks resolved approvals expired", () => {
    const old = approval({
      status: "approved",
      createdAt: new Date(now - 100 * 3600 * 1000).toISOString(),
    });
    expect(isExpired(old, now)).toBe(false);
  });
});

describe("summarize / metaLine", () => {
  it("describes an application approval with its target", () => {
    const a = approval({ payload: { job_title: "Senior ML Engineer", company: "Canva" } });
    expect(summarize(a)).toBe("Application for Senior ML Engineer @ Canva");
  });
  it("labels cover-letter payloads", () => {
    const a = approval({ payload: { kind: "cover_letter", job_title: "SE", company: "Vercel" } });
    expect(summarize(a)).toBe("Cover letter for SE @ Vercel");
  });
  it("builds the company · location · via source meta line", () => {
    const details = parseApprovalPayload(
      approval({ payload: { company: "Canva", location: "Sydney", source: "LinkedIn" } }),
    );
    expect(metaLine(details)).toBe("Canva · Sydney · via LinkedIn");
  });
  it("omits missing meta segments", () => {
    const details = parseApprovalPayload(approval({ payload: { company: "Canva" } }));
    expect(metaLine(details)).toBe("Canva");
  });
});
