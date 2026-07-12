/**
 * User-facing feedback messages for the Agents console (UX defect fix).
 *
 * The full pipeline is a single synchronous ~30–120 s API call; without
 * these messages the "Run Full Pipeline" button looked dead. Pure functions
 * (no React) so they are unit-testable and reusable.
 */

/** Canonical pipeline node order — mirrors the API's _PIPELINE_PLAN. */
export const PIPELINE_ORDER = [
  "supervisor",
  "scout",
  "fitScorer",
  "matcher",
  "tailor",
  "coverLetter",
] as const;

const PHASE_ACTIVITY: Record<string, string> = {
  supervisor: "Supervisor is planning the run",
  scout: "Scout is discovering jobs",
  fitScorer: "FitScorer is scoring jobs against your resume",
  matcher: "Matcher is picking the best-fit job",
  tailor: "Tailor is rewriting your resume for the top job",
  coverLetter: "CoverLetter is drafting your cover letter",
};

/** A banner notice shown above the agent grid. */
export interface Notice {
  kind: "info" | "success" | "error";
  text: string;
  /** Optional call-to-action link rendered next to the text. */
  href?: string;
  hrefLabel?: string;
}

/** Immediate feedback the instant the pipeline button is clicked. */
export function pipelineStartNotice(): Notice {
  return {
    kind: "info",
    text: "Pipeline started — Scout is discovering jobs… This runs six agents and usually takes 30–120 seconds. Progress updates below.",
  };
}

/**
 * Live progress from the set of pipeline agents that have completed since
 * the run started (derived by polling GET /agents/runs).
 */
export function pipelineProgressNotice(completedAgents: string[]): Notice {
  const done = new Set(completedAgents);
  let nextIdx = 0;
  for (let i = 0; i < PIPELINE_ORDER.length; i += 1) {
    if (done.has(PIPELINE_ORDER[i])) nextIdx = i + 1;
  }
  const current = PIPELINE_ORDER[Math.min(nextIdx, PIPELINE_ORDER.length - 1)];
  const step = Math.min(nextIdx + 1, PIPELINE_ORDER.length);
  return {
    kind: "info",
    text: `Pipeline running — step ${step} of ${PIPELINE_ORDER.length}: ${PHASE_ACTIVITY[current]}…`,
  };
}

interface PipelineStep {
  agent: string;
  output: Record<string, unknown>;
}

/** Completion summary that guides the user's next action. */
export function pipelineCompletionNotice(response: Record<string, unknown>): Notice {
  const steps = (response.steps as PipelineStep[] | undefined) ?? [];
  const byAgent = new Map(steps.map((s) => [s.agent, s.output]));
  const scored = Number(byAgent.get("fitScorer")?.scored ?? 0);
  const matched = Number(byAgent.get("matcher")?.matched ?? 0);
  const changes = Number(byAgent.get("tailor")?.changes ?? 0);
  const hasLetter = byAgent.has("coverLetter");

  if (response.approvalRequired) {
    const topTitle = byAgent.get("matcher")?.top_job_title;
    const topCompany = byAgent.get("matcher")?.top_company;
    const target =
      typeof topTitle === "string" && typeof topCompany === "string"
        ? ` for ${topTitle} @ ${topCompany}`
        : "";
    return {
      kind: "success",
      text: `Pipeline complete — ${matched} jobs matched (${scored} newly scored), resume tailored (${changes} changes)${hasLetter ? " and cover letter drafted" : ""}${target}. Nothing is sent without you:`,
      href: "/dashboard/approvals",
      hrefLabel: "review the pending approval in Approvals →",
    };
  }
  return {
    kind: "success",
    text: "Pipeline complete — no jobs matched yet. Run Scout with a different query, or browse what was discovered:",
    href: "/dashboard/jobs",
    hrefLabel: "open Jobs →",
  };
}

/** Per-agent success feedback pointing at where the data landed. */
export function agentSuccessNotice(agent: string, output: Record<string, unknown>): Notice {
  switch (agent) {
    case "scout": {
      const persisted = Number(output.persisted ?? 0);
      return {
        kind: "success",
        text:
          persisted > 0
            ? `Scout finished — ${persisted} new jobs discovered.`
            : "Scout finished — no new jobs this time (already up to date).",
        href: "/dashboard/jobs",
        hrefLabel: "view them in Jobs →",
      };
    }
    case "fitScorer": {
      const scored = Number(output.scored ?? 0);
      return {
        kind: "success",
        text: `FitScorer finished — ${scored} jobs scored. Sort Jobs by fit score to see the best matches:`,
        href: "/dashboard/jobs",
        hrefLabel: "open Jobs →",
      };
    }
    case "tailor": {
      const changes = Number(output.changes ?? 0);
      return {
        kind: "success",
        text: `Tailor finished — resume tailored with ${changes} accepted changes.`,
        href: "/dashboard/resume",
        hrefLabel: "review the diff in Resume Studio →",
      };
    }
    case "coverLetter":
      return {
        kind: "success",
        text: "CoverLetter finished — a draft is awaiting your sign-off.",
        href: "/dashboard/approvals",
        hrefLabel: "review it in Approvals →",
      };
    case "storyExtractor": {
      const extracted = Number(output.extracted ?? output.stories ?? 0);
      return {
        kind: "success",
        text: `StoryExtractor finished — ${extracted || "new"} STAR stories ready.`,
        href: "/dashboard/stories",
        hrefLabel: "open Story Bank →",
      };
    }
    default:
      return { kind: "success", text: `${agent} finished successfully.` };
  }
}

/** Actionable failure/timeout guidance (never a dead-end error). */
export function runErrorNotice(err: unknown, context: string): Notice {
  const status =
    typeof err === "object" && err !== null && "status" in err
      ? Number((err as { status: unknown }).status)
      : undefined;
  if (status === 503) {
    return {
      kind: "error",
      text: `${context} paused — the AI model is busy or its time budget was exceeded. Wait a minute and press the button again; your data is safe.`,
    };
  }
  if (status === 422) {
    return {
      kind: "error",
      text: `${context} needs more data first — run Scout to discover jobs, then try again.`,
      href: "/dashboard/jobs",
      hrefLabel: "open Jobs →",
    };
  }
  if (status === 401) {
    return {
      kind: "error",
      text: `${context} failed — your session expired. Reload the page to sign in again.`,
    };
  }
  const detail = err instanceof Error ? err.message : "";
  return {
    kind: "error",
    text: `${context} failed${detail ? ` (${detail.slice(0, 140)})` : ""}. Retry in a moment; if it keeps failing, check the RECENT RUNS table below for the error.`,
  };
}
