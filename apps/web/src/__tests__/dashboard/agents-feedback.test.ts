/**
 * Unit tests for the Agents console feedback helpers (UX defect fix).
 * Covers start/progress/completion notices and error mapping (503/422/401).
 */
import { describe, expect, it } from "vitest";

import {
  PIPELINE_ORDER,
  agentSuccessNotice,
  pipelineCompletionNotice,
  pipelineProgressNotice,
  pipelineStartNotice,
  runErrorNotice,
} from "../../lib/agents-feedback";

describe("pipelineStartNotice", () => {
  it("gives immediate info feedback mentioning Scout and expected duration", () => {
    const n = pipelineStartNotice();
    expect(n.kind).toBe("info");
    expect(n.text).toContain("Pipeline started");
    expect(n.text).toContain("Scout is discovering jobs");
    expect(n.text).toContain("30–120 seconds");
  });
});

describe("pipelineProgressNotice", () => {
  it("reports step 1 (supervisor) when nothing has completed yet", () => {
    const n = pipelineProgressNotice([]);
    expect(n.kind).toBe("info");
    expect(n.text).toContain("step 1 of 6");
    expect(n.text).toContain("Supervisor is planning");
  });

  it("advances to the next agent after earlier steps complete", () => {
    const n = pipelineProgressNotice(["supervisor", "scout", "fitScorer"]);
    expect(n.text).toContain("step 4 of 6");
    expect(n.text).toContain("Matcher is picking");
  });

  it("caps at the final step when everything has completed", () => {
    const n = pipelineProgressNotice([...PIPELINE_ORDER]);
    expect(n.text).toContain("step 6 of 6");
    expect(n.text).toContain("CoverLetter is drafting");
  });
});

describe("pipelineCompletionNotice", () => {
  it("summarizes results and links to Approvals when approval is required", () => {
    const n = pipelineCompletionNotice({
      status: "awaiting_approval",
      approvalRequired: true,
      steps: [
        { agent: "supervisor", output: { plan: PIPELINE_ORDER.slice(1) } },
        { agent: "scout", output: { persisted: 3 } },
        { agent: "fitScorer", output: { scored: 5 } },
        {
          agent: "matcher",
          output: { matched: 4, top_job_title: "Data Analyst", top_company: "Acme" },
        },
        { agent: "tailor", output: { changes: 9 } },
        { agent: "coverLetter", output: { approvalRequired: true } },
      ],
    });
    expect(n.kind).toBe("success");
    expect(n.text).toContain("4 jobs matched");
    expect(n.text).toContain("5 newly scored");
    expect(n.text).toContain("9 changes");
    expect(n.text).toContain("cover letter drafted");
    expect(n.text).toContain("Data Analyst @ Acme");
    expect(n.href).toBe("/dashboard/approvals");
  });

  it("guides the user to Jobs when no jobs matched", () => {
    const n = pipelineCompletionNotice({
      status: "completed",
      approvalRequired: false,
      steps: [
        { agent: "scout", output: { persisted: 0 } },
        { agent: "matcher", output: { matched: 0 } },
      ],
    });
    expect(n.kind).toBe("success");
    expect(n.text).toContain("no jobs matched yet");
    expect(n.href).toBe("/dashboard/jobs");
  });
});

describe("agentSuccessNotice", () => {
  it("points scout results at the Jobs screen", () => {
    const n = agentSuccessNotice("scout", { persisted: 7 });
    expect(n.text).toContain("7 new jobs discovered");
    expect(n.href).toBe("/dashboard/jobs");
  });

  it("handles a scout run with nothing new", () => {
    const n = agentSuccessNotice("scout", { persisted: 0 });
    expect(n.text).toContain("no new jobs this time");
  });

  it("points tailor results at Resume Studio", () => {
    const n = agentSuccessNotice("tailor", { changes: 12 });
    expect(n.text).toContain("12 accepted changes");
    expect(n.href).toBe("/dashboard/resume");
  });

  it("points coverLetter results at Approvals", () => {
    const n = agentSuccessNotice("coverLetter", {});
    expect(n.href).toBe("/dashboard/approvals");
  });

  it("falls back to a generic success for unknown agents", () => {
    const n = agentSuccessNotice("outreach", {});
    expect(n.text).toContain("outreach finished successfully");
    expect(n.href).toBeUndefined();
  });
});

describe("runErrorNotice", () => {
  it("maps 503 to budget/retry guidance", () => {
    const n = runErrorNotice({ status: 503 }, "Pipeline");
    expect(n.kind).toBe("error");
    expect(n.text).toContain("time budget was exceeded");
    expect(n.text).toContain("press the button again");
  });

  it("maps 422 to run-Scout-first guidance with a Jobs link", () => {
    const n = runErrorNotice({ status: 422 }, "Tailor");
    expect(n.text).toContain("run Scout to discover jobs");
    expect(n.href).toBe("/dashboard/jobs");
  });

  it("maps 401 to a reload prompt", () => {
    const n = runErrorNotice({ status: 401 }, "Pipeline");
    expect(n.text).toContain("session expired");
  });

  it("includes the error message and RECENT RUNS pointer for unknown failures", () => {
    const n = runErrorNotice(new Error("boom"), "Scout");
    expect(n.text).toContain("(boom)");
    expect(n.text).toContain("RECENT RUNS");
  });
});
