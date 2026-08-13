/**
 * Customer-facing copy normalisation.
 *
 * Internal run/feed strings leak engineering jargon ("generation degraded",
 * "no worker heartbeat", "abandoned"). These helpers translate them into
 * calm, reassuring language before they ever reach the UI. They are applied
 * at *render* time only — the underlying feed/run helpers stay pure so their
 * unit tests keep asserting the raw domain strings.
 */

/** Ordered phrase → friendly-copy rewrites (case-insensitive, substring). */
const ACTIVITY_PHRASE_MAP: Array<{ pattern: RegExp; replace: string }> = [
  // Longer / more specific phrases first so they win over generic ones.
  { pattern: /generation degraded/gi, replace: "will retry automatically" },
  { pattern: /no worker heartbeat/gi, replace: "" },
  { pattern: /worker heartbeat missing/gi, replace: "" },
  { pattern: /run failed/gi, replace: "Agent run paused — retrying" },
  { pattern: /\babandoned\b/gi, replace: "paused" },
];

/**
 * Humanise a single activity-feed / run message for display.
 *
 * Examples:
 *   "run failed"                              → "Agent run paused — retrying"
 *   "cover letter unavailable (generation degraded)"
 *                                             → "Could not generate — will retry automatically"
 *   "no worker heartbeat"                     → "" (stripped)
 *   "run abandoned"                           → "run paused"
 */
export function humanizeActivityMessage(msg: string | null | undefined): string {
  if (!msg) return "";
  let out = String(msg);

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
  // begins with "Agent" ("Agent run paused") reads as "…Agent Agent run…".
  result = result.replace(/\bAgent\s+Agent\b/g, "Agent");

  return result;
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
