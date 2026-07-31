/**
 * GOLD-MASTER-V2 §12.4 / W-J item 5 — Application/tracker card shows NO ATS
 * score.
 *
 * MEASURED ground truth for this run: production Job rows carry BOTH
 * `fitScore` and `atsScore` (`apps/web/src/lib/api/jobs.ts:35`:
 * `atsScore: z.number().nullish()`). The Application Tracker board renders
 * `fitScore` (as "fit", via `StageCard.fit` / `fitClass`) but `atsScore` is
 * read NOWHERE in the tracker pipeline:
 *   - `TrackerApplicationSchema` (tracker-api.ts) extends `ApplicationSchema`
 *     with only `answers` and `fitScore` — no `atsScore` field, so zod's
 *     default "strip unknown keys" behaviour silently drops it even if the
 *     API returns it on an Application row.
 *   - `StageCard` (tracker-lib.ts) has only a `fit?: number` field; `atsScore`
 *     is never read off either `Job` or `TrackerApplication` in `buildStages`.
 *
 * This is the "sibling test found NO score shown" gap referenced by the
 * W-J brief: the Application/tracker card never surfaces the ATS score at
 * all, at any layer from the network schema down to the rendered card.
 *
 * Pure-function / pure-schema tests only — no DOM needed, matching this
 * module's own stated test philosophy ("Everything here is side-effect
 * free so ... unit-testable without a DOM").
 */
import { describe, expect, it } from "vitest";

import type { Job } from "../../../lib/api/jobs";
import { TrackerApplicationSchema, type TrackerApplication } from "../tracker-api";
import { buildStages } from "../tracker-lib";

function job(over: Partial<Job>): Job {
  return {
    id: "j1",
    title: "Engineer",
    company: "Acme",
    status: "discovered",
    remote: false,
    saved: false,
    ...over,
  } as Job;
}

function rawApplicationPayload(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "a1",
    jobId: "j1",
    resumeId: "r1",
    status: "draft",
    jobTitle: "Engineer",
    company: "Acme",
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    fitScore: 62,
    atsScore: 88,
    ...over,
  };
}

describe("W-J item 5 — ATS score never reaches the Application/tracker card", () => {
  it("TrackerApplicationSchema preserves atsScore from a live API payload", () => {
    const parsed = TrackerApplicationSchema.parse(rawApplicationPayload());
    // §12.4: the tracker card must be able to show the ATS score. It can't
    // — the schema doesn't declare the field, so zod's default "strip
    // unknown keys" parsing silently drops it even though the raw payload
    // carries a distinct atsScore (88) from fitScore (62).
    expect((parsed as unknown as { atsScore?: number }).atsScore).toBe(88);
  });

  it("buildStages exposes a distinct ATS score on job-pipeline cards, not just fit", () => {
    // fitScore and atsScore deliberately differ so the assertion can't be
    // satisfied by accident via the existing `fit` field.
    const j = job({ id: "j-ats", status: "discovered", fitScore: 55, atsScore: 91 });
    const stages = buildStages([], [j]);
    const card = stages.flatMap((s) => s.cards).find((c) => c.id === "job-j-ats");

    expect(card).toBeTruthy();
    expect(card!.fit).toBe(55); // fit score already works
    // ATS score (91) must also be exposed somewhere on the card — it isn't;
    // StageCard has no atsScore field at all.
    expect((card as unknown as { atsScore?: number })?.atsScore).toBe(91);
  });

  it("buildStages exposes a distinct ATS score on application cards, not just fit", () => {
    const apps: TrackerApplication[] = [
      TrackerApplicationSchema.parse(
        rawApplicationPayload({ status: "submitted", fitScore: 62, atsScore: 88 }),
      ),
    ];
    const stages = buildStages(apps, []);
    const card = stages.flatMap((s) => s.cards).find((c) => c.id === "a1");

    expect(card).toBeTruthy();
    expect((card as unknown as { atsScore?: number })?.atsScore).toBe(88);
  });
});
