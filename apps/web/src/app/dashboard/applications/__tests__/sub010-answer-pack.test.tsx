// @vitest-environment jsdom
/**
 * SUB-010 — the SMART SHORTLIST: one honest screen for a manual application,
 * and the 'needs your click' filter that finds them.
 *
 * LEDGER: *"read-only GET /applications/{id}/answer-pack fusing profile +
 * answer bank + resume + cover for every manual job, + a 'needs your click'
 * filter. Buildable from existing parts. Honesty contract: never claims
 * applied."*
 *
 * THE DEVIATION. The board had no way to isolate the applications that are
 * prepared but not transmitted — the ones whose last step is the user's own
 * click — and no surface that fused the four things Aether already holds for
 * that job (profile fields, banked answers, the tailored résumé, the cover
 * letter). The user re-assembled them by hand from four screens.
 *
 * WHAT IS PINNED HERE
 * 1. The filter isolates exactly the SUB-006 prepared-but-not-transmitted set
 *    — the predicate is IMPORTED, never re-derived, so the filter and the
 *    card badge can never disagree about what counts as sent.
 * 2. The pack opens from those cards, and shows every part the API returned.
 * 3. Honest absence: a missing résumé/cover/answer is rendered as the API's
 *    absence sentence, never as an empty box and never as a fabricated value.
 * 4. The honesty contract in COPY: no string this screen authors about a
 *    prepared row says applied / submitted / sent.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FILTER_OPTIONS,
  NEEDS_YOUR_CLICK_LABEL,
  STAGE_DEFS,
  cardMatchesFilter,
  isPreparedNotTransmitted,
  viewStages,
  type StageCard,
} from "../../../../components/applications/tracker-lib";
import ApplicationsPage from "../page";

const apiRequest = vi.fn();
const downloadResume = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// The résumé in the pack is an artifact REFERENCE resolved through the
// authenticated résumé client (`GET /resumes/{id}/download`) — the same
// renderer the Studio's own download button uses, so the document named on the
// panel is byte-for-byte the one an employer would receive.
vi.mock("../../../../lib/api/resumes", () => ({
  downloadResume: (...args: unknown[]) => downloadResume(...args),
}));

/** A claim word this screen may not use about a row with no transmission. */
const CLAIM_RE = /\b(applied|submitted|sent)\b/i;

const BASE_APP = {
  jobId: "job-1",
  resumeId: "resume-1",
  status: "submitted",
  coverLetter: "Dear Northwind hiring team,",
  jobTitle: "Staff Platform Engineer",
  company: "Northwind Systems",
  applyUrl: "https://www.seek.com.au/job/8811",
  createdAt: "2026-08-10T00:00:00Z",
  updatedAt: "2026-08-14T00:00:00Z",
  answers: {},
  fitScore: 92,
  autoSubmittable: false,
  applyEmail: null,
  applyEmailSource: null,
};

/** The production shape: status says submitted, nothing proves a send. */
const PREPARED = {
  ...BASE_APP,
  id: "app-prepared",
  transmitted: false,
  submissionState: "not_transmitted",
  transmittedAt: null,
  transmittedTo: null,
  transmissionChannel: null,
  transmissionRef: null,
};

/** A row with real proof — it is NOT waiting on the user's click. */
const TRANSMITTED = {
  ...BASE_APP,
  id: "app-transmitted",
  jobId: "job-2",
  company: "Harbourline Labs",
  transmitted: true,
  submissionState: "transmitted",
  transmittedAt: "2026-08-14T09:00:00Z",
  transmittedTo: "careers@harbourline.example",
  transmissionChannel: "greenhouse",
  transmissionRef: "evidence/app-transmitted.png",
};

/** An employer has replied — reinterpreting this row would be its own lie. */
const IN_INTERVIEW = {
  ...BASE_APP,
  id: "app-interview",
  jobId: "job-3",
  company: "Rivermouth Data",
  status: "interview",
  transmitted: false,
  submissionState: "not_transmitted",
  transmittedAt: null,
  transmittedTo: null,
  transmissionChannel: null,
  transmissionRef: null,
};

/** The pack the API returns for `app-prepared`. */
const PACK = {
  applicationId: "app-prepared",
  jobId: "job-1",
  jobTitle: "Staff Platform Engineer",
  company: "Northwind Systems",
  applyUrl: "https://www.seek.com.au/job/8811",
  honesty: {
    transmitted: false,
    claim: "prepared",
    statement:
      "Aether has NOT transmitted this application anywhere. Everything below is " +
      "material Aether prepared for you, ready to copy into the employer's own " +
      "form — the click is still yours.",
    readOnly: true,
    note: "Opening this pack changes nothing and contacts no employer.",
    evidenceRef: null,
    transmittedAt: null,
  },
  profile: {
    fields: [
      {
        key: "fullName",
        label: "Full name",
        value: "Priya Raman",
        present: true,
        source: "your Aether account",
        absence: null,
      },
      {
        key: "email",
        label: "Email",
        value: "priya.raman@example.com",
        present: true,
        source: "your Aether account",
        absence: null,
      },
      {
        key: "github",
        label: "GitHub",
        value: null,
        present: false,
        source: null,
        absence: "No GitHub URL on file — add it under Career Data or to your résumé.",
      },
    ],
    presentCount: 2,
    missingCount: 1,
    otherResumeContactLines: [],
  },
  answers: {
    entries: [
      {
        question: "Why Northwind Systems?",
        questionSource: "employer_form",
        sensitivity: "factual",
        answered: true,
        answer: "Your platform work.",
        answerSource: "this_application",
        bankedQuestion: null,
        matchConfidence: 1,
        matchMethod: "exact",
        wouldAutoSend: true,
        gateReason: "Aether may reuse this factual answer.",
        absence: null,
      },
      {
        question: "What are your salary expectations?",
        questionSource: "likely_for_any_application",
        sensitivity: "judgement",
        answered: false,
        answer: null,
        answerSource: null,
        bankedQuestion: null,
        matchConfidence: null,
        matchMethod: null,
        wouldAutoSend: false,
        gateReason: "A judgement answer stays with you until you opt it in.",
        absence:
          "You have not answered this yet, and Aether will not invent an answer.",
      },
    ],
    answeredCount: 1,
    unansweredCount: 1,
    note: "Answers are your own words, stored exactly as you wrote them.",
  },
  resume: {
    present: true,
    resumeId: "resume-tailored",
    version: 2,
    label: "Northwind — tailored",
    tailoredToThisJob: true,
    downloadPath: "/resumes/resume-tailored/download",
    updatedAt: "2026-08-13T00:00:00Z",
    absence: null,
  },
  coverLetter: {
    present: true,
    text: "Dear Northwind hiring team,",
    characterCount: 27,
    downloadPath: null,
    absence: null,
  },
};

/** The same pack with both artifacts missing — honest absence, clause 1. */
const EMPTY_PACK = {
  ...PACK,
  resume: {
    present: false,
    resumeId: null,
    version: null,
    label: null,
    tailoredToThisJob: false,
    downloadPath: null,
    updatedAt: null,
    absence: "There is no job-tailored résumé for this role yet.",
  },
  coverLetter: {
    present: false,
    text: null,
    characterCount: 0,
    downloadPath: null,
    absence: "There is no cover-letter draft for this application yet.",
  },
};

function mockBoard(apps: Array<Record<string, unknown>>, pack: unknown = PACK) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/applications") return apps;
    if (path === "/jobs") return [];
    if (path.startsWith("/approvals")) return [];
    if (path === "/workspaces/settings") {
      return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
    }
    if (path === "/applications/funnel/sankey") {
      return { stages: [], dropoffs: [], insight: "" };
    }
    if (path.endsWith("/answer-pack")) return pack;
    const match = apps.find((a) => path === `/applications/${String(a.id)}`);
    if (match) return match;
    return {};
  });
}

function cardOf(app: Record<string, unknown>): StageCard {
  return {
    id: String(app.id),
    title: String(app.jobTitle),
    company: String(app.company),
    updatedAt: String(app.updatedAt),
    meta: {},
    app: app as never,
  };
}

/** Open the Filter menu and choose the 'needs your click' option. */
async function chooseNeedsYourClick(): Promise<void> {
  fireEvent.click(await screen.findByTestId("filter-btn"));
  fireEvent.click(
    await screen.findByRole("menuitemradio", { name: NEEDS_YOUR_CLICK_LABEL }),
  );
}

beforeEach(() => {
  // The real client returns a promise; the panel awaits it so a failed
  // download is reported rather than swallowed.
  downloadResume.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  apiRequest.mockReset();
  downloadResume.mockReset();
});

describe("SUB-010 — the 'needs your click' filter (clause 2)", () => {
  it("offers the filter, worded as a click that is still owed", () => {
    const option = FILTER_OPTIONS.find((o) => o.key === "needs-your-click");
    expect(option).toBeDefined();
    expect(option!.label).toBe(NEEDS_YOUR_CLICK_LABEL);
    expect(NEEDS_YOUR_CLICK_LABEL).not.toMatch(CLAIM_RE);
  });

  it("isolates exactly the prepared-but-not-transmitted rows", () => {
    expect(cardMatchesFilter(cardOf(PREPARED), "needs-your-click")).toBe(true);
    expect(cardMatchesFilter(cardOf(TRANSMITTED), "needs-your-click")).toBe(false);
    expect(cardMatchesFilter(cardOf(IN_INTERVIEW), "needs-your-click")).toBe(false);
  });

  it("uses the SUB-006 predicate itself rather than a second opinion", () => {
    for (const app of [PREPARED, TRANSMITTED, IN_INTERVIEW]) {
      expect(cardMatchesFilter(cardOf(app), "needs-your-click")).toBe(
        isPreparedNotTransmitted(app),
      );
    }
  });

  it("never claims a pipeline card is waiting on a click it cannot receive", () => {
    // A card with no application behind it (a discovered job) has nothing
    // prepared, so it cannot be in the set.
    const jobCard: StageCard = {
      id: "job-9",
      title: "Platform Lead",
      company: "Southbank Freight",
      updatedAt: "2026-08-14T00:00:00Z",
      meta: {},
    };
    expect(cardMatchesFilter(jobCard, "needs-your-click")).toBe(false);
  });

  it("filters every stage of the board through the same predicate", () => {
    // The real submitted lane, filled with one row of each kind.
    const submitted = STAGE_DEFS.find((d) => d.key === "submitted")!;
    const stages = [
      { ...submitted, cards: [cardOf(PREPARED), cardOf(TRANSMITTED)] },
    ];
    const filtered = viewStages(stages, "needs-your-click", "recent");
    expect(filtered[0].cards.map((c) => c.id)).toEqual(["app-prepared"]);
  });

  it("shows only the rows whose click is outstanding, on the rendered board", async () => {
    mockBoard([PREPARED, TRANSMITTED, IN_INTERVIEW]);
    render(<ApplicationsPage />);
    await screen.findByTestId("prepared-not-sent-badge");
    expect(screen.getByText("Harbourline Labs")).toBeTruthy();

    await chooseNeedsYourClick();

    expect(screen.getByText("Northwind Systems")).toBeTruthy();
    expect(screen.queryByText("Harbourline Labs")).toBeNull();
    expect(screen.queryByText("Rivermouth Data")).toBeNull();
  });
});

describe("SUB-010 — the fused pack (clauses 1 and 3)", () => {
  it("opens from the card that needs the click and fuses all four parts", async () => {
    mockBoard([PREPARED]);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("answer-pack-btn"));

    const panel = await screen.findByTestId("answer-pack-panel");
    expect(apiRequest).toHaveBeenCalledWith(
      "/applications/app-prepared/answer-pack",
      expect.anything(),
    );

    // profile
    expect(within(panel).getByText("priya.raman@example.com")).toBeTruthy();
    // answer bank — the employer's own question and the user's own answer
    expect(within(panel).getByText("Why Northwind Systems?")).toBeTruthy();
    expect(within(panel).getByText("Your platform work.")).toBeTruthy();
    // résumé artifact reference — the tailored version for THIS job, opened
    // through the authenticated download path rather than a bare link.
    const resumeLink = within(panel).getByTestId("answer-pack-resume-link");
    expect(resumeLink.getAttribute("data-download-path")).toBe(
      "/resumes/resume-tailored/download",
    );
    expect(within(panel).getByText("Northwind — tailored")).toBeTruthy();
    fireEvent.click(resumeLink);
    expect(downloadResume).toHaveBeenCalledWith("resume-tailored");
    // cover letter
    expect(within(panel).getByText("Dear Northwind hiring team,")).toBeTruthy();
  });

  it("states that nothing was transmitted, and claims nothing else", async () => {
    mockBoard([PREPARED]);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("answer-pack-btn"));
    const panel = await screen.findByTestId("answer-pack-panel");

    expect(within(panel).getByTestId("answer-pack-honesty").textContent).toContain(
      "NOT transmitted",
    );

    // Every word on the panel that is not verbatim user/employer content is
    // Aether's own copy about a row with no transmission — it may not claim
    // one. The two verbatim strings this fixture carries are excluded by
    // value, because quoting them faithfully IS the contract.
    const rendered = (panel.textContent ?? "")
      .replace(PACK.answers.entries[0].answer!, "")
      .replace(PACK.coverLetter.text!, "");
    expect(rendered).not.toMatch(CLAIM_RE);
  });

  it("reports a missing résumé and cover letter as absent, inventing neither", async () => {
    mockBoard([PREPARED], EMPTY_PACK);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("answer-pack-btn"));
    const panel = await screen.findByTestId("answer-pack-panel");

    expect(within(panel).queryByTestId("answer-pack-resume-link")).toBeNull();
    expect(within(panel).getByText(EMPTY_PACK.resume.absence)).toBeTruthy();
    expect(within(panel).getByText(EMPTY_PACK.coverLetter.absence)).toBeTruthy();
  });

  it("shows an unanswered question as unanswered, with no suggestion", async () => {
    mockBoard([PREPARED]);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("answer-pack-btn"));
    const panel = await screen.findByTestId("answer-pack-panel");

    const unanswered = within(panel).getByTestId(
      "answer-pack-entry-what-are-your-salary-expectations",
    );
    expect(unanswered.textContent).toContain(PACK.answers.entries[1].absence);
    expect(unanswered.textContent).not.toContain("AUD");
  });

  it("says an answer would not travel unattended when the bank's gate is shut", async () => {
    mockBoard([PREPARED]);
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("answer-pack-btn"));
    const panel = await screen.findByTestId("answer-pack-panel");

    const gated = within(panel).getByTestId(
      "answer-pack-entry-what-are-your-salary-expectations",
    );
    expect(gated.textContent).toContain(PACK.answers.entries[1].gateReason);
  });

  it("is not offered on a row that was really transmitted", async () => {
    mockBoard([TRANSMITTED]);
    render(<ApplicationsPage />);
    await screen.findByTestId("submission-transmitted-badge");
    expect(screen.queryByTestId("answer-pack-btn")).toBeNull();
  });

  it("reports a failed load honestly instead of an empty pack", async () => {
    mockBoard([PREPARED]);
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/applications") return [PREPARED];
      if (path === "/jobs") return [];
      if (path.startsWith("/approvals")) return [];
      if (path === "/workspaces/settings") {
        return { agentConfig: { autoApply: false, approvalGate: true, matchThreshold: 85 } };
      }
      if (path.endsWith("/answer-pack")) throw new Error("request failed");
      return {};
    });
    render(<ApplicationsPage />);
    fireEvent.click(await screen.findByTestId("answer-pack-btn"));

    const error = await screen.findByTestId("answer-pack-error");
    expect(error.textContent).toContain("request failed");
  });
});
