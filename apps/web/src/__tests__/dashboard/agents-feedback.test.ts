/**
 * Unit tests for the Agents console feedback helpers (UX defect fix).
 * Covers start/progress/completion notices and error mapping (503/422/401).
 */
import { describe, expect, it } from "vitest";

import {
  PIPELINE_ORDER,
  agentSuccessNotice,
  missingResumeNotice,
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

  it("degrades gracefully when the cover letter was withheld (GAP-P7-COV-PIPE-001)", () => {
    const n = pipelineCompletionNotice({
      status: "completed",
      approvalRequired: false,
      coverLetterUnavailable: true,
      steps: [
        { agent: "scout", output: { persisted: 2 } },
        { agent: "fitScorer", output: { scored: 3 } },
        {
          agent: "matcher",
          output: { matched: 4, top_job_title: "Senior PM", top_company: "Deputy" },
        },
        { agent: "tailor", output: { changes: 7 } },
        { agent: "coverLetter", output: { coverLetterUnavailable: true, reason: "['origination']" } },
      ],
    });
    // Not a hard failure and not the empty "no jobs matched" branch: it reports
    // the real tailoring progress and points at the Cover Letter studio.
    expect(n.kind).toBe("info");
    expect(n.text).toContain("4 jobs matched");
    expect(n.text).toContain("7 changes");
    expect(n.text).toContain("Senior PM @ Deputy");
    expect(n.text).toContain("withheld");
    expect(n.text).not.toContain("no jobs matched yet");
    expect(n.href).toBe("/dashboard/cover-letters");
  });

  it("does not overclaim tailoring when cover withheld AND no résumé changes applied", () => {
    const n = pipelineCompletionNotice({
      status: "completed",
      approvalRequired: false,
      coverLetterUnavailable: true,
      steps: [
        { agent: "scout", output: { persisted: 1 } },
        { agent: "matcher", output: { matched: 2 } },
        { agent: "tailor", output: { noChangesApplied: true, changes: 0 } },
        { agent: "coverLetter", output: { coverLetterUnavailable: true } },
      ],
    });
    expect(n.text).not.toContain("resume was tailored");
    expect(n.text).toContain("no verifiable resume changes were applied");
    expect(n.href).toBe("/dashboard/cover-letters");
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

  it("falls back to run-Scout-first guidance with a Jobs link when no 422 detail is extractable", () => {
    const n = runErrorNotice({ status: 422 }, "Tailor");
    expect(n.text).toContain("run Scout to discover jobs");
    expect(n.href).toBe("/dashboard/jobs");
  });

  it("NF-final-closure-002: surfaces the real 422 detail instead of the hardcoded 'run Scout' line when one is extractable", () => {
    const err = Object.assign(
      new Error(
        'POST /agents/fit-scorer/run failed (422): {"detail":"Add your resume before scoring jobs against it."}',
      ),
      { status: 422 },
    );
    const n = runErrorNotice(err, "fitScorer");
    expect(n.text).toContain("Add your resume before scoring jobs against it.");
    expect(n.text).not.toContain("run Scout to discover jobs");
  });

  it("review regression (NF-final-closure-002): preserves the href-bearing Scout-guidance notice for resolveParams()'s CLIENT-SIDE synthetic zero-jobs 422 (a plain Error, no JSON body)", () => {
    // apps/web/src/app/dashboard/agents/page.tsx's resolveParams() throws
    // exactly this shape for trigger('tailor')/trigger('coverLetter') when
    // the user has zero jobs sourced — the ordinary, pre-existing
    // "run Scout first" scenario, NOT a genuine backend-returned 422 detail.
    // The fitScorer-detail fix above must not swallow this case: a raw,
    // non-JSON Error.message is not a real backend `detail` and must fall
    // through to the original href-bearing Scout guidance unchanged.
    const err = Object.assign(new Error("No jobs discovered yet"), { status: 422 });
    const n = runErrorNotice(err, "Tailor");
    expect(n.text).toContain("run Scout to discover jobs");
    expect(n.text).not.toContain("No jobs discovered yet");
    expect(n.href).toBe("/dashboard/jobs");
    expect(n.hrefLabel).toBe("open Jobs →");
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

describe("missingResumeNotice", () => {
  it("NF-final-closure-002: returns an honest non-success notice for the shared missingResume refusal shape", () => {
    const n = missingResumeNotice({
      resume_id: null,
      missingResume: true,
      message: "Add your resume before tailoring or generating an application.",
    });
    expect(n).not.toBeNull();
    expect(n?.kind).toBe("error");
    expect(n?.text).toBe("Add your resume before tailoring or generating an application.");
    expect(n?.href).toBe("/dashboard/resume");
  });

  it("falls back to a generic honest message when the backend omits `message`", () => {
    const n = missingResumeNotice({ resume_id: null, missingResume: true });
    expect(n?.text).toContain("Add your resume");
  });

  it("returns null for a real completed result (no overcorrection)", () => {
    expect(missingResumeNotice({ changes: 4 })).toBeNull();
    expect(missingResumeNotice({ persisted: 3 })).toBeNull();
    expect(missingResumeNotice({})).toBeNull();
  });

  it("returns null for the unrelated NoChangesApplied no-op shape", () => {
    // MV-adv-A-002: every proposed edit rejected by the fabrication guard is
    // a real, honest no-op completion — NOT a missing-résumé refusal — and
    // must keep rendering agentSuccessNotice's "0 accepted changes" text.
    expect(
      missingResumeNotice({
        resume_id: null,
        changes: 0,
        noChangesApplied: true,
        message: "Every proposed edit was rejected.",
      }),
    ).toBeNull();
  });
});
