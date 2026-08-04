/**
 * Pure helpers for the Settings → Resume Management upload panel (F-03).
 *
 * PROD-UAT-2026-08-03 finding F-03 (MAJOR): uploading a résumé auto-dispatched
 * the LLM-metered `storyExtractor` agent, so one deliberate user action spent
 * an agent run — 20% of the Free plan's five monthly runs — with no warning
 * before the fact. The panel's only mention of extraction came AFTER the
 * upload ("story extraction ran."), unconditionally, and never said it was
 * billable; it said that even when extraction had failed.
 *
 * The endpoint is now opt-in (`extract_stories`, default off — see
 * `apps/api/app/routers/resumes.py`). These helpers carry the two things the
 * screen owes the user:
 *   - `EXTRACTION_OPT_IN_LABEL` / `EXTRACTION_COST_HINT` — the price, stated at
 *     the point of decision, BEFORE the file is sent;
 *   - `buildUploadNotice` — after-the-fact copy derived from what the server
 *     actually reports, so it can no longer claim a run that never happened.
 *
 * Kept side-effect-free so both can be unit-tested without a DOM.
 */

/** Metered agent runs one story-extraction consumes. */
export const STORY_EXTRACTION_RUN_COST = 1;

/** Checkbox label — the cost disclosure, rendered BEFORE the user commits. */
export const EXTRACTION_OPT_IN_LABEL =
  "Also extract STAR stories from this résumé — runs the Story Extractor " +
  "agent and uses 1 of your monthly agent runs.";

/** Sub-label making the default (opt-out) state's cost explicit too. */
export const EXTRACTION_COST_HINT =
  "Uploading on its own is free and uses no agent runs. You can extract " +
  "stories later from the Story Bank.";

/** The subset of `POST /resumes/upload`'s response this panel renders. */
export interface ResumeUploadResult {
  version?: number;
  label?: string;
  /** Echoes the `extract_stories` flag the caller sent. */
  storyExtractionRequested?: boolean;
  /** The extractor run's result — null/absent when it was not requested. */
  storyExtraction?: {
    created?: number;
    bullets?: number;
    error?: string;
  } | null;
}

function describeVersion(result: ResumeUploadResult): string {
  const version = typeof result.version === "number" ? `v${result.version}` : "a new version";
  return result.label
    ? `Uploaded and parsed — registered as ${version} (“${result.label}”).`
    : `Uploaded and parsed — registered as ${version}.`;
}

/**
 * Truthful post-upload copy: what ran, what it cost, and what did not run.
 *
 * Three distinct outcomes, never conflated:
 *   1. extraction not requested — nothing was billed, and the user is told
 *      where to run it and what it will cost;
 *   2. extraction requested and it failed — no stories added, said plainly
 *      (the server swallowed a non-HTTP failure into `storyExtraction.error`;
 *      an entitlement/quota refusal is an HTTP error and never reaches here);
 *   3. extraction requested and it ran — the run charge is stated, with the
 *      real number of stories the run reports.
 */
export function buildUploadNotice(result: ResumeUploadResult): string {
  const head = describeVersion(result);
  if (!result.storyExtractionRequested) {
    return `${head} No agent run was used. ${EXTRACTION_COST_HINT}`;
  }
  const extraction = result.storyExtraction ?? null;
  if (extraction?.error) {
    return (
      `${head} Story extraction failed: ${extraction.error} — no stories were ` +
      "added. You can retry it from the Story Bank."
    );
  }
  const created = typeof extraction?.created === "number" ? extraction.created : null;
  const stories =
    created === null
      ? "Story extraction ran"
      : `Story extraction ran and added ${created} ${created === 1 ? "story" : "stories"}`;
  return `${head} ${stories} — that used ${STORY_EXTRACTION_RUN_COST} of your monthly agent runs.`;
}
