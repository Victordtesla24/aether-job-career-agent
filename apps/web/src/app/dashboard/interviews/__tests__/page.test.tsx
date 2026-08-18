// @vitest-environment jsdom
/**
 * MV-interview-center-001 / -003 regression guard (/dashboard/interviews).
 *
 * The screen was a static "No interview scheduled" placeholder that never
 * called any of its 7 backend endpoints, and there was no UI anywhere to
 * schedule an interview. These tests render the REAL InterviewCenterPage
 * against a mocked apiRequest and assert:
 *   1. it GETs /interviews and renders the real rows (role/company/status), and
 *   2. the "Schedule interview" form POSTs to /interviews and the new interview
 *      round-trips into the list, then a status transition (complete) hits the
 *      real endpoint and updates the card.
 *
 * A regression that reverts the page to a static placeholder fails here.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();

vi.mock("../../../../lib/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

// eslint-disable-next-line import/first
import InterviewCenterPage from "../page";

const APP_FIXTURE = {
  id: "app-1",
  jobId: "job-1",
  resumeId: "resume-1",
  status: "interview",
  coverLetter: null,
  jobTitle: "Senior Product Owner",
  company: "Acme Corp",
  applyUrl: null,
  createdAt: "2026-07-10T00:00:00Z",
  updatedAt: "2026-07-14T00:00:00Z",
};

interface WireInterview {
  id: string;
  user_id: string;
  application_id: string | null;
  type: string;
  status: string;
  scheduled_at: string;
  duration_minutes: number;
  location: string | null;
  meeting_link: string | null;
  notes: string | null;
  contact_name: string | null;
  contact_email: string | null;
  created_at: string;
  updated_at: string;
}

let interviews: WireInterview[] = [];
let seq = 0;

function makeInterview(body: Record<string, unknown>): WireInterview {
  seq += 1;
  return {
    id: `iv-${seq}`,
    user_id: "u-1",
    application_id: (body.application_id as string) ?? null,
    type: (body.type as string) ?? "video",
    status: "scheduled",
    scheduled_at: (body.scheduled_at as string) ?? "2026-08-01T15:00:00.000Z",
    duration_minutes: (body.duration_minutes as number) ?? 60,
    location: (body.location as string) ?? null,
    meeting_link: (body.meeting_link as string) ?? null,
    notes: (body.notes as string) ?? null,
    contact_name: (body.contact_name as string) ?? null,
    contact_email: (body.contact_email as string) ?? null,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  };
}

beforeEach(() => {
  interviews = [];
  seq = 0;
  apiRequest.mockReset();
  apiRequest.mockImplementation(async (path: string, options: { method?: string; body?: unknown } = {}) => {
    const method = options.method ?? "GET";
    if (path === "/applications") return [APP_FIXTURE];
    if (path === "/interviews" && method === "GET") return [...interviews];
    if (path === "/interviews" && method === "POST") {
      const iv = makeInterview((options.body ?? {}) as Record<string, unknown>);
      interviews.push(iv);
      return iv;
    }
    const complete = path.match(/^\/interviews\/(.+)\/complete$/);
    if (complete && method === "POST") {
      interviews = interviews.map((i) =>
        i.id === complete[1] ? { ...i, status: "completed" } : i,
      );
      return interviews.find((i) => i.id === complete[1]);
    }
    const cancel = path.match(/^\/interviews\/(.+)\/cancel$/);
    if (cancel && method === "POST") {
      interviews = interviews.map((i) =>
        i.id === cancel[1] ? { ...i, status: "cancelled" } : i,
      );
      return interviews.find((i) => i.id === cancel[1]);
    }
    throw new Error(`unexpected apiRequest(${method} ${path})`);
  });
});

afterEach(() => cleanup());

describe("Interview Center — real backend wiring (MV-interview-center-001/003)", () => {
  it("GETs /interviews and renders real rows (role, company, status)", async () => {
    interviews = [
      makeInterview({
        application_id: "app-1",
        type: "onsite",
        scheduled_at: "2026-08-02T09:30:00.000Z",
        notes: "Research the payments org.",
      }),
    ];

    render(<InterviewCenterPage />);

    const card = await screen.findByTestId("interview-card");
    expect(apiRequest).toHaveBeenCalledWith("/interviews", expect.anything());
    // Real fields render — not a hardcoded empty state.
    expect(within(card).getByText(/Senior Product Owner/)).not.toBeNull();
    expect(within(card).getByText(/Acme Corp/)).not.toBeNull();
    expect(within(card).getByText(/Research the payments org\./)).not.toBeNull();
    expect(within(card).getByTestId("interview-status").textContent).toContain("scheduled");
    // The old static placeholder copy is gone.
    expect(screen.queryByTestId("interviews-empty-state")).toBeNull();
  });

  it("schedules an interview that round-trips into the list, then completes it", async () => {
    render(<InterviewCenterPage />);

    // Starts empty (honest empty state after a real fetch that returned []).
    await screen.findByTestId("interviews-empty-state");

    // Open the create affordance and fill the form.
    fireEvent.click(screen.getByTestId("schedule-interview-btn"));
    const form = await screen.findByTestId("schedule-interview-form");
    fireEvent.change(within(form).getByTestId("interview-application-select"), {
      target: { value: "app-1" },
    });
    fireEvent.change(within(form).getByTestId("interview-scheduled-at"), {
      target: { value: "2026-08-01T15:00" },
    });
    fireEvent.click(within(form).getByTestId("interview-submit-btn"));

    // Round-trip: the new interview now appears in the list.
    const card = await screen.findByTestId("interview-card");
    expect(within(card).getByText(/Senior Product Owner/)).not.toBeNull();

    // A real POST /interviews fired with the scoped application id + ISO time.
    const post = apiRequest.mock.calls.find(
      ([p, o]) => p === "/interviews" && (o as { method?: string })?.method === "POST",
    );
    expect(post).toBeDefined();
    const body = (post![1] as { body: Record<string, unknown> }).body;
    expect(body.application_id).toBe("app-1");
    expect(typeof body.scheduled_at).toBe("string");
    expect(body.scheduled_at as string).toMatch(/T.*Z$/);

    // Status transition: mark complete -> real endpoint -> card updates.
    fireEvent.click(within(card).getByTestId("interview-complete-btn"));
    const status = await screen.findByTestId("interview-status");
    expect(status.textContent).toContain("completed");
    expect(apiRequest).toHaveBeenCalledWith(
      expect.stringMatching(/^\/interviews\/iv-1\/complete$/),
      expect.objectContaining({ method: "POST" }),
    );
  });
});

// ===========================================================================
// Interview Prep panel (ML-W4B-OBS-1, orchestrator-ruled: wave-4B incomplete
// until user-visible).
//
// FACT: GET /workspaces/interviews/prep works end-to-end on the backend (real
// per-job question briefs with story-grounded STAR+R answer sketches, plus a
// questionsNote when the only brief on file belongs to another job — see
// apps/api/app/routers/workspaces.py and
// apps/api/tests/test_ml_w4b_interview_panel_attribution.py) but NO shipped
// frontend file ever requested it. These tests fail against the pre-fix page
// (it never calls the endpoint, so the panel never appears) and pass once the
// panel is wired to fetch when an application is at the interview stage.
// ===========================================================================

interface PrepFixtureOverrides {
  questions?: unknown[];
  questionsNote?: string | null;
  briefing?: Record<string, unknown> | null;
  pack?: Record<string, unknown> | null;
  session?: Record<string, unknown>;
}

function makePrepFixture(overrides: PrepFixtureOverrides = {}) {
  return {
    session: {
      role: "Senior Product Owner",
      company: "Acme Corp",
      round: "Active Interview",
      scheduledFor: null,
      format: "Check your calendar for details",
      jobId: "job-1",
      location: null,
      ...(overrides.session ?? {}),
    },
    compliance: {
      message: "Live Assist is disabled by default during interviews.",
      level: "warning",
    },
    brief: {
      columns: [{ title: "Company", items: ["Acme Corp"] }],
      insight:
        "Fit score: 88%. Review the job description and your application " +
        "answers for key talking points.",
    },
    questions: overrides.questions ?? [],
    questionsNote: overrides.questionsNote ?? null,
    briefing: overrides.briefing ?? null,
    pack: overrides.pack ?? null,
    liveAssist: {
      enabled: false,
      fillerWordsPerMin: 0,
      wordsPerMin: 0,
      talkListenRatio: { talk: 50, listen: 50 },
      coachingCue: null,
    },
    debrief: null,
  };
}

const GROUNDED_QUESTION = {
  question: "How did you scale delivery across multiple squads?",
  category: "behavioural",
  whyAsked: "The posting asks for delivery at scale.",
  suggestedStoryId: "story-1",
  suggestedStoryTitle: "ANZ 30% delivery efficiency",
  answerSketch: {
    situation: "The ANZ platform team had a 6-week release cadence.",
    task: "I owned cutting that to weekly releases.",
    action: "I introduced trunk-based development and automated canary rollouts.",
    result: "Release cadence dropped to weekly with 30% fewer rollback incidents.",
    reflection: "I'd invest in the canary tooling even earlier next time.",
  },
  preparationNote: null,
  guardActions: [],
};

let applicationsFixture: Record<string, unknown>[] = [APP_FIXTURE];
let prepFixture: ReturnType<typeof makePrepFixture> = makePrepFixture();

describe("Interview Prep panel (ML-W4B-OBS-1)", () => {
  beforeEach(() => {
    applicationsFixture = [APP_FIXTURE];
    prepFixture = makePrepFixture();
    interviews = [
      makeInterview({
        application_id: "app-1",
        type: "onsite",
        scheduled_at: "2026-08-02T09:30:00.000Z",
      }),
    ];
    apiRequest.mockReset();
    apiRequest.mockImplementation(
      async (path: string, options: { method?: string; body?: unknown } = {}) => {
        const method = options.method ?? "GET";
        if (path === "/applications") return applicationsFixture;
        if (path === "/interviews" && method === "GET") return [...interviews];
        if (path === "/workspaces/interviews/prep" && method === "GET") return prepFixture;
        if (path.startsWith("/workspaces/interviews/pack") && method === "POST") {
          prepFixture = makePrepFixture({
            questions: prepFixture.questions,
            briefing: {
              logistics: ["Face to face at Docklands office"],
              traps: [{ title: "Unanswered question", detail: "When did you finish with the ATO?" }],
              questionsToAsk: ["Where has the tender actually got to?"],
              guidelines: ["Arrive ten minutes early."],
            },
            pack: {
              folder: "Interview pack — Acme Corp — Senior Product Owner",
              files: [
                {
                  name: "01-interview-prep.pdf",
                  kind: "interview_prep",
                  branded: true,
                  agent: "interviewPrep",
                  note: "Aether-branded brief.",
                },
                {
                  name: "02-interview-slides.pdf",
                  kind: "slides",
                  branded: true,
                  agent: "interviewPrep",
                  note: "Four landscape slides.",
                },
              ],
              gaps: ["No job-tailored résumé for this role yet."],
              plan: ["companyResearch", "interviewPrep", "tailor", "coverLetter"],
            },
          });
          return { files: prepFixture.pack?.files ?? [], gaps: prepFixture.pack?.gaps ?? [] };
        }
        if (path === "/agents/interviewPrep/run" && method === "POST") {
          prepFixture = makePrepFixture({ questions: [GROUNDED_QUESTION] });
          return {
            jobId: "job-1",
            predictedQuestions: prepFixture.questions,
            message: "1 predicted question(s) for Senior Product Owner at Acme Corp.",
          };
        }
        throw new Error(`unexpected apiRequest(${method} ${path})`);
      },
    );
  });

  it("fetches the prep brief when an application is at the interview stage and shows the honest empty state with a Run affordance", async () => {
    render(<InterviewCenterPage />);

    await screen.findByTestId("interview-prep-panel");
    expect(apiRequest).toHaveBeenCalledWith(
      "/workspaces/interviews/prep",
      expect.anything(),
    );
    const empty = await screen.findByTestId("interview-prep-empty");
    expect(empty.textContent).toMatch(/No prep brief yet — run the Interview Prep agent/);
    expect(screen.getByTestId("interview-prep-run-btn")).not.toBeNull();
  });

  it("still fetches the prep brief when a schedule exists even if the application list has not caught up", async () => {
    applicationsFixture = [{ ...APP_FIXTURE, status: "screening" }];

    render(<InterviewCenterPage />);

    await screen.findByTestId("interview-prep-panel");
    expect(apiRequest).toHaveBeenCalledWith(
      "/workspaces/interviews/prep",
      expect.anything(),
    );
  });

  it("does not fetch the prep brief when there are no interviews and no interview-stage application", async () => {
    applicationsFixture = [{ ...APP_FIXTURE, status: "screening" }];
    interviews = [];

    render(<InterviewCenterPage />);

    await screen.findByTestId("interviews-empty-state");
    expect(apiRequest).not.toHaveBeenCalledWith(
      "/workspaces/interviews/prep",
      expect.anything(),
    );
    expect(screen.queryByTestId("interview-prep-panel")).toBeNull();
  });

  it("renders a question with whyAsked and a story-grounded STAR+R answer sketch, linked to the suggested story", async () => {
    prepFixture = makePrepFixture({ questions: [GROUNDED_QUESTION] });

    render(<InterviewCenterPage />);

    const card = await screen.findByTestId("interview-prep-question");
    expect(within(card).getByText(/How did you scale delivery/)).not.toBeNull();
    expect(within(card).getByText(/The posting asks for delivery at scale\./)).not.toBeNull();

    const sketch = within(card).getByTestId("interview-prep-answer-sketch");
    expect(within(sketch).getByText(/6-week release cadence/)).not.toBeNull();
    expect(within(sketch).getByText(/30% fewer rollback incidents/)).not.toBeNull();

    const storyLink = within(card).getByTestId("interview-prep-story-link");
    expect(storyLink.textContent).toMatch(/ANZ 30% delivery efficiency/);
    expect(storyLink.getAttribute("href")).toBe("/dashboard/stories");
  });

  it('renders the honest "no matching story" state when a question has no answer sketch', async () => {
    prepFixture = makePrepFixture({
      questions: [
        {
          question: "Describe a time you managed regulatory risk.",
          category: "behavioural",
          whyAsked: "The posting mentions compliance obligations.",
          suggestedStoryId: null,
          suggestedStoryTitle: null,
          answerSketch: null,
          preparationNote:
            "No story in your Story Bank supports an answer here yet — prepare " +
            "one (situation, task, action, result, then what you would do " +
            "differently) before the interview.",
          guardActions: [],
        },
      ],
    });

    render(<InterviewCenterPage />);

    const card = await screen.findByTestId("interview-prep-question");
    expect(within(card).queryByTestId("interview-prep-answer-sketch")).toBeNull();
    const noStory = within(card).getByTestId("interview-prep-no-story");
    expect(noStory.textContent).toMatch(/prepare one/i);
  });

  it("renders questionsNote when the only brief on file belongs to another job", async () => {
    prepFixture = makePrepFixture({
      questions: [],
      questionsNote:
        "Your most recent interview prep was generated for a different job " +
        "(Staff Data Engineer) — those questions were predicted from another " +
        "posting, so they are not shown as this interview's prep. Run " +
        "Interview Prep for this role to get questions for it.",
    });

    render(<InterviewCenterPage />);

    const note = await screen.findByTestId("interview-prep-questions-note");
    expect(note.textContent).toMatch(/Staff Data Engineer/);
  });

  it("running Interview Prep from the empty state calls the agent then refetches the brief", async () => {
    render(<InterviewCenterPage />);
    await screen.findByTestId("interview-prep-empty");

    fireEvent.click(screen.getByTestId("interview-prep-run-btn"));

    const card = await screen.findByTestId("interview-prep-question");
    expect(within(card).getByText(/How did you scale delivery/)).not.toBeNull();
    expect(apiRequest).toHaveBeenCalledWith(
      "/agents/interviewPrep/run",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.queryByTestId("interview-prep-empty")).toBeNull();
    expect(apiRequest).toHaveBeenCalledWith(
      expect.stringMatching(/^\/workspaces\/interviews\/pack/),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("renders the interview folder, traps and questions to ask from the orchestrator pack", async () => {
    prepFixture = makePrepFixture({
      session: { format: "Face to face", scheduledFor: "2026-08-19T00:00:00.000Z", location: "Docklands office" },
      briefing: {
        logistics: ["Face to face at Docklands office"],
        traps: [{ title: "Unanswered question", detail: "When did you finish with the ATO?" }],
        questionsToAsk: ["Where has the tender actually got to?"],
        guidelines: ["Arrive ten minutes early."],
      },
      pack: {
        folder: "Interview pack — Next Business Energy — Project Manager",
        files: [
          {
            name: "01-interview-prep.pdf",
            kind: "interview_prep",
            branded: true,
            agent: "interviewPrep",
            note: "Aether-branded brief.",
          },
        ],
        gaps: ["No cover letter for this application yet."],
        plan: ["companyResearch", "interviewPrep", "tailor", "coverLetter"],
      },
    });

    render(<InterviewCenterPage />);

    const meta = await screen.findByTestId("interview-prep-session-meta");
    expect(meta.textContent).toMatch(/Face to face/);
    expect(screen.getByTestId("interview-pack-folder").textContent).toMatch(
      /Interview pack — Next Business Energy/,
    );
    expect(screen.getByTestId("interview-pack-file").textContent).toMatch(/01-interview-prep\.pdf/);
    expect(screen.getByTestId("interview-prep-briefing").textContent).toMatch(/ATO/);
    expect(screen.getByTestId("interview-pack-gaps").textContent).toMatch(/cover letter/i);
  });

  it("Assemble folder POSTs the orchestrator pack endpoint", async () => {
    render(<InterviewCenterPage />);
    await screen.findByTestId("interview-pack-empty");
    fireEvent.click(screen.getByTestId("interview-pack-assemble-btn"));
    const folder = await screen.findByTestId("interview-pack-files");
    expect(folder.textContent).toMatch(/01-interview-prep\.pdf/);
    expect(apiRequest).toHaveBeenCalledWith(
      expect.stringMatching(/^\/workspaces\/interviews\/pack/),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
