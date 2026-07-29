/**
 * Pure helpers for the dashboard Agent Activity feed (wireframe
 * agent-feed-s1t2u3): per-agent display names/icon tiles, run descriptions
 * enriched from AgentRun output, badge mapping and relative timestamps.
 * Kept free of React so they are unit-testable.
 */
import type { AgentRun } from "../../lib/api/agents";

interface FeedBadge {
  label: string;
  cls: string;
}

interface FeedTile {
  icon: string;
  cls: string;
}

const AGENT_NAMES: Record<string, string> = {
  scout: "Scout Agent",
  matcher: "Matcher Agent",
  fitScorer: "Fit Scorer",
  tailor: "Tailoring Agent",
  coverLetter: "Cover Letter Agent",
  submission: "Submission Agent",
  supervisor: "Supervisor",
};

const AGENT_TILES: Record<string, FeedTile> = {
  scout: { icon: "fa-magnifying-glass", cls: "bg-aether-indigo/15 border-aether-indigo/25 text-[#818CF8]" },
  matcher: { icon: "fa-wand-magic-sparkles", cls: "bg-aether-indigo/15 border-aether-indigo/25 text-[#818CF8]" },
  fitScorer: { icon: "fa-gauge-high", cls: "bg-aether-indigo/15 border-aether-indigo/25 text-[#818CF8]" },
  tailor: { icon: "fa-file-pen", cls: "bg-aether-coral/15 border-aether-coral/25 text-aether-coral" },
  coverLetter: { icon: "fa-file-lines", cls: "bg-aether-amber/15 border-aether-amber/25 text-aether-amber" },
  submission: { icon: "fa-check", cls: "bg-aether-green/15 border-aether-green/25 text-aether-green" },
  supervisor: { icon: "fa-sitemap", cls: "bg-aether-violet/15 border-aether-violet/25 text-aether-violet" },
};

const DEFAULT_TILE: FeedTile = {
  icon: "fa-robot",
  cls: "bg-white/8 border-white/10 text-aether-muted",
};

export function agentDisplayName(agentName: string): string {
  return AGENT_NAMES[agentName] ?? `${agentName} agent`;
}

export function agentTile(agentName: string): FeedTile {
  return AGENT_TILES[agentName] ?? DEFAULT_TILE;
}

/** True when a completed coverLetter run degraded gracefully and produced no
 * letter (QA-RES-F). The cover-letter agent/worker set this exact flag on
 * every honest degrade path (LLM unavailable on first draft, fabrication/
 * structural guard rejection) — see apps/api/app/agents/cover_letter_agent.py,
 * apps/api/app/workers/tasks.py and apps/api/app/routers/agents.py, all of
 * which mark the run `completed` with `output.coverLetterUnavailable = true`
 * and `cover_letter_id: None`. Genuine successes always carry a real
 * `cover_letter_id` and never set this flag.
 *
 * Exported (QA3-F-03) so every other surface that renders AgentRun rows —
 * the Agents console's Orchestration panel and its "Recent runs" table —
 * reuses this SAME predicate instead of re-deriving it, so a degraded run
 * can never read as a plain success on one screen while this one shows it
 * honestly. */
export function coverLetterDegraded(run: AgentRun): boolean {
  if (run.agentName !== "coverLetter") return false;
  const out = run.output ?? {};
  return out.coverLetterUnavailable === true;
}

/** Badge per run status/agent (wireframe: Discovered/Tailored/Submitted/Waiting). */
export function runBadge(run: AgentRun): FeedBadge {
  if (run.status === "queued" || run.status === "running") {
    return { label: "Waiting", cls: "bg-aether-yellow/15 text-aether-yellow border-aether-yellow/20" };
  }
  if (run.status === "failed") {
    return { label: "Failed", cls: "bg-red-500/15 text-red-300 border-red-500/20" };
  }
  if (coverLetterDegraded(run)) {
    // Honest neutral badge — never the success "Drafted" amber for a run
    // that produced no letter.
    return { label: "Unavailable", cls: "bg-white/8 text-aether-muted border-white/10" };
  }
  const byAgent: Record<string, FeedBadge> = {
    scout: { label: "Discovered", cls: "bg-aether-indigo/15 text-[#818CF8] border-aether-indigo/20" },
    matcher: { label: "Discovered", cls: "bg-aether-indigo/15 text-[#818CF8] border-aether-indigo/20" },
    tailor: { label: "Tailored", cls: "bg-aether-coral/15 text-aether-coral border-aether-coral/20" },
    submission: { label: "Submitted", cls: "bg-aether-green/15 text-aether-green border-aether-green/20" },
    coverLetter: { label: "Drafted", cls: "bg-aether-amber/15 text-aether-amber border-aether-amber/20" },
  };
  return (
    byAgent[run.agentName] ?? {
      label: "Completed",
      cls: "bg-aether-green/15 text-aether-green border-aether-green/20",
    }
  );
}

function num(value: unknown): number | null {
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * One-line description + mono metric for a run, enriched with job/company
 * context where the orchestrator output carries it.
 */
export function describeRun(run: AgentRun): { text: string; highlight: string | null; metric: string | null } {
  const out = run.output ?? {};
  if (run.status === "failed") {
    return { text: "run failed", highlight: null, metric: run.error ? run.error.slice(0, 60) : null };
  }
  if (run.status === "queued" || run.status === "running") {
    return { text: `run ${run.status}`, highlight: null, metric: "in progress" };
  }
  switch (run.agentName) {
    case "scout": {
      const persisted = num(out.persisted);
      const updated = num(out.updated);
      if (!persisted) {
        // A zero-insert run re-checked the boards and refreshed known
        // postings — saying "discovered 0 new roles" every half hour reads
        // as broken; saying "discovered N" for refreshes would be untrue.
        return {
          text: "checked job boards — no new roles",
          highlight: null,
          metric: updated ? `${updated} refreshed` : null,
        };
      }
      return {
        text: `discovered ${persisted} new role${persisted === 1 ? "" : "s"}`,
        highlight: null,
        metric: `${persisted} persisted`,
      };
    }
    case "matcher": {
      const title = str(out.top_job_title);
      const company = str(out.top_company);
      const fit = num(out.top_fit_score);
      if (title && company) {
        return {
          text: "found a strong match — ",
          highlight: `${title} at ${company}`,
          metric: fit != null ? `match ${Math.round(fit)}%` : null,
        };
      }
      const matched = num(out.matched);
      return { text: `ranked ${matched ?? 0} matches`, highlight: null, metric: null };
    }
    case "fitScorer": {
      const scored = num(out.scored);
      if (!scored) {
        // A zero-count run means every job was already scored — say so
        // instead of the broken-sounding "scored 0 jobs".
        return {
          text: "checked for unscored jobs — all up to date",
          highlight: null,
          metric: null,
        };
      }
      return {
        text: `scored ${scored} job${scored === 1 ? "" : "s"} for fit`,
        highlight: null,
        metric: `${scored} scored`,
      };
    }
    case "tailor": {
      const changes = Array.isArray(out.changes) ? out.changes.length : num(out.changes);
      return {
        text: "customized your resume",
        highlight: null,
        metric: changes != null ? `${changes} edits` : null,
      };
    }
    case "coverLetter": {
      if (coverLetterDegraded(run)) {
        // QA-RES-F: the writing model was unavailable / the fabrication
        // guard rejected every draft — no letter exists. Say so instead of
        // claiming success.
        const message = str(out.message);
        return {
          text: "cover letter unavailable (generation degraded)",
          highlight: null,
          metric: message ? message.slice(0, 60) : null,
        };
      }
      const waiting = str(out.approval_status) === "pending";
      return {
        text: waiting ? "drafted a cover letter — awaiting your approval" : "drafted a cover letter",
        highlight: null,
        metric: waiting ? "needs approval" : null,
      };
    }
    case "submission":
      return { text: "submitted an application", highlight: null, metric: null };
    case "supervisor":
      return { text: "planned the discovery → tailoring pipeline", highlight: null, metric: null };
    default:
      return { text: `run ${run.status}`, highlight: null, metric: null };
  }
}

/** "just now" / "N min ago" / "N hr ago" / "N d ago" relative to `now`. */
export function relTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "queued";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "queued";
  const mins = Math.max(0, Math.floor((now.getTime() - then) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.floor(hrs / 24)} d ago`;
}
