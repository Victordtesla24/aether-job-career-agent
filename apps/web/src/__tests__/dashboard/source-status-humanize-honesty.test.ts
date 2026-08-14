/**
 * NEW-I4-FE-05 / NEW-I4-FE-06 (I4 closing-gate round-2 re-review) —
 * failing-first characterisation tests for `sourceStatus.ts`'s
 * `humanizeSourceError`'s "looksRaw" branch (URL-bearing / stack-trace /
 * oversized adapter errors).
 *
 * Before this fix, that branch discarded ANY such error and replaced it with
 * the fabricated line "<Source>: temporarily unavailable — Aether will
 * retry on the next sync." — asserting a TEMPORARY nature the code cannot
 * know, and destroying the real cause, in direct contradiction of this
 * module's own contract comments (sourceStatus.ts:21 "the real backend
 * error, never fabricated"; :28-30 "never fabricates a cause ... anything
 * it does not recognise passes through verbatim").
 *
 * Inputs below are REAL backend strings, composited verbatim from source
 * reads (not invented):
 *   - adzuna_adapter.py:97 `f"Adzuna AU search failed: {type(exc).__name__}: {exc}"`
 *     wrapped by scout_agent.py's `f"{type(exc).__name__}: {exc}"` outer
 *     "AdapterFetchError: " prefix, with `exc` a real httpx.HTTPStatusError
 *     whose message format is httpx's own `Response.raise_for_status()`
 *     (verified against the installed httpx package): "{error_type}
 *     '{status} {reason}' for url '{url}'\nFor more information check:
 *     https://developer.mozilla.org/.../Status/{status}" — a genuinely
 *     multi-line, URL-and-query-string-bearing, >160-char string carrying
 *     Adzuna's app_id/app_key credentials in the query string.
 *   - base_adapter.py:109-114 fixture-mode misconfiguration message
 *     verbatim, wrapped by the same outer "AdapterFetchError: " prefix.
 *   - wellfound_adapter.py:38 `f"Wellfound public listings unavailable: {exc}"`
 *     raised as `SourceBlockedError`, wrapped by scout_agent.py's blocked-path
 *     `f"{type(exc).__name__}: {exc}"` ("SourceBlockedError: ...") — again a
 *     real, multi-line, URL-bearing httpx message.
 *
 * Before the fix, ALL THREE render as a fabricated "temporarily unavailable"
 * claim for what are, in two of the three cases, PERMANENT failures (bad
 * credentials; a structural 403 block) that a retry can never fix.
 */
import { describe, expect, it } from "vitest";

import { humanizeSourceError } from "../../components/dashboard/sourceStatus";

// adzuna_adapter.py:97 + scout_agent.py's `{type(exc).__name__}: {exc}` wrap,
// exc = httpx.HTTPStatusError for a 401 (bad/expired Adzuna credentials —
// PERMANENT until an operator rotates them; a retry cannot fix this).
const ADZUNA_401_CREDENTIAL_FAILURE =
  "AdapterFetchError: Adzuna AU search failed: HTTPStatusError: Client error " +
  "'401 Unauthorized' for url 'https://api.adzuna.com/v1/api/jobs/au/search/1" +
  "?app_id=a1b2c3d4&app_key=k9y8z7w6v5&results_per_page=50&what_or=software+engineer" +
  "&where=Melbourne&max_days_old=30&sort_by=date&content-type=application/json'\n" +
  "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401";

// base_adapter.py:109-114 verbatim, wrapped by scout_agent.py's outer prefix.
// A permanent operator-configuration error (>160 chars, no URL).
const FIXTURE_MODE_MISCONFIGURATION =
  "AdapterFetchError: fixture mode is active (AETHER_DISCOVERY_FIXTURE_DIR=/srv/fixtures) " +
  "but source 'greenhouse' has no recorded payload at /srv/fixtures/greenhouse/jobs.json. " +
  "Record one (or pass fixture=) — refusing to make a live HTTP call while fixture mode " +
  "is configured.";

// wellfound_adapter.py:38-46 + scout_agent.py's blocked-path wrap, exc = a
// real httpx.HTTPStatusError for a structural 403 (PERMANENT — Wellfound
// blocks this deployment on every request; a retry cannot fix this).
const WELLFOUND_403_BLOCK =
  "SourceBlockedError: Wellfound public listings unavailable: Client error " +
  "'403 Forbidden' for url 'https://wellfound.com/role/l/software-engineer'\n" +
  "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403";

describe("humanizeSourceError — honesty over raw/unrecognised errors (NEW-I4-FE-05)", () => {
  it("never claims 'temporarily unavailable' or a retry for a permanent Adzuna credential failure", () => {
    const out = humanizeSourceError(ADZUNA_401_CREDENTIAL_FAILURE, "adzuna");
    expect(out).not.toMatch(/temporarily/i);
    expect(out).not.toMatch(/retry/i);
    // Real cause preserved verbatim, not fabricated away.
    expect(out).toContain("401");
    expect(out).toContain("Unauthorized");
  });

  it("strips the credential-bearing query string from the Adzuna URL", () => {
    const out = humanizeSourceError(ADZUNA_401_CREDENTIAL_FAILURE, "adzuna");
    expect(out).not.toContain("app_id=");
    expect(out).not.toContain("app_key=");
    expect(out).not.toContain("a1b2c3d4");
    expect(out).not.toContain("k9y8z7w6v5");
  });

  it("never claims 'temporarily unavailable' or a retry for a permanent fixture-mode misconfiguration", () => {
    const out = humanizeSourceError(FIXTURE_MODE_MISCONFIGURATION, "greenhouse");
    expect(out).not.toMatch(/temporarily/i);
    expect(out).not.toMatch(/retry/i);
    // Real cause preserved (bounded-length truncation is allowed, but the
    // substance must survive, not be swapped for a generic sentence).
    expect(out).toContain("fixture mode is active");
  });

  it("never claims 'temporarily unavailable' or a retry for a permanent structural block (SourceBlockedError)", () => {
    const out = humanizeSourceError(WELLFOUND_403_BLOCK, "wellfound");
    expect(out).not.toMatch(/temporarily/i);
    expect(out).not.toMatch(/retry/i);
    expect(out).toContain("403");
    expect(out).toContain("Forbidden");
  });

  it("truncates an oversized raw cause to a bounded length instead of discarding it", () => {
    const out = humanizeSourceError(FIXTURE_MODE_MISCONFIGURATION, "greenhouse");
    // Bounded, not unlimited — but not collapsed to a one-line platitude either.
    expect(out.length).toBeLessThan(FIXTURE_MODE_MISCONFIGURATION.length);
    expect(out.length).toBeGreaterThan(40);
  });

  it("never renders a non-empty raw/unrecognised error as empty or an em-dash (NEW-I4-FE-06 c)", () => {
    for (const raw of [ADZUNA_401_CREDENTIAL_FAILURE, FIXTURE_MODE_MISCONFIGURATION, WELLFOUND_403_BLOCK]) {
      const out = humanizeSourceError(raw, "source");
      expect(out.trim().length).toBeGreaterThan(0);
      expect(out.trim()).not.toBe("—");
    }
  });

  it("still humanises a genuinely transient error honestly (no over-correction)", () => {
    // Control: short, non-URL, non-stack-trace text is untouched by this
    // branch and keeps its existing (already-reviewed, unchanged) behaviour.
    const out = humanizeSourceError("AdapterFetchError: ReadTimeout on greenhouse", "greenhouse");
    expect(out).toContain("ReadTimeout on greenhouse");
  });
});
