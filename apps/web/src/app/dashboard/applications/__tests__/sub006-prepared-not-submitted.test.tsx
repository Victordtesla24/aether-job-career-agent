// @vitest-environment jsdom
/**
 * SUB-006 — swimlane honesty: `status = 'submitted'` with `transmittedAt`
 * NULL is PREPARED, never SUBMITTED.
 *
 * GROUND TRUTH (production, 2026-08-16): the database holds 5 applications.
 * ALL FIVE carry `status = 'submitted'`, and ZERO of them carry a
 * `transmittedAt`. Every one of those cards sat in a lane whose word is
 * "Submitted" and whose per-card stage badge repeated that word as its
 * tooltip — a claim that five real job applications were sent, with nothing
 * in the database able to support any of them.
 *
 * The stored status is the user's own tracker history and is NOT rewritten
 * (they may well have applied by hand). What changes is the CLAIM the card
 * makes: the honest word for "artifacts ready, nothing transmitted" is
 * prepared, and the click is still the user's.
 *
 * This file pins BOTH halves: the pure derivation (so no surface has to
 * re-derive it) and the rendered board.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PREPARED_NOT_SENT_LABEL,
  isPreparedNotTransmitted,
  stageLabelForCard,
} from "../../../../components/applications/tracker-lib";
import { hasTransmissionProof } from "../../../../components/applications/submission-control-lib";
import ApplicationsPage from "../page";

const apiRequest = vi.fn();

// `vi.mock` is hoisted above every import by Vitest, so the page module below
// resolves the mocked client even though this call is written after it. The
// factory only CLOSES OVER `apiRequest`; it dereferences it when a request is
// actually made, which is always inside a test, long after initialisation.
vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

const BASE_APP = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "submitted",
  coverLetter: "Dear Hiring Manager,",
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: "https://www.acme.example/careers/job?gh_jid=8569564002",
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
  answers: {},
  fitScore: 88,
  autoSubmittable: false,
  applyEmail: null,
  applyEmailSource: null,
};

/** The 5 live production rows: marked submitted, never transmitted. */
const PREPARED_ONLY = {
  ...BASE_APP,
  transmitted: false,
  submissionState: "not_transmitted",
  transmittedAt: null,
  transmittedTo: null,
  transmissionChannel: null,
  transmissionRef: null,
};

/** A row with real proof — the ONLY shape allowed to read as submitted. */
const REALLY_TRANSMITTED = {
  ...BASE_APP,
  transmitted: true,
  submissionState: "transmitted",
  transmittedAt: "2026-08-14T09:00:00Z",
  transmittedTo: "careers@acme.example",
  transmissionChannel: "greenhouse",
  transmissionRef: "evidence/app-1.png",
};

function mockBoard(app: Record<string, unknown>) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/applications") return [app];
    if (path === "/jobs") return [];
    if (path.startsWith("/approvals")) return [];
    if (path === "/workspaces/settings") {
      return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
    }
    if (path === "/applications/funnel/sankey") {
      return { stages: [], dropoffs: [], insight: "" };
    }
    if (path.startsWith("/applications/app-1")) return app;
    return {};
  });
}

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
});

describe("SUB-006 — the prepared-vs-submitted derivation", () => {
  it("treats submitted-without-transmittedAt as prepared, not sent", () => {
    expect(isPreparedNotTransmitted({ status: "submitted", transmittedAt: null })).toBe(true);
    expect(isPreparedNotTransmitted({ status: "submitted" })).toBe(true);
  });

  it("a row with real transmission proof is NOT prepared-only", () => {
    expect(
      isPreparedNotTransmitted({ status: "submitted", transmittedAt: "2026-08-14T09:00:00Z" }),
    ).toBe(false);
  });

  it("uses exactly the proof predicate the submit control uses", () => {
    const row = { status: "submitted", transmittedAt: null };
    expect(isPreparedNotTransmitted(row)).toBe(!hasTransmissionProof(row));
  });

  it("leaves every other stage's word alone", () => {
    expect(stageLabelForCard("ready", PREPARED_ONLY)).toBe("Ready to Apply");
    expect(stageLabelForCard("in-review", { status: "screening", transmittedAt: null })).toBe(
      "In Review",
    );
    expect(stageLabelForCard("offer", { status: "offer", transmittedAt: null })).toBe("Offer");
  });

  it("never says 'Submitted' on a card with no transmission proof", () => {
    expect(stageLabelForCard("submitted", PREPARED_ONLY)).toBe(PREPARED_NOT_SENT_LABEL);
    expect(stageLabelForCard("submitted", PREPARED_ONLY)).not.toBe("Submitted");
  });

  it("still says 'Submitted' when the row really proves it", () => {
    expect(stageLabelForCard("submitted", REALLY_TRANSMITTED)).toBe("Submitted");
  });

  it("does not relabel a row the employer has already replied to", () => {
    // screening/interview/offer are the USER telling us an application is
    // live somewhere. Calling those "prepared" would be its own false claim.
    expect(isPreparedNotTransmitted({ status: "screening", transmittedAt: null })).toBe(false);
    expect(isPreparedNotTransmitted({ status: "interview", transmittedAt: null })).toBe(false);
  });
});

describe("SUB-006 — the rendered board", () => {
  it("badges a prepared-only application honestly on its swimlane card", async () => {
    mockBoard(PREPARED_ONLY);
    render(<ApplicationsPage />);
    const badge = await screen.findByTestId("prepared-not-sent-badge");
    expect(badge.textContent).toContain(PREPARED_NOT_SENT_LABEL);
  });

  it("the card's own stage badge does not claim 'Submitted'", async () => {
    mockBoard(PREPARED_ONLY);
    render(<ApplicationsPage />);
    await screen.findByTestId("prepared-not-sent-badge");
    const stageBadge = screen.getByTestId("card-stage-badge");
    expect(stageBadge.getAttribute("title")).toBe(PREPARED_NOT_SENT_LABEL);
    expect(stageBadge.getAttribute("title")).not.toBe("Submitted");
  });

  it("a really-transmitted application keeps the submitted wording", async () => {
    mockBoard(REALLY_TRANSMITTED);
    render(<ApplicationsPage />);
    await screen.findByTestId("submission-transmitted-badge");
    expect(screen.queryByTestId("prepared-not-sent-badge")).toBeNull();
    expect(screen.getByTestId("card-stage-badge").getAttribute("title")).toBe("Submitted");
  });
});
