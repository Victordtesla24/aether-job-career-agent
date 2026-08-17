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

  const topTitle = byAgent.get("matcher")?.top_job_title;
  const topCompany = byAgent.get("matcher")?.top_company;
  const target =
    typeof topTitle === "string" && typeof topCompany === "string"
      ? ` for ${topTitle} @ ${topCompany}`
      : "";

  // GAP-P7-COV-PIPE-001: the résumé was tailored but the cover letter was
  // withheld because its fabrication/format guard rejected every draft. This is
  // a graceful degradation (not a failure) — surface the real progress and point
  // the user at the Cover Letter studio rather than the (empty) Approvals queue.
  if (response.coverLetterUnavailable) {
    // Honest lead: only claim the résumé was tailored when changes were actually
    // applied (mirrors the backend's honest message; the compound tailor-no-op +
    // cover-rejected case must not overclaim).
    const tailorClause =
      changes > 0
        ? `and your resume was tailored (${changes} changes)`
        : "and no verifiable resume changes were applied";
    return {
      kind: "info",
      text: `Pipeline complete — ${matched} jobs matched (${scored} newly scored) ${tailorClause}${target}. The cover letter couldn't be auto-generated without unverifiable wording, so it was withheld — generate or write one yourself:`,
      href: "/dashboard/cover-letters",
      hrefLabel: "open the Cover Letter studio →",
    };
  }

  if (response.approvalRequired) {
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

/**
 * Success notice for the "Stop All Agents" bulk pause (ML-STOPALL-001).
 *
 * Enforcement now lives server-side — every dispatch path (the sync run
 * routes, the pipeline, the generic `/agents/{name}/run` route, the async
 * ARQ worker, and the board-sweep autopilot) refuses a paused agent's runs
 * with an honest 409 before they start — so this can truthfully say "New
 * runs are blocked" instead of the old "on hold" wording nothing enforced.
 *
 * `runningCount` is the SAME `isInFlight && isLiveRun` count the RUN HEALTH
 * strip already shows: pausing an agent does NOT force-kill a run already in
 * progress (no cancel/abort endpoint exists), so a user watching a run keep
 * going after "Stop All" must be told that plainly rather than left assuming
 * the pause silently failed.
 */
export function stopAllAgentsNotice(pausedCount: number, runningCount: number): Notice {
  // AUD-AGENT-4: `pausedCount` counts the CARDS whose toggle was flipped, and
  // three of those cards are one `fitScorer` engine — so this says cards. The
  // enforcement claim is unchanged and still true either way: pausing any card
  // blocks the runs it owns.
  const base = `Paused ${pausedCount} agent card${
    pausedCount === 1 ? "" : "s"
  }. New runs are blocked.`;
  if (runningCount > 0) {
    return {
      kind: "success",
      text: `${base} ${runningCount} run${
        runningCount === 1 ? "" : "s"
      } already in progress will finish — there is no force-kill.`,
    };
  }
  return { kind: "success", text: base };
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
        text: scored
          ? `FitScorer finished — ${scored} jobs scored. Sort Jobs by fit score to see the best matches:`
          : "FitScorer finished — every job already had a fit score (nothing new to score):",
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
    // F3 (agents-uplift/u5d re-review, MUST-FIX): before this case existed,
    // EVERY Submission Agent run fell to the `default:` arm below and rendered
    // a hardcoded green "submission finished successfully." — regardless of
    // what actually happened. `submission_agent.py`'s `_describe` computes an
    // honest terminal state (module-level `STATE_*`) and an honest `message`
    // for exactly this reason; `transmitted` is read back from
    // `Application."transmittedAt"` AFTER the write and is the ONLY state
    // backed by real transmission evidence (`transmissionRef` is the proof).
    // Every other state — `awaiting_approval`, `manual_step_required`,
    // `recorded_not_transmitted`, `no_change`, `none` — means nothing left
    // the system, so this must NEVER render `kind: "success"` for them: doing
    // so reproduces the exact production illusion (three real runs that wrote
    // nothing / transmitted nothing, all shown as "Submitted…") this whole
    // workstream exists to kill. The backend's own sentence (already honest
    // and state-specific) is used verbatim rather than re-authored here, so
    // this banner can never drift out of sync with `_describe`'s wording.
    case "submission": {
      const message =
        typeof output.message === "string" && output.message.trim()
          ? output.message
          : undefined;
      if (output.submissionState === "transmitted") {
        return {
          kind: "success",
          text: message ?? "Submission Agent finished — your application was transmitted.",
          href: "/dashboard/applications",
          hrefLabel: "view it in your tracker →",
        };
      }
      if (output.submissionState === "awaiting_approval") {
        return {
          kind: "info",
          text:
            message ??
            "Recorded in your tracker and queued for sending — NOT transmitted yet. Approve it in Approvals to send.",
          href: "/dashboard/approvals",
          hrefLabel: "review it in Approvals →",
        };
      }
      // manual_step_required, recorded_not_transmitted, no_change, none — and
      // any future state this switch does not yet know by name: an unknown
      // state must default to the same honest non-success arm, never to
      // `default:`'s generic "finished successfully.".
      return {
        kind: "info",
        text: message ?? "Submission Agent finished — nothing was transmitted.",
        href: "/dashboard/applications",
        hrefLabel: "open your tracker →",
      };
    }
    // F3 audit (same review): the Email Agent's per-agent Run button
    // dispatches `mode: "triage"` and, like submission, computes an honest
    // `connected`/`degraded`/`message` (`email_agent.py`'s `_triage`) that
    // this switch was discarding in favour of the same blanket "emailAgent
    // finished successfully." — including when Gmail was never connected
    // (0 threads synced, 0 triaged) or a sync failure degraded the run.
    // `degraded` is the single flag `_triage` sets on both of those honest
    // non-outcomes, so it is the only signal this needs to read.
    case "emailAgent": {
      const message =
        typeof output.message === "string" && output.message.trim()
          ? output.message
          : undefined;
      if (output.degraded === true) {
        return {
          kind: "info",
          text: message ?? "Email Agent could not triage your inbox — Gmail is not connected.",
          href: "/dashboard/email",
          hrefLabel: "connect Gmail →",
        };
      }
      return {
        kind: "success",
        text: message ?? "Email Agent finished triaging your inbox.",
        href: "/dashboard/email",
        hrefLabel: "open Email Center →",
      };
    }
    default:
      return { kind: "success", text: `${agent} finished successfully.` };
  }
}

/**
 * Detect the shared async "missing résumé" honest-refusal result shape and,
 * when present, return an honest non-success Notice carrying the backend's
 * own message — instead of letting `agentSuccessNotice`/
 * `pipelineCompletionNotice` fabricate a green success from the fields a
 * refusal never has (NF-final-closure-002).
 *
 * apps/api/app/workers/tasks.py's `except MissingResumeError` handler
 * completes the BackgroundJob (never "failed") with
 * `{resume_id: null, missingResume: true, message: "Add your resume
 * before…"}` for BOTH the single-agent branch (tailor/coverLetter/...) and
 * the pipeline branch — the exact shape NF-final-resid-002 already handles
 * for Cover Letter Studio's `applyCoverLetterResult`. Before this check,
 * `agentSuccessNotice`/`pipelineCompletionNotice` read fields the refusal
 * shape never sets (`changes`, `steps`, `approvalRequired`, ...) and
 * fabricated "Tailor finished — 0 accepted changes", "a draft is awaiting
 * your sign-off", or "Pipeline complete — no jobs matched yet" — all FALSE
 * SUCCESS, dropping the honest message entirely. Call this BEFORE
 * agentSuccessNotice/pipelineCompletionNotice and use its result when
 * non-null.
 */
export function missingResumeNotice(output: Record<string, unknown>): Notice | null {
  if (output.missingResume !== true) return null;
  const message =
    typeof output.message === "string" && output.message.trim()
      ? output.message
      : "Add your resume before running this agent.";
  return {
    kind: "error",
    text: message,
    href: "/dashboard/resume",
    hrefLabel: "add your resume →",
  };
}

/**
 * Lift the real backend `detail` out of an `ApiError`'s raw message.
 * `apiRequest` embeds the raw response body in the error message (e.g.
 * `PUT /agents/providers/x/credential failed (503): {"detail":"Vault
 * unavailable"}`); this pulls the JSON `detail` string out when present and
 * otherwise falls back to the raw message text. Mirrors the extraction
 * already used for email-send errors (see lib/api/workspaces.ts).
 */
function extractApiDetail(err: unknown): string | null {
  if (!(err instanceof Error) || !err.message.trim()) return null;
  // Shared JSON-detail core lives in extractApiJsonDetail (hoisted declaration);
  // this variant adds the documented raw-message fallback.
  return extractApiJsonDetail(err) ?? err.message;
}

/**
 * Strict variant of `extractApiDetail`: returns the parsed JSON `detail`
 * ONLY when `err.message` genuinely ends in a real backend error body
 * (`apiRequest`'s `... failed (<status>): {"detail": "..."}` shape) —
 * unlike `extractApiDetail`, this NEVER falls back to the raw message text.
 *
 * Review regression fix (NF-final-closure-002): `runErrorNotice`'s 422
 * branch used `extractApiDetail`, whose raw-message fallback made it treat
 * ANY `Error` with a 422 `status` property as if it carried a genuine
 * backend detail — including `agents/page.tsx`'s `resolveParams()`, which
 * throws a CLIENT-SIDE synthetic `Object.assign(new Error("No jobs
 * discovered yet"), {status:422})` for Tailor/CoverLetter when the user has
 * zero jobs sourced (the ordinary, pre-existing "run Scout first" scenario
 * the hardcoded copy below was built for). That plain, non-JSON message is
 * not a real backend detail, so `extractApiDetail` fell through to
 * returning it verbatim, silently swallowing the href-bearing Scout
 * guidance. Using this stricter helper for that one call site keeps the
 * fitScorer/genuine-backend-422 improvement (a real `{"detail":...}` body
 * still surfaces) while restoring the original Scout-guidance notice for
 * any 422 whose message isn't genuinely JSON. `providerCredentialErrorNotice`
 * still uses `extractApiDetail` (unchanged) — its raw-message fallback is
 * correct there since every error on that path is a real backend response.
 */
function extractApiJsonDetail(err: unknown): string | null {
  if (!(err instanceof Error) || !err.message.trim()) return null;
  const match = err.message.match(/\{[\s\S]*\}$/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
  } catch {
    // Not JSON — genuinely no real backend detail.
  }
  return null;
}

/**
 * Honest toast for the provider-credential save/remove/verify flow (QA
 * finding: `runErrorNotice`'s generic 503 copy — "the AI model is busy or its
 * time budget was exceeded" — is WRONG here. A 503 on this path means the
 * server's credential vault is unreachable or misconfigured, not that an LLM
 * call timed out; a 422 means the pasted secret failed validation. The
 * modal's inline banner already renders the real backend detail, so this
 * keeps the toast in agreement with it instead of contradicting it with an
 * unrelated generic message. Scoped to provider-credential actions only —
 * `runErrorNotice` is untouched for the pipeline/agent-run flows that still
 * want the generic retry guidance.
 */
export function providerCredentialErrorNotice(err: unknown, context: string): Notice {
  const detail = extractApiDetail(err);
  return {
    kind: "error",
    text: detail ? `${context} failed — ${detail}` : `${context} failed. Please try again.`,
  };
}

/** Actionable failure/timeout guidance (never a dead-end error). */
/**
 * The structured `detail` object the API client preserves on an ApiError, read
 * structurally (this module stays React- and import-free by design). Returns
 * `undefined` when the server sent no object — callers must never be handed a
 * synthesized one.
 */
function apiErrorDetail(err: unknown): Record<string, unknown> | undefined {
  if (typeof err !== "object" || err === null || !("detail" in err)) return undefined;
  const d = (err as { detail: unknown }).detail;
  return d && typeof d === "object" && !Array.isArray(d)
    ? (d as Record<string, unknown>)
    : undefined;
}

/**
 * Human phrasing for a quota reset instant, or `null` when the server sent none
 * or sent something unparseable. Never guesses a reset time: a wrong "runs
 * resume tomorrow" is worse than saying nothing.
 */
function formatQuotaReset(iso: string | null): string | null {
  if (!iso) return null;
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return null;
  return `on ${when.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })} at ${when.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

export function runErrorNotice(err: unknown, context: string): Notice {
  const status =
    typeof err === "object" && err !== null && "status" in err
      ? Number((err as { status: unknown }).status)
      : undefined;
  if (status === 503) {
    // CRITICAL-3b. The API chooses the 503 body by FAILURE CLASS
    // (`llm_client.llm_failure_user_message`): an upstream HTTP 402 says the
    // provider account is out of credits and that retrying will NOT help; a
    // 401 says the configured API key was rejected; only the transient class
    // says "temporarily unavailable, try again". Overwriting all three with
    // one hardcoded "wait a minute and press the button again" told a user
    // staring at a dead upstream to keep pressing — and hid an operator
    // failure behind copy that reads like routine flakiness.
    //
    // Uses the STRICT extractor: only a genuine backend `{"detail": "..."}`
    // body replaces the copy below. A synthetic client-side error, or a 503
    // with no JSON detail (proxy/gateway page), still falls through to the
    // original guidance unchanged.
    const detail = extractApiJsonDetail(err);
    if (detail) {
      return { kind: "error", text: `${context} paused — ${detail}` };
    }
    return {
      kind: "error",
      text: `${context} paused — the AI model is busy or its time budget was exceeded. Wait a minute and press the button again; your data is safe.`,
    };
  }
  if (status === 429) {
    // DROP-001. The plan-quota 429 (routers/agents.py) ships `message`,
    // `quotaReset` and `upgradeUrl`, describing itself as carrying "an upgrade
    // CTA and the period reset time so the UI can prompt an upgrade or a wait".
    // None of it was reachable — ApiError flattened the body into a string — so
    // a quota wall fell through to the generic branch below, which tells the
    // user to "retry in a moment" and check RECENT RUNS. Both are wrong for a
    // quota: retrying cannot succeed, and the runs table explains nothing.
    const detail = apiErrorDetail(err);
    const serverMessage =
      typeof detail?.message === "string" && detail.message.trim()
        ? detail.message.trim()
        : `${context} is blocked — you've reached your plan's run quota for this period.`;
    const resetPhrase = formatQuotaReset(
      typeof detail?.quotaReset === "string" ? detail.quotaReset : null,
    );
    const upgradeUrl =
      typeof detail?.upgradeUrl === "string" && detail.upgradeUrl ? detail.upgradeUrl : null;
    const isSpendCap = detail?.code === "spend_cap_exceeded";
    return {
      kind: "error",
      // Only state a reset time the server actually sent — never invent one.
      text: resetPhrase ? `${serverMessage} Runs resume ${resetPhrase}.` : serverMessage,
      ...(upgradeUrl
        ? { href: upgradeUrl, hrefLabel: isSpendCap ? "review plan →" : "upgrade plan →" }
        : {}),
    };
  }
  if (status === 422) {
    // NF-final-closure-002: this hardcoded "run Scout to discover jobs" copy
    // was wrong whenever the real 422 detail said something else — most
    // often fitScorer's honest, synchronous MissingResumeError refusal
    // ("Add your resume before scoring jobs against it."), which "run
    // Scout" both drops and misdirects (jobs already exist; the résumé is
    // what's missing). Surface the server's own detail when present — but
    // ONLY when it was genuinely parsed from a backend JSON body
    // (extractApiJsonDetail, not extractApiDetail): resolveParams() in
    // agents/page.tsx throws a CLIENT-SIDE synthetic 422 ("No jobs
    // discovered yet") for the ordinary zero-jobs case, and that plain
    // Error's message must keep falling through to the Scout-guidance
    // notice below, not be mistaken for a real backend detail (review
    // regression fix).
    const detail = extractApiJsonDetail(err);
    if (detail) {
      return { kind: "error", text: `${context} failed — ${detail}` };
    }
    return {
      kind: "error",
      text: `${context} needs more data first — run Scout to discover jobs, then try again.`,
      href: "/dashboard/jobs",
      hrefLabel: "open Jobs →",
    };
  }
  if (status === 409) {
    // F5-010 (Fable 5 review): a 409 from the Stop-All / per-agent pause
    // guard is a DELIBERATE, pre-side-effect refusal — the user's own
    // controls stopped the agent, nothing ran and nothing was charged (see
    // `_agent_paused_by_user` and the string/dict refusal shapes in
    // apps/api/app/routers/agents.py). It previously fell through to the
    // generic branch below, which (a) rendered it as a FAILURE with the raw
    // truncated body ("agent_paused: ... (Stop Al") and (b) advised "Retry
    // in a moment" — actively wrong, since retrying cannot succeed until the
    // user re-enables the agent. It also halted the OrchestrationMap batch
    // ("Stopped at Sentiment Analysis Agent — ..."), misreporting a pause as
    // a pipeline failure. Mirror board_sweep's honest-skip semantics: an
    // `info` notice (so the batch runner does not treat it as a refusal)
    // with the ONE action that actually helps. Both backend refusal shapes
    // are recognized: the plain-string `"agent_paused: ..."` detail from
    // `_dispatch`/`_enqueue_single_agent` and the coded
    // `{code: "agent_paused"}` dict from `_execute_reserved_run`.
    const structured = apiErrorDetail(err);
    const jsonDetail = extractApiJsonDetail(err);
    const isPausedRefusal =
      structured?.code === "agent_paused" ||
      (typeof jsonDetail === "string" && jsonDetail.startsWith("agent_paused"));
    if (isPausedRefusal) {
      return {
        kind: "info",
        text: `${context} skipped — it's stopped by your agent controls (Stop All / per-agent toggle), so nothing ran and nothing was charged. Re-enable it with its toggle on the Agents page, then run it again.`,
      };
    }
    // Any other genuine backend 409 conflict: surface the server's own
    // detail rather than the generic retry copy, when one was sent.
    if (jsonDetail) {
      return { kind: "error", text: `${context} failed — ${jsonDetail}` };
    }
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
