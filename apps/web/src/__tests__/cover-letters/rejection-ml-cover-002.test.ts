import { describe, expect, it } from "vitest";

import { ApiError } from "../../lib/api/client";
import { parseCoverLetterRejection } from "../../components/cover-letters/rejection";

/**
 * ML-cover-002(b) — failing tests BEFORE fix (MODELS-LIVE §7 step 2).
 *
 * RCA verified against CURRENT code (2026-07-22):
 * - `resolveRun` (apps/web/src/lib/api/agents.ts:92-97) throws, on ANY
 *   failed async background job, a hardcoded
 *   `new ApiError(job.error?.trim() || "Generation failed. Please try
 *   again.", 502)`. The message is the RAW `job.error` string — it does NOT
 *   carry the `"POST ... failed (xxx): {json}"` wrapper a direct HTTP error
 *   from `apiRequest` has (`extractDetail` in rejection.ts looks for that
 *   wrapper's `"): "` delimiter to find the embedded JSON `detail`).
 * - `parseCoverLetterRejection` (apps/web/src/components/cover-letters/
 *   rejection.ts:74, `if (!(error instanceof ApiError) || error.status !==
 *   422) return null;`) rejects the async 502 shape before its message is
 *   ever inspected, regardless of content.
 *
 * Because of this status-code mismatch (422 sync vs 502 async), an async
 * single-agent cover-letter run that fails with an honest fabrication/
 * structural guard message can NEVER surface the dedicated rejection panel
 * — it falls through to the generic error banner instead (rejection panel
 * structurally unreachable for the async path, per PIPELINE-RCA ML-cover-002).
 *
 * Target behaviour (not yet implemented): the matcher also recognizes the
 * async failure shape — a 502 ApiError whose message carries the SAME guard
 * wording the sync 422 path uses — and still returns a non-null
 * rejection-panel model.
 */
describe("parseCoverLetterRejection — ML-cover-002(b) async (502) failure shape", () => {
  it("recognizes a fabrication-guard rejection surfaced via the async job's 502 ApiError", () => {
    // Shape resolveRun() actually throws today: raw job.error text at status
    // 502 — NOT the "POST ... failed (422): {...}" wrapper a direct HTTP
    // error carries.
    const asyncFailure = new ApiError(
      "Cover letter rejected by fabrication guard: ['Kubernetes', 'Series B']",
      502,
    );
    const model = parseCoverLetterRejection(asyncFailure);
    expect(model).not.toBeNull();
    expect(model?.guard).toBe("fabrication");
    expect(model?.items).toEqual(["Kubernetes", "Series B"]);
  });

  it("recognizes a structural-contract rejection surfaced via the async job's 502 ApiError", () => {
    const asyncFailure = new ApiError(
      "Cover letter rejected — §10.2 format contract not met: " +
        "['missing a specific call-to-action']",
      502,
    );
    const model = parseCoverLetterRejection(asyncFailure);
    expect(model).not.toBeNull();
    expect(model?.guard).toBe("structural");
    expect(model?.items).toEqual(["missing a specific call-to-action"]);
  });
});
