// @vitest-environment jsdom
/**
 * ML-approvals-001 (MEDIUM) — the Approvals queue card preview shows only
 * letterhead lines for cover-letter/offer-response approvals, never the
 * substantive content, because it combines `whitespace-pre-line` with
 * `line-clamp-3` on text that always opens with several short letterhead
 * lines (uat/reports/evidence/models-live/screens/misc-dashboard/
 * TESTING-OUTCOME-REPORT.md).
 *
 * Real cover-letter payloads (apps/api/app/agents/cover_letter_agent.py
 * compose_letter()) always start:
 *   "<date>\n\nHiring Team\n<Company>\nRe: <role>\n\nDear Hiring Team at
 *   <Company>,\n\n<substantive paragraph>…"
 * apps/web/src/app/dashboard/approvals/page.tsx renders this VERBATIM
 * (`details.preview`, straight from `payload.preview`) in a
 * `className="mt-2 line-clamp-3 whitespace-pre-line …"` <p>. Because
 * `whitespace-pre-line` turns every `\n` into a forced line break and
 * `line-clamp-3` caps the card to 3 rendered lines, the visible card is
 * exhausted by "<date>" / "" / "Hiring Team" — three real, forced visual
 * lines — before the salutation or a single substantive word ever appears.
 * jsdom performs no real CSS layout, so this spec pins the DATA-level
 * contract that is provably true regardless of layout: the first 3
 * `\n`-delimited *segments* of whatever text the card renders — which
 * `white-space: pre-line` forces onto exactly the first 3 rendered visual
 * lines, since none of those segments is long enough to wrap on its own at
 * a card's width — must contain something OTHER than only letterhead.
 * (The full Review modal, `ApprovalModal.tsx`'s `data-testid="modal-preview"`,
 * uses `line-clamp-3` WITHOUT `whitespace-pre-line`, so ordinary
 * whitespace-collapsing already shows real content there — this spec is
 * scoped to the queue CARD only.)
 *
 * Fix intent (assigned, not implemented by this spec): the card should
 * derive a substantive excerpt (skip the letterhead / find the first real
 * paragraph) rather than piping the raw letter straight into a
 * `whitespace-pre-line` clamp.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../../lib/api/approvals";

const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../../lib/api/approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/approvals")>();
  return { ...actual, fetchApprovals: (...args: unknown[]) => fetchApprovalsMock(...args) };
});

// eslint-disable-next-line import/first
import ApprovalsPage from "../page";

/** A realistic cover-letter body, matching compose_letter()'s exact business-
 *  letter format (date / addressee block / Re: line / salutation / body /
 *  sign-off) — the same shape build_approval_extras() puts on `payload.preview`. */
function coverLetterPreview(company: string, role: string): string {
  return (
    `22 July 2026\n\n` +
    `Hiring Team\n${company}\n` +
    `Re: ${role}\n\n` +
    `Dear Hiring Team at ${company},\n\n` +
    `My background as a Business Analyst is a direct match for the ${role} role at ` +
    `${company}. My experience architecting AI/ML solutions for enterprise clients ` +
    `directly addresses the requirements in your posting.\n\n` +
    `I would welcome the opportunity to discuss how my background can contribute to your team.\n\n` +
    `Sincerely,\nJamie Rivera\n`
  );
}

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: {
      kind: "cover_letter",
      job_title: "Senior Product Manager",
      company: "Deputy",
      preview: coverLetterPreview("Deputy", "Senior Product Manager"),
    },
    createdAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    resolvedAt: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  fetchApprovalsMock.mockReset();
});

describe("ML-approvals-001: queue card preview must surface substantive content, not only letterhead", () => {
  it("the first 3 newline-delimited lines of a cover-letter card's preview are not ALL letterhead", async () => {
    fetchApprovalsMock.mockResolvedValue([approval()]);
    render(<ApprovalsPage />);

    const card = await screen.findByTestId("approval-card");
    // The rendered preview <p> is the one carrying both the whitespace-pre-line
    // and line-clamp-3 classes together — the exact CSS combination this
    // finding is about (distinguishing it from any other paragraph on the card).
    const previewEl = Array.from(card.querySelectorAll("p")).find(
      (p) => p.className.includes("whitespace-pre-line") && p.className.includes("line-clamp-3"),
    );
    expect(previewEl, "expected a whitespace-pre-line + line-clamp-3 preview <p> on the card").toBeTruthy();

    const rawText = previewEl!.textContent ?? "";
    // white-space: pre-line forces every "\n" onto its own rendered visual
    // line; line-clamp-3 then caps the card to the first 3 of those lines.
    // None of the letterhead segments below is long enough to itself wrap
    // at a card's width, so these first 3 "\n"-segments are exactly what a
    // real browser renders as the visible 3 lines.
    const firstThreeLines = rawText.split("\n").slice(0, 3).join(" ").trim();

    const looksSubstantive = /background|direct match|experience|welcome the opportunity/i.test(
      firstThreeLines,
    );
    expect(
      looksSubstantive,
      `card preview's first 3 visual lines are "${firstThreeLines}" — pure letterhead ` +
        `(date / blank / "Hiring Team"), never reaching the substantive body text that the ` +
        `same underlying payload.preview DOES contain further down`,
    ).toBe(true);
  });

  it("an offer_response card preview also surfaces substantive content in its first 3 lines", async () => {
    fetchApprovalsMock.mockResolvedValue([
      approval({
        id: "appr-2",
        type: "offer_response",
        payload: {
          job_title: "Staff Engineer",
          company: "Canva",
          preview: coverLetterPreview("Canva", "Staff Engineer"),
        },
      }),
    ]);
    render(<ApprovalsPage />);

    const card = await screen.findByTestId("approval-card");
    const previewEl = Array.from(card.querySelectorAll("p")).find(
      (p) => p.className.includes("whitespace-pre-line") && p.className.includes("line-clamp-3"),
    );
    expect(previewEl).toBeTruthy();

    const rawText = previewEl!.textContent ?? "";
    const firstThreeLines = rawText.split("\n").slice(0, 3).join(" ").trim();
    const looksSubstantive = /background|direct match|experience|welcome the opportunity/i.test(
      firstThreeLines,
    );
    expect(
      looksSubstantive,
      `offer_response card preview's first 3 visual lines are "${firstThreeLines}" — pure letterhead`,
    ).toBe(true);
  });
});
