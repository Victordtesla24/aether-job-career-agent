// @vitest-environment jsdom
/**
 * NF-final-closure-002 regression guard (Agents console + pipeline "Run
 * All" — final adversarial CLOSURE sweep, same bug class as
 * NF-final-resid-002 the fixer flagged as an out-of-scope lead on this exact
 * page).
 *
 * The async single-agent and pipeline paths can complete honestly with a
 * no-résumé REFUSAL instead of real work: the backend's completed
 * BackgroundJob result carries `missingResume: true` and a user-actionable
 * `message` (apps/api/app/workers/tasks.py's `except MissingResumeError`
 * handler, both the single-agent AND pipeline branches — same shape
 * NF-final-resid-002 fixed for Cover Letter Studio).
 *
 * Before the fix, `trigger()`/`pipeline()` in ../page.tsx fed that refusal
 * result straight into `agentSuccessNotice`/`pipelineCompletionNotice`,
 * which read fields the refusal shape never has (`changes`, `steps`,
 * `approvalRequired`, ...) and fabricated a GREEN SUCCESS notice with a
 * dead-end CTA, silently dropping the honest "Add your resume…" message.
 * fitScorer is synchronous (no BackgroundJob) — its honest 422 detail was
 * separately dropped by a hardcoded "run Scout to discover jobs" string in
 * `runErrorNotice`.
 *
 * This drives the REAL AgentsPage against mocked API boundaries and asserts,
 * per agent-notice path (tailor, coverLetter, pipeline, fitScorer), that the
 * honest backend message renders and no green success notice appears. Two
 * regression guards prove the fix doesn't overcorrect real completions.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
const fetchAgentRuns = vi.fn();
const fetchAgents = vi.fn();
const runAgent = vi.fn();
const runPipeline = vi.fn();
const fetchAgentStats = vi.fn();
const fetchCatalog = vi.fn();
const fetchProviders = vi.fn();
const updateAgentConfig = vi.fn();
const updateProvider = vi.fn();

vi.mock("../../../../lib/api/client", async () => {
  // ML-test-001: keep the REAL ApiError class alive through the mock —
  // page.tsx's catalogErrorText() does `e instanceof ApiError` in a catch
  // block, and a full-replacement mock that omits it makes that access throw
  // (vitest's mock guard), which escapes the catch as an unhandled rejection.
  const actual =
    await vi.importActual<typeof import("../../../../lib/api/client")>(
      "../../../../lib/api/client",
    );
  return { ...actual, apiRequest: (...args: unknown[]) => apiRequest(...args) };
});

vi.mock("../../../../lib/api/agents", () => ({
  fetchAgentRuns: (...args: unknown[]) => fetchAgentRuns(...args),
  fetchAgents: (...args: unknown[]) => fetchAgents(...args),
  runAgent: (...args: unknown[]) => runAgent(...args),
  runPipeline: (...args: unknown[]) => runPipeline(...args),
}));

vi.mock("../../../../components/agents/api", () => ({
  fetchAgentStats: (...args: unknown[]) => fetchAgentStats(...args),
  fetchCatalog: (...args: unknown[]) => fetchCatalog(...args),
  fetchProviders: (...args: unknown[]) => fetchProviders(...args),
  updateAgentConfig: (...args: unknown[]) => updateAgentConfig(...args),
  updateProvider: (...args: unknown[]) => updateProvider(...args),
}));

// eslint-disable-next-line import/first
import AgentsPage from "../page";

const STATS = {
  spendUsd: 0,
  avgCostPerRun: 0,
  providerCount: 0,
  tokensTotal: 0,
  tokensIn: 0,
  tokensOut: 0,
  mostActiveAgent: null,
  successRate: 0,
  taskCount: 0,
};

function agent(key: string, name: string) {
  return {
    key,
    name,
    icon: "fa-robot",
    accent: "indigo",
    model: "gpt-5.5",
    recommended: "gpt-5.5",
    tip: "test agent",
    runnable: true,
    backend: key,
    enabled: true,
    status: "active" as const,
    last_run: null,
  };
}

const CATALOG = {
  agents: [agent("tailor", "Tailor"), agent("coverLetter", "CoverLetter"), agent("fitScorer", "FitScorer")],
  counts: { total: 3, active: 3, paused: 0, error: 0, planned: 0 },
};

const JOB = { id: "job-1" };

function setupDefaultMocks() {
  fetchCatalog.mockResolvedValue(CATALOG);
  fetchProviders.mockResolvedValue([]);
  fetchAgentStats.mockResolvedValue(STATS);
  fetchAgents.mockResolvedValue([]);
  fetchAgentRuns.mockResolvedValue([]);
  apiRequest.mockImplementation((path: string) => {
    if (path === "/jobs?sort=fitScore") return Promise.resolve([JOB]);
    throw new Error(`unexpected apiRequest call: ${path}`);
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function waitForLoaded() {
  await waitFor(() => expect(fetchCatalog).toHaveBeenCalled());
  await waitFor(() => screen.getByTestId("agent-run-tailor"));
}

function noticeElement() {
  return screen.findByTestId("agents-notice");
}

describe("NF-final-closure-002: honest no-résumé refusal surfacing (agents console)", () => {
  it("tailor refusal: renders the honest message, never a green false-success", async () => {
    setupDefaultMocks();
    runAgent.mockResolvedValue({
      resume_id: null,
      missingResume: true,
      message: "Add your resume before tailoring or generating an application.",
    });
    render(<AgentsPage />);
    await waitForLoaded();

    fireEvent.click(screen.getByTestId("agent-run-tailor"));

    const notice = await noticeElement();
    await waitFor(() =>
      expect(notice.textContent).toContain(
        "Add your resume before tailoring or generating an application.",
      ),
    );
    expect(notice.textContent).not.toContain("accepted changes");
    expect(notice.className).not.toContain("aether-green");
  });

  it("coverLetter refusal: renders the honest message, never 'awaiting your sign-off'", async () => {
    setupDefaultMocks();
    runAgent.mockResolvedValue({
      resume_id: null,
      missingResume: true,
      message: "Add your resume before generating a cover letter.",
    });
    render(<AgentsPage />);
    await waitForLoaded();

    fireEvent.click(screen.getByTestId("agent-run-coverLetter"));

    const notice = await noticeElement();
    await waitFor(() =>
      expect(notice.textContent).toContain("Add your resume before generating a cover letter."),
    );
    expect(notice.textContent).not.toContain("awaiting your sign-off");
    expect(notice.className).not.toContain("aether-green");
  });

  it("pipeline ('Run All') refusal: renders the honest message, never 'Pipeline complete'", async () => {
    setupDefaultMocks();
    runPipeline.mockResolvedValue({
      resume_id: null,
      missingResume: true,
      message: "Add your resume before scoring jobs against it.",
    });
    render(<AgentsPage />);
    await waitForLoaded();

    fireEvent.click(screen.getByTestId("run-pipeline-btn"));

    const notice = await noticeElement();
    await waitFor(() =>
      expect(notice.textContent).toContain("Add your resume before scoring jobs against it."),
    );
    expect(notice.textContent).not.toContain("Pipeline complete");
    expect(notice.className).not.toContain("aether-green");
  });

  it("fitScorer refusal (sync 422): renders the real backend detail, not the hardcoded 'run Scout' remediation", async () => {
    setupDefaultMocks();
    const apiError = Object.assign(
      new Error(
        'POST /agents/fit-scorer/run failed (422): {"detail":"Add your resume before scoring jobs against it."}',
      ),
      { status: 422 },
    );
    runAgent.mockRejectedValue(apiError);
    render(<AgentsPage />);
    await waitForLoaded();

    fireEvent.click(screen.getByTestId("agent-run-fitScorer"));

    const notice = await noticeElement();
    await waitFor(() =>
      expect(notice.textContent).toContain("Add your resume before scoring jobs against it."),
    );
    expect(notice.textContent).not.toContain("run Scout to discover jobs");
  });

  it("regression guard: a REAL tailor completion still renders the original green success notice", async () => {
    setupDefaultMocks();
    runAgent.mockResolvedValue({ resume_id: "r-1", changes: 4 });
    render(<AgentsPage />);
    await waitForLoaded();

    fireEvent.click(screen.getByTestId("agent-run-tailor"));

    const notice = await noticeElement();
    await waitFor(() => expect(notice.textContent).toContain("4 accepted changes"));
    expect(notice.className).toContain("aether-green");
  });

  it("regression guard: a REAL pipeline completion (approval required) still renders the original green success notice", async () => {
    setupDefaultMocks();
    runPipeline.mockResolvedValue({
      status: "awaiting_approval",
      approvalRequired: true,
      steps: [
        { agent: "scout", output: { persisted: 3 } },
        { agent: "fitScorer", output: { scored: 5 } },
        {
          agent: "matcher",
          output: { matched: 4, top_job_title: "Data Analyst", top_company: "Acme" },
        },
        { agent: "tailor", output: { changes: 9 } },
      ],
    });
    render(<AgentsPage />);
    await waitForLoaded();

    fireEvent.click(screen.getByTestId("run-pipeline-btn"));

    const notice = await noticeElement();
    await waitFor(() => expect(notice.textContent).toContain("4 jobs matched"));
    expect(notice.className).toContain("aether-green");
  });
});
