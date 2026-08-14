// @vitest-environment jsdom
/**
 * ML-U2B-approval-honesty ruling 2, component level (round-4 re-review MF-2).
 *
 * `lib.test.ts` locks the PURE `withLiveFidelity` helper only. Nothing
 * rendered `ApprovalModal` itself to prove: (a) the live
 * `GET /resumes/{id}/fidelity` fetch actually fires for a pending
 * `resume_tailor` approval, (b) it is keyed by `payload.resume_id`, (c) a
 * successful response supersedes the frozen "Original layout preserved"
 * claim in the rendered DOM, (d) a FAILED fetch renders the honest-unknown
 * warning rather than leaving the frozen green "Verified" claim on screen
 * (MF-1 — the exact false-claim pattern this slice exists to kill), and
 * (e) resolved/non-`resume_tailor` approvals never fetch at all.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Approval } from "../../../lib/api/approvals";

const fetchResumeFidelityMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/resumes", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/resumes")>();
  return {
    ...actual,
    fetchResumeFidelity: (...args: unknown[]) => fetchResumeFidelityMock(...args),
  };
});

// eslint-disable-next-line import/first
import { ApprovalModal } from "../ApprovalModal";

const FROZEN_CLAIM =
  "Original layout preserved — the source PDF's format hash is carried through untouched.";

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-1",
    userId: "u1",
    applicationId: null,
    type: "application_submit",
    status: "pending",
    payload: {
      kind: "resume_tailor",
      resume_id: "resume-42",
      job_title: "Backend Engineer",
      company: "Acme",
      reasoning: [
        { kind: "check", text: "Every reworded bullet is grounded in your résumé." },
        { kind: "check", text: FROZEN_CLAIM },
      ],
    },
    createdAt: new Date().toISOString(),
    resolvedAt: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  fetchResumeFidelityMock.mockReset();
});

describe("ApprovalModal live fidelity fetch", () => {
  it("fetches the résumé's live fidelity for a pending resume_tailor approval, keyed by payload.resume_id", async () => {
    fetchResumeFidelityMock.mockResolvedValue({
      resume_id: "resume-42",
      formatPreserved: false,
      method: "reflow-template",
      confidence: "low",
      note: "Rendered in the Aether template; original layout preservation is not yet available for this upload type.",
    });

    render(<ApprovalModal approval={approval()} onClose={vi.fn()} onDecide={vi.fn()} />);

    await waitFor(() => expect(fetchResumeFidelityMock).toHaveBeenCalledTimes(1));
    expect(fetchResumeFidelityMock).toHaveBeenCalledWith("resume-42");
  });

  it("supersedes the frozen claim with the live fidelity note once the fetch resolves", async () => {
    fetchResumeFidelityMock.mockResolvedValue({
      resume_id: "resume-42",
      formatPreserved: false,
      method: "reflow-template",
      confidence: "low",
      note: "Rendered in the Aether template; original layout preservation is not yet available for this upload type.",
    });

    render(<ApprovalModal approval={approval()} onClose={vi.fn()} onDecide={vi.fn()} />);

    const list = await screen.findByTestId("modal-reasoning");
    await waitFor(() =>
      expect(list.textContent).toContain(
        "Rendered in the Aether template; original layout preservation is not yet available for this upload type.",
      ),
    );
    expect(list.textContent).not.toContain(FROZEN_CLAIM);
    const supersededItem = screen
      .getByText(/Rendered in the Aether template/)
      .closest("li");
    // formatPreserved: false -> warning, never the green check.
    expect(supersededItem?.querySelector(".fa-triangle-exclamation")).toBeTruthy();
    expect(supersededItem?.querySelector(".fa-check")).toBeFalsy();
  });

  it("MF-1: renders the honest-unknown warning, never the frozen green check, when the fidelity fetch FAILS", async () => {
    fetchResumeFidelityMock.mockRejectedValue(new Error("network error"));

    render(<ApprovalModal approval={approval()} onClose={vi.fn()} onDecide={vi.fn()} />);

    const list = await screen.findByTestId("modal-reasoning");
    await waitFor(() => expect(list.textContent).toMatch(/could not be verified/i));

    // The exact false claim this slice exists to kill must never survive a
    // fetch failure.
    expect(list.textContent).not.toContain(FROZEN_CLAIM);
    const supersededItem = screen.getByText(/could not be verified/i).closest("li");
    expect(supersededItem?.querySelector(".fa-triangle-exclamation")).toBeTruthy();
    expect(supersededItem?.querySelector(".fa-check")).toBeFalsy();
  });

  it("never fetches live fidelity for a resolved (historical) resume_tailor approval", async () => {
    render(
      <ApprovalModal
        approval={approval({ status: "approved", resolvedAt: new Date().toISOString() })}
        onClose={vi.fn()}
        onDecide={vi.fn()}
      />,
    );

    await screen.findByTestId("modal-reasoning");
    // Give any (incorrect) effect a microtask/macrotask to have fired.
    await waitFor(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(fetchResumeFidelityMock).not.toHaveBeenCalled();
  });

  it("never fetches live fidelity for a non-resume_tailor approval", async () => {
    render(
      <ApprovalModal
        approval={approval({ payload: { kind: "cover_letter", job_title: "Backend Engineer" } })}
        onClose={vi.fn()}
        onDecide={vi.fn()}
      />,
    );

    await screen.findByTestId("approval-modal");
    await waitFor(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(fetchResumeFidelityMock).not.toHaveBeenCalled();
  });

  // MF-A (round-5 re-review): built from the reviewer's never-settling-mock
  // probe (u2b-r5-probe-20260814/reviewer-probe-failure-paths.test.tsx PROBE
  // A), which proved the frozen "Original layout preserved" claim rendered
  // as a green "Verified" check for the fetch's entire in-flight window —
  // indefinitely, on a hang, since nothing bounded it. Unlike that probe
  // (which documented the bug), this asserts the FIXED behavior: the CHECKING
  // sentinel, never the frozen claim, for as long as the fetch is
  // unresolved — including synchronously on the very first render, before
  // any effect has had a chance to run.
  it("MF-A: a fetch that never settles shows the CHECKING state, never the frozen green claim, from the first paint onward", async () => {
    fetchResumeFidelityMock.mockImplementation(() => new Promise(() => {}));

    render(<ApprovalModal approval={approval()} onClose={vi.fn()} onDecide={vi.fn()} />);

    // Synchronous: the very first render already seeded CHECKING — no tick,
    // no effect flush, needed to avoid the frozen claim.
    const list = screen.getByTestId("modal-reasoning");
    expect(list.textContent).not.toContain(FROZEN_CLAIM);
    expect(list.textContent).toContain("Checking this version's layout fidelity");
    const checkingItem = screen
      .getByText(/Checking this version's layout fidelity/)
      .closest("li");
    expect(checkingItem?.querySelector(".fa-check")).toBeFalsy();
    expect(checkingItem?.querySelector(".fa-triangle-exclamation")).toBeFalsy();
    expect(checkingItem?.querySelector(".fa-circle-notch")).toBeTruthy();

    // Still true well after mount (the reviewer probe's hang window) — no
    // late flip back to the frozen claim, and no fake "Verified" green
    // check invented just because time passed.
    await new Promise((resolve) => setTimeout(resolve, 250));
    const stillChecking = screen.getByTestId("modal-reasoning");
    expect(stillChecking.textContent).not.toContain(FROZEN_CLAIM);
    expect(stillChecking.textContent).toContain("Checking this version's layout fidelity");
  });

  it("MF-A: switching this modal to a different pending resume_tailor approval reseeds CHECKING synchronously, never showing the new approval's frozen claim", async () => {
    fetchResumeFidelityMock.mockImplementation(() => new Promise(() => {}));
    const reasoningWithFrozenClaim = [
      { kind: "check", text: "Every reworded bullet is grounded in your résumé." },
      { kind: "check", text: FROZEN_CLAIM },
    ];
    const first = approval({
      id: "appr-1",
      payload: { kind: "resume_tailor", resume_id: "resume-42", reasoning: reasoningWithFrozenClaim },
    });
    const second = approval({
      id: "appr-2",
      payload: { kind: "resume_tailor", resume_id: "resume-99", reasoning: reasoningWithFrozenClaim },
    });

    const { rerender } = render(
      <ApprovalModal approval={first} onClose={vi.fn()} onDecide={vi.fn()} />,
    );
    await screen.findByTestId("modal-reasoning");

    rerender(<ApprovalModal approval={second} onClose={vi.fn()} onDecide={vi.fn()} />);
    const list = screen.getByTestId("modal-reasoning");
    expect(list.textContent).not.toContain(FROZEN_CLAIM);
    expect(list.textContent).toContain("Checking this version's layout fidelity");
  });
});
