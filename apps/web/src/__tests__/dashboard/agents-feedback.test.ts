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
  stopAllAgentsNotice,
  workflowAutoRetryWaitMs,
} from "../../lib/agents-feedback";
import { ApiError } from "../../lib/api/client";

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

  it("reports the AUD-COV-2 low-fit skip honestly instead of 'no jobs matched'", () => {
    const message =
      "No cover letter was auto-generated for this role: it scored 15 against " +
      "your profile, below your match threshold of 50. Adjust your match " +
      "threshold, or generate one yourself from the Cover Letter studio.";
    const n = pipelineCompletionNotice({
      status: "completed",
      approvalRequired: false,
      message,
      steps: [
        { agent: "scout", output: { persisted: 2 } },
        { agent: "fitScorer", output: { scored: 3 } },
        {
          agent: "matcher",
          output: { matched: 4, top_job_title: "Senior PM", top_company: "Deputy" },
        },
        { agent: "tailor", output: { changes: 7 } },
        {
          agent: "coverLetter",
          output: {
            skipped: true,
            reason: "below_match_threshold",
            fitScore: 15,
            matchThreshold: 50,
            message,
          },
        },
      ],
    });
    // A job WAS matched and the résumé WAS tailored — the pre-AUD-COV-2 code
    // would have fallen through to "no jobs matched yet", which is false.
    expect(n.kind).toBe("info");
    expect(n.text).toContain("4 jobs matched");
    expect(n.text).toContain("7 changes");
    expect(n.text).toContain("Senior PM @ Deputy");
    expect(n.text).toContain("below your match threshold of 50");
    expect(n.text).not.toContain("no jobs matched yet");
    expect(n.text).not.toContain("cover letter drafted");
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

  // F3 (agents-uplift/u5d re-review): the Submission Agent's honest terminal
  // states (submission_agent.py's STATE_* / `_describe`) must reach the
  // banner verbatim — a green "success" is reserved for `transmitted`, the
  // ONLY state backed by real transmission evidence. Every other state is a
  // neutral, honest banner carrying the backend's own message — never a
  // fabricated claim that something was sent.
  describe("submission", () => {
    it("renders success, naming the proof, ONLY when the backend proves a real transmission", () => {
      const n = agentSuccessNotice("submission", {
        submissionState: "transmitted",
        transmitted: true,
        transmissionRef: "ref-123",
        message: "Transmitted your application for Data Analyst at Acme (reference ref-123).",
      });
      expect(n.kind).toBe("success");
      expect(n.text).toBe(
        "Transmitted your application for Data Analyst at Acme (reference ref-123).",
      );
      expect(n.href).toBe("/dashboard/applications");
    });

    it("never renders success for recorded_not_transmitted — surfaces the honest NOT-transmitted message", () => {
      const n = agentSuccessNotice("submission", {
        submissionState: "recorded_not_transmitted",
        transmitted: false,
        message:
          "Recorded Data Analyst at Acme in your tracker as applied — NOT transmitted. Apply on the employer's site — this posting publishes no application address Aether can send to.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.kind).toBe("info");
      expect(n.text).toContain("NOT transmitted");
    });

    it("never renders success for awaiting_approval — points at Approvals, not a completed send", () => {
      const n = agentSuccessNotice("submission", {
        submissionState: "awaiting_approval",
        transmitted: false,
        message:
          "Recorded Data Analyst at Acme in your tracker and queued it for sending to jobs@acme.com — NOT transmitted yet. Approve it in Approvals to send.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.href).toBe("/dashboard/approvals");
      expect(n.text).toContain("NOT transmitted");
    });

    it("never renders success for manual_step_required", () => {
      const n = agentSuccessNotice("submission", {
        submissionState: "manual_step_required",
        transmitted: false,
        message:
          "NOT transmitted — Data Analyst at Acme needs a manual step (captcha required). Finish this application on the employer's site.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.text).toContain("NOT transmitted");
    });

    it("never renders success for no_change — the exact state the production false positives were in", () => {
      const n = agentSuccessNotice("submission", {
        submissionState: "no_change",
        transmitted: false,
        message:
          "No change — Data Analyst at Acme was already recorded in your tracker, and Aether has NOT transmitted it.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.text).toContain("NOT transmitted");
    });

    it("never renders success when nothing was ready to submit", () => {
      const n = agentSuccessNotice("submission", {
        submissionState: "none",
        reason: "nothing_ready",
        message:
          "No application is ready to submit yet — tailor a resume and generate a cover letter for a job first (or submit a specific job_id), then run this agent again.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.text).toContain("No application is ready");
    });

    it("never fabricates success copy even if the backend message is somehow missing", () => {
      const n = agentSuccessNotice("submission", { submissionState: "recorded_not_transmitted" });
      expect(n.kind).not.toBe("success");
      expect(n.text.toLowerCase()).toContain("nothing was transmitted");
    });
  });

  // Same illusion, different backend (F3 review's audit instruction): the
  // Email Agent's per-agent Run button dispatches `mode: "triage"` and, like
  // submission, computes an honest `connected`/`degraded`/`message` the FE
  // was discarding in favour of a blanket "emailAgent finished successfully."
  // — including when Gmail was never connected and zero emails were triaged.
  describe("emailAgent", () => {
    it("never renders success for a degraded (not-connected, or sync-failed) triage", () => {
      const n = agentSuccessNotice("emailAgent", {
        mode: "triage",
        connected: false,
        degraded: true,
        triaged: 0,
        message: "Connect Gmail to triage your recruiter inbox.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.text).toBe("Connect Gmail to triage your recruiter inbox.");
      expect(n.href).toBe("/dashboard/email");
    });

    it("never paints success or blames Gmail when triage degraded on a rate limit", () => {
      const n = agentSuccessNotice("emailAgent", {
        mode: "triage",
        connected: true,
        degraded: true,
        triaged: 12,
        message:
          "Sorted 12 career threads with the career filter (no AI scores this run). The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.",
      });
      expect(n.kind).not.toBe("success");
      expect(n.text).toContain("rate-limited");
      expect(n.text.toLowerCase()).not.toContain("gmail is not connected");
      expect(n.href).toBe("/dashboard/email");
      expect(n.hrefLabel).toBe("open Email Center →");
    });

    it("renders a genuine success for a real, connected triage", () => {
      const n = agentSuccessNotice("emailAgent", {
        mode: "triage",
        connected: true,
        degraded: false,
        triaged: 5,
        categories: { recruiter: 3, all: 2 },
        message: "Triaged 5 emails into 2 categories.",
      });
      expect(n.kind).toBe("success");
      expect(n.text).toBe("Triaged 5 emails into 2 categories.");
      expect(n.href).toBe("/dashboard/email");
    });
  });
});

describe("runErrorNotice", () => {
  it("maps 503 to budget/retry guidance", () => {
    const n = runErrorNotice({ status: 503 }, "Pipeline");
    expect(n.kind).toBe("error");
    expect(n.text).toContain("time budget was exceeded");
    expect(n.text).toContain("press the button again");
  });

  it("LOOP-429: copies Retry-After from a rate-limit 503 onto the notice", () => {
    const err = new ApiError(
      'POST /agents/tailor/run failed (503): {"detail":"The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings."}',
      503,
      60,
    );
    const n = runErrorNotice(err, "tailor");
    expect(n.kind).toBe("error");
    expect(n.retryAfterSeconds).toBe(60);
    expect(n.text).toMatch(/rate-limited/i);
  });

  it("LOOP-429: a polled job failure (plain 503 body, no JSON wrapper) keeps the rate-limit sentence and Retry-After", () => {
    const err = new ApiError(
      "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.",
      503,
      812,
    );
    const n = runErrorNotice(err, "tailor");
    expect(n.retryAfterSeconds).toBe(812);
    expect(n.text).toMatch(/rate-limited/i);
    expect(n.text).not.toMatch(/wait a minute and press the button again/i);
  });

  it("LOOP-429: copies Retry-After on HTTP 429 without treating quota as a provider rate-limit", () => {
    const err = new ApiError(
      "You've reached your plan's run quota this period.",
      429,
      3600,
    );
    const n = runErrorNotice(err, "tailor");
    expect(n.retryAfterSeconds).toBe(3600);
    expect(workflowAutoRetryWaitMs(n)).toBeNull();
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

describe("stopAllAgentsNotice", () => {
  // ML-STOPALL-001: the "Stop All Agents" success notice must now claim
  // ENFORCED reality ("blocked", not the old inert "on hold") and must
  // disclose in-flight runs — pausing an agent has no force-kill, so any
  // run already underway when the user clicked "Stop All" keeps going.

  it("says runs are BLOCKED (not merely 'on hold') with zero in-flight runs", () => {
    const n = stopAllAgentsNotice(3, 0);
    expect(n.kind).toBe("success");
    // AUD-AGENT-4: the number counts CARDS (three of which are one engine),
    // so the copy names cards. The enforcement claim is unchanged.
    expect(n.text).toBe("Paused 3 agent cards. New runs are blocked.");
    expect(n.text).not.toContain("on hold");
  });

  it("singularizes the agent count", () => {
    const n = stopAllAgentsNotice(1, 0);
    expect(n.text).toBe("Paused 1 agent card. New runs are blocked.");
  });

  it("discloses in-flight runs and the no-force-kill caveat when some are running", () => {
    const n = stopAllAgentsNotice(4, 2);
    expect(n.kind).toBe("success");
    expect(n.text).toContain("Paused 4 agent cards. New runs are blocked.");
    expect(n.text).toContain("2 runs already in progress will finish");
    expect(n.text).toContain("there is no force-kill");
  });

  it("singularizes a single in-flight run", () => {
    const n = stopAllAgentsNotice(2, 1);
    expect(n.text).toContain("1 run already in progress will finish");
    expect(n.text).not.toContain("1 runs");
  });
});

describe("LOOP-429 workflowAutoRetryWaitMs", () => {
  const RATE =
    "The AI provider rate-limited this run. Wait a minute and try again, or pick a lighter model in Agent Settings.";

  it("retries immediately when Retry-After is 0 (test seam / already elapsed)", () => {
    expect(workflowAutoRetryWaitMs({ kind: "error", text: RATE, retryAfterSeconds: 0 })).toBe(0);
  });

  it("does not invent a one-minute wait when Retry-After was never sent", () => {
    // Production async jobs drop the HTTP 503; a missing header used to
    // become 60s and auto-retry a 15-minute cooldown.
    expect(workflowAutoRetryWaitMs({ kind: "error", text: RATE })).toBeNull();
  });

  it("does not auto-retry a quota wall", () => {
    expect(
      workflowAutoRetryWaitMs({
        kind: "error",
        text: "You've reached your plan's run quota this period.",
      }),
    ).toBeNull();
  });

  it("does not auto-wait a long cooldown — resume is the subscriber's call", () => {
    expect(
      workflowAutoRetryWaitMs({ kind: "error", text: RATE, retryAfterSeconds: 812 }),
    ).toBeNull();
  });
});
