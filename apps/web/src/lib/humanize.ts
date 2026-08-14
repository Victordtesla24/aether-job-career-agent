/**
 * Customer-facing copy normalisation.
 *
 * Internal run/feed strings occasionally leak engineering jargon (e.g.
 * "generation degraded"). This helper translates that ONE case into calm,
 * reassuring language before it ever reaches the UI. It is applied at
 * *render* time only — the underlying feed/run helpers stay pure so their
 * unit tests keep asserting the raw domain strings.
 *
 * HONESTY INVARIANT (I4-FE-02 / I4-FE-02b / I4-FE-02c): this function must
 * never rewrite a genuinely terminal/failed run into copy that reads as
 * "paused", "retrying", or otherwise in-progress, and must never reduce a
 * non-empty error to the empty string (a blank result renders identically
 * to "no error" wherever a caller falls back to an em-dash on empty output —
 * apps/web/src/app/dashboard/agents/page.tsx's run-error column does exactly
 * that). `apps/api/app/services/agent_run_watchdog.py`'s `_honest_error()` /
 * `ABANDONED_ERROR_MARKER` deliberately avoid retry-sounding wording because
 * an abandoned run is chronic breakage, not a hiccup — this module must not
 * put that wording back in on the way to the screen. A prior version of this
 * file rewrote "abandoned" → "paused", "run failed" → "Agent run paused —
 * retrying", and "no worker heartbeat" / "worker heartbeat missing" → "" ;
 * all three were removed for that reason. Only cosmetic, truth-preserving
 * rewrites belong in `ACTIVITY_PHRASE_MAP` below.
 */

/** Ordered phrase → friendly-copy rewrites (case-insensitive, substring). */
const ACTIVITY_PHRASE_MAP: Array<{ pattern: RegExp; replace: string }> = [
  { pattern: /generation degraded/gi, replace: "will retry automatically" },
];

/**
 * Humanise a single activity-feed / run message for display.
 *
 * Examples:
 *   "cover letter unavailable (generation degraded)"
 *                                              → "Could not generate — will retry automatically"
 *   "run abandoned — no worker heartbeat"      → unchanged (honest failure text is never rewritten)
 *   "run failed"                               → unchanged (never claims a retry that isn't happening)
 *
 * Guarantee: for a non-empty `msg`, the return value is never the empty
 * string.
 */
export function humanizeActivityMessage(msg: string | null | undefined): string {
  if (!msg) return "";
  const original = String(msg);
  let out = original;

  // Special-case: "<thing> unavailable (generation degraded)" reads better as a
  // single reassuring sentence than a literal phrase swap.
  if (/generation degraded/i.test(out) && /unavailable/i.test(out)) {
    return "Could not generate — will retry automatically";
  }

  let changed = false;
  for (const { pattern, replace } of ACTIVITY_PHRASE_MAP) {
    if (pattern.test(out)) {
      changed = true;
      out = out.replace(pattern, replace);
    }
  }

  // Only tidy up separators/whitespace when we actually rewrote something —
  // otherwise legitimate trailing punctuation (e.g. "found a strong match — ",
  // which is deliberately followed by a highlight span) would be mangled.
  let result = changed ? tidyCopy(out) : out;

  // Collapse an accidental "Agent Agent" — an agent whose display name already
  // ends in "Agent" (e.g. "Cover Letter Agent") followed by a template that
  // begins with "Agent" reads as "…Agent Agent…".
  result = result.replace(/\bAgent\s+Agent\b/g, "Agent");

  // Never turn a non-empty input into an empty output — fall back to the
  // untouched original message rather than silently erasing a real error.
  return result.trim() ? result : original;
}

/**
 * Join an agent's display name with a humanised activity message without
 * producing a redundant "Agent Agent". When the display name already ends in
 * "Agent" and the message begins with "Agent ", drop that leading "Agent ".
 * Returns just the (possibly trimmed) message — the caller keeps the display
 * name in its own (bold) node.
 */
export function activityMessageAfterAgentName(
  displayName: string,
  humanizedMessage: string,
): string {
  if (/agent\s*$/i.test(displayName) && /^agent\s+/i.test(humanizedMessage)) {
    return humanizedMessage.replace(/^agent\s+/i, "");
  }
  return humanizedMessage;
}

/**
 * Clean up artefacts left behind after phrase removal — empty parens,
 * dangling separators, and doubled whitespace.
 */
function tidyCopy(text: string): string {
  return text
    .replace(/\(\s*\)/g, "") // empty "()"
    .replace(/\[\s*\]/g, "") // empty "[]"
    .replace(/\s*[—–-]\s*$/g, "") // trailing dash separators
    .replace(/[—–-]\s*[—–-]/g, "—") // doubled dashes
    .replace(/\s{2,}/g, " ") // collapse whitespace
    .replace(/\s+([,.;:])/g, "$1") // space before punctuation
    .replace(/[\s,;:—–-]+$/g, "") // trailing junk separators
    .trim();
}

/**
 * Strip a leading "Copy of " prefix (any casing, repeated) from a job title so
 * duplicated listings display their real title. Applied at data-load time.
 */
export function stripCopyOfPrefix(title: string | null | undefined): string {
  if (!title) return title ?? "";
  let out = String(title);
  // Remove one or more leading "Copy of " prefixes (e.g. "Copy of Copy of X").
  while (/^\s*copy of\s+/i.test(out)) {
    out = out.replace(/^\s*copy of\s+/i, "");
  }
  return out.trim() || String(title).trim();
}
