import { describe, expect, it } from "vitest";

import type { Approval } from "../../../lib/api/approvals";
import {
  EXPIRY_HOURS,
  FIDELITY_CHECKING,
  FIDELITY_FETCH_FAILED,
  canRemove,
  companyInitials,
  isExpired,
  metaLine,
  parseApprovalPayload,
  previewLabel,
  summarize,
  withLiveFidelity,
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

describe("canRemove (FEAT-B1)", () => {
  const now = Date.parse("2026-07-10T12:00:00Z");
  it("is false for a live (non-expired) pending approval — still actionable", () => {
    const fresh = approval({ createdAt: new Date(now - 3600 * 1000).toISOString() });
    expect(canRemove(fresh, now)).toBe(false);
  });
  it("is true for an expired pending approval", () => {
    const stale = approval({
      createdAt: new Date(now - (EXPIRY_HOURS + 1) * 3600 * 1000).toISOString(),
    });
    expect(canRemove(stale, now)).toBe(true);
  });
  it("is true for resolved approvals regardless of age", () => {
    const approved = approval({ status: "approved", createdAt: new Date(now).toISOString() });
    const rejected = approval({ status: "rejected", createdAt: new Date(now).toISOString() });
    expect(canRemove(approved, now)).toBe(true);
    expect(canRemove(rejected, now)).toBe(true);
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
  it("labels resume-tailor payloads distinctly from cover letters (MV-resume-studio-001)", () => {
    const a = approval({
      payload: { kind: "resume_tailor", job_title: "SE", company: "Vercel" },
    });
    expect(summarize(a)).toBe("Tailored résumé for SE @ Vercel");
    // Both share the application_submit type but must never collide in labeling.
    expect(previewLabel(a)).toBe("Tailored résumé changes");
  });
  it("keeps the cover-letter preview label for cover-letter approvals", () => {
    const a = approval({ payload: { kind: "cover_letter" } });
    expect(previewLabel(a)).toBe("Generated cover letter");
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

// ML-U2B-approval-honesty ruling 2: a PENDING resume_tailor approval's
// frozen "Original layout" reasoning line must be superseded by the
// résumé's LIVE fidelity where it is displayed — the exact live-sampled
// defect (SONNET-COHERENCE-REREVIEW-20260814.md F4): 2/3 real approvals
// showed a green "Verified: Original layout preserved" claim for a résumé
// whose real fidelity was `formatPreserved: false`.
describe("withLiveFidelity", () => {
  const frozenReasoning = [
    { kind: "check" as const, text: "Every reworded bullet is grounded in your résumé." },
    { kind: "check" as const, text: "Original layout: pending — the mechanism claims preservation." },
  ];

  it("supersedes the frozen layout line with the live, verified value", () => {
    const a = approval({ status: "pending", payload: { kind: "resume_tailor", resume_id: "r1" } });
    const result = withLiveFidelity(a, frozenReasoning, {
      preserved: false,
      note: "Rendered in the Aether template; original layout preservation is not yet available.",
    });
    expect(result[0]).toEqual(frozenReasoning[0]);
    expect(result[1]).toEqual({
      kind: "warning",
      text: "Original layout: Rendered in the Aether template; original layout preservation is not yet available.",
    });
    // Never the false affirmative claim, even though the frozen text was written honestly-pending.
    expect(result[1].text.toLowerCase()).not.toContain("original layout preserved");
  });

  it("renders a check when the live fidelity genuinely confirms preservation", () => {
    const a = approval({ status: "pending", payload: { kind: "resume_tailor", resume_id: "r1" } });
    const result = withLiveFidelity(a, frozenReasoning, {
      preserved: true,
      note: "All 2 tailored changes were verified present in the file you download.",
    });
    expect(result[1].kind).toBe("check");
  });

  it("is a no-op when the live fidelity has not resolved yet", () => {
    const a = approval({ status: "pending", payload: { kind: "resume_tailor", resume_id: "r1" } });
    expect(withLiveFidelity(a, frozenReasoning, null)).toEqual(frozenReasoning);
  });

  it("never touches a resolved (historical) approval's frozen reasoning (ruling 3)", () => {
    const a = approval({ status: "approved", payload: { kind: "resume_tailor", resume_id: "r1" } });
    const result = withLiveFidelity(a, frozenReasoning, { preserved: false, note: "reflow" });
    expect(result).toEqual(frozenReasoning);
  });

  it("never touches a non-resume_tailor approval", () => {
    const a = approval({ status: "pending", payload: { kind: "cover_letter" } });
    const result = withLiveFidelity(a, frozenReasoning, { preserved: false, note: "reflow" });
    expect(result).toEqual(frozenReasoning);
  });

  it("is a no-op when no layout line exists to supersede", () => {
    const a = approval({ status: "pending", payload: { kind: "resume_tailor", resume_id: "r1" } });
    const noLayout = [frozenReasoning[0]];
    expect(withLiveFidelity(a, noLayout, { preserved: false, note: "reflow" })).toEqual(noLayout);
  });

  // MF-A (round-5 re-review): FIDELITY_CHECKING must supersede the frozen
  // claim with an honest in-flight state — never the green "check" the
  // frozen text renders as, and never left as a no-op the way `live ===
  // null` is (that would be the exact bug: the frozen "Verified" claim
  // still on screen for the whole fetch window).
  it("supersedes the frozen claim with the CHECKING sentinel while the fetch is in flight", () => {
    const a = approval({ status: "pending", payload: { kind: "resume_tailor", resume_id: "r1" } });
    const result = withLiveFidelity(a, frozenReasoning, FIDELITY_CHECKING);
    expect(result[1]).toEqual({
      kind: "checking",
      text: "Checking this version's layout fidelity…",
    });
    expect(result[1].text.toLowerCase()).not.toContain("original layout preserved");
  });

  // FIDELITY_CHECKING and FIDELITY_FETCH_FAILED share the same
  // `preserved: null` shape — withLiveFidelity must tell them apart by
  // identity, not degrade a genuine in-flight check into the "warning"
  // styling a real failure gets (or vice versa).
  it("renders CHECKING and FETCH_FAILED distinctly even though both carry preserved: null", () => {
    const a = approval({ status: "pending", payload: { kind: "resume_tailor", resume_id: "r1" } });
    const checking = withLiveFidelity(a, frozenReasoning, FIDELITY_CHECKING);
    const failed = withLiveFidelity(a, frozenReasoning, FIDELITY_FETCH_FAILED);
    expect(checking[1].kind).toBe("checking");
    expect(failed[1].kind).toBe("warning");
    expect(checking[1].kind).not.toBe(failed[1].kind);
  });
});
