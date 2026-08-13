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

/**
 * U2a (R-F1/R-F3/MON-012) — honest copy for the upload panel's helper text
 * and the "original stored" badge.
 *
 * BASELINE_HELP_TEXT states, before the user picks a file: which formats
 * Aether genuinely reads, that the uploaded file becomes the user's
 * immutable baseline (tailoring never rewrites it — see
 * `apps/api/app/repositories/resume.py`'s `BaselineImmutableError` guard),
 * and that a resume uploaded before this feature shipped has no stored
 * original bytes.
 *
 * FE-review refix (2026-08-13, finding F-1): the previous copy said
 * re-uploading would "enable format preservation" — false in the PRESENT
 * TENSE. Storing the original bytes only gives a *future* format-preserving
 * engine (U2b/R-F4, not yet built) a source document to work from,
 * regardless of how old or new the upload is: today, `POST
 * /resumes/{id}/download` still routes every user-authored résumé through
 * `create_branded_resume_pdf` (see `apps/api/app/services/resume_pdf.py`'s
 * `resolve_original_pdf`, which only matches the two hand-tuned bundled
 * seed PDFs) and the stored `originalFile` bytes have exactly one reader,
 * `GET /resumes/{id}/original` — no download or tailoring path reads them
 * yet. The copy below says what re-uploading actually does today: stores
 * the bytes as a source for later, without claiming downloads already look
 * any different.
 */
export const BASELINE_HELP_TEXT =
  "Supported formats: PDF (.pdf), Word (.docx), and plain text (.txt/.md). " +
  "Your uploaded file is stored as your immutable baseline — tailoring " +
  "never alters it. If you uploaded your résumé before this feature " +
  "existed, its original bytes were never stored; re-uploading stores " +
  "them now as the source for a future format-preserving engine — today, " +
  "every download still renders in the Aether template.";

/** Badge copy for whether the active resume has its original bytes stored. */
export const ORIGINAL_STORED_LABEL = "Original stored ✓";
export const ORIGINAL_NOT_STORED_LABEL = "Original not stored — re-upload to store it";

/** Hard cap mirroring `lib/api/client.ts`'s `ERROR_MESSAGE_MAX_CHARS` — the
 * upload call uses multipart `FormData` via a raw `fetch`, not `apiRequest`,
 * so it cannot reuse that module's private `describeApiError()` machinery
 * and needs its own (much simpler) bound. */
const UPLOAD_ERROR_MAX_CHARS = 300;

/**
 * Turn a failed `POST /resumes/upload` response into the honest message to
 * show the user (MON-012 / upload-rejection honesty).
 *
 * Every rejection this endpoint raises — unsupported format, undecodable
 * text, too-short extraction, oversized file — is a single human-written
 * `{"detail": "..."}` string (see `apps/api/app/routers/resumes.py`), never a
 * Pydantic field-validation array. The previous behaviour showed the raw
 * `{"detail": "..."}` JSON blob truncated at a fixed character count — a
 * user rejected for an unsupported format saw a mid-sentence cutoff wrapped
 * in stray JSON punctuation instead of the actual reason. This shows that
 * exact sentence, verbatim, with no re-wording — only a defensive length
 * cap in case a future detail is unexpectedly long.
 */
export function describeUploadError(status: number, rawBody: string): string {
  try {
    const parsed: unknown = JSON.parse(rawBody);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as { detail?: unknown }).detail === "string"
    ) {
      const detail = (parsed as { detail: string }).detail;
      return detail.length <= UPLOAD_ERROR_MAX_CHARS
        ? detail
        : `${detail.slice(0, UPLOAD_ERROR_MAX_CHARS - 1)}…`;
    }
  } catch {
    // Non-JSON body (proxy error page, empty body) — nothing structured to
    // lift; fall through to an honest status-only message below.
  }
  return `Upload failed (HTTP ${status}). Please try again.`;
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
