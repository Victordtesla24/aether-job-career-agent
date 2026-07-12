/** AGT-APPS — pure board logic tests (stage mapping, fit colour, time, filter/sort). */
import { describe, expect, it } from "vitest";

import type { Job } from "../../../lib/api/jobs";
import type { TrackerApplication } from "../tracker-api";
import {
  STAGE_DEFS,
  buildStages,
  cardMatchesFilter,
  fitClass,
  initials,
  shortDate,
  sortCards,
  timeAgo,
  viewStages,
  type StageCard,
} from "../tracker-lib";

const NOW = new Date("2026-07-10T12:00:00Z").getTime();

function app(over: Partial<TrackerApplication>): TrackerApplication {
  return {
    id: "a1",
    jobId: "j1",
    resumeId: "r1",
    status: "draft",
    jobTitle: "Engineer",
    company: "Acme",
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    ...over,
  } as TrackerApplication;
}

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

describe("STAGE_DEFS", () => {
  it("has the 8 wireframe stages in order with wireframe labels", () => {
    expect(STAGE_DEFS.map((s) => s.label)).toEqual([
      "Discovered",
      "Evaluating",
      "Tailoring",
      "Ready to Apply",
      "Submitted",
      "In Review",
      "Interview",
      "Offer",
    ]);
  });
});

describe("buildStages", () => {
  it("maps application statuses to the last five stages", () => {
    const stages = buildStages(
      [
        app({ id: "a1", status: "draft" }),
        app({ id: "a2", jobId: "j2", status: "submitted" }),
        app({ id: "a3", jobId: "j3", status: "screening" }),
        app({ id: "a4", jobId: "j4", status: "interview" }),
        app({ id: "a5", jobId: "j5", status: "offer" }),
        app({ id: "a6", jobId: "j6", status: "rejected" }),
      ],
      [],
    );
    const byKey = Object.fromEntries(stages.map((s) => [s.key, s.cards.map((c) => c.id)]));
    expect(byKey["ready"]).toEqual(["a1"]);
    expect(byKey["submitted"]).toEqual(["a2"]);
    expect(byKey["in-review"]).toEqual(["a3"]);
    expect(byKey["interview"]).toEqual(["a4"]);
    expect(byKey["offer"]).toEqual(["a5"]);
    // rejected never lands on the board
    expect(stages.flatMap((s) => s.cards.map((c) => c.id))).not.toContain("a6");
  });

  it("maps pipeline jobs to the first three stages, excluding applied-to jobs", () => {
    const stages = buildStages(
      [app({ id: "a1", jobId: "j-applied", status: "submitted" })],
      [
        job({ id: "j-d", status: "discovered" }),
        job({ id: "j-s", status: "screening" }),
        job({ id: "j-m", status: "matched" }),
        job({ id: "j-t", status: "tailoring" }),
        job({ id: "j-applied", status: "applied" }),
      ],
    );
    const byKey = Object.fromEntries(stages.map((s) => [s.key, s.cards.map((c) => c.id)]));
    expect(byKey["discovered"]).toEqual(["job-j-d"]);
    expect(byKey["evaluating"]).toEqual(["job-j-s", "job-j-m"]);
    expect(byKey["tailoring"]).toEqual(["job-j-t"]);
    // the applied job is represented by its application card, not a job card
    expect(stages.flatMap((s) => s.cards.map((c) => c.id))).not.toContain("job-j-applied");
  });

  it("prefers the application's own fitScore, falling back to the job's", () => {
    const stages = buildStages(
      [
        app({ id: "a1", jobId: "jx", status: "offer", fitScore: 95.4 }),
        app({ id: "a2", jobId: "j-f", status: "interview" }),
      ],
      [job({ id: "j-f", status: "applied", fitScore: 88.2 })],
    );
    const offer = stages.find((s) => s.key === "offer")!.cards[0];
    const interview = stages.find((s) => s.key === "interview")!.cards[0];
    expect(offer.fit).toBe(95);
    expect(interview.fit).toBe(88);
  });

  it("exposes answers as tracker metadata", () => {
    const stages = buildStages(
      [app({ id: "a1", status: "offer", answers: { offerAmount: "$225k", offerDeadline: "2026-07-18" } })],
      [],
    );
    expect(stages.find((s) => s.key === "offer")!.cards[0].meta.offerAmount).toBe("$225k");
  });
});

describe("fitClass / initials / time formatting", () => {
  it("colours ≥85 green and <85 amber (wireframe 94 green / 81 amber)", () => {
    expect(fitClass(94)).toContain("green");
    expect(fitClass(85)).toContain("green");
    expect(fitClass(84)).toContain("yellow");
    expect(fitClass(81)).toContain("yellow");
  });

  it("builds initials from up to two words", () => {
    expect(initials("Canva")).toBe("C");
    expect(initials("Queensland Government")).toBe("QG");
    expect(initials("")).toBe("?");
  });

  it("formats relative time like the wireframe", () => {
    expect(timeAgo(new Date(NOW - 2 * 60_000).toISOString(), NOW)).toBe("2 min ago");
    expect(timeAgo(new Date(NOW - 30_000).toISOString(), NOW)).toBe("just now");
    expect(timeAgo(new Date(NOW - 3 * 3_600_000).toISOString(), NOW)).toBe("3 h ago");
    expect(timeAgo(new Date(NOW - 4 * 86_400_000).toISOString(), NOW)).toBe("4 d ago");
    expect(timeAgo("garbage", NOW)).toBe("—");
  });

  it("formats short badge dates", () => {
    expect(shortDate("2026-07-03")).toBe("Jul 3");
  });
});

describe("filter / sort", () => {
  const cards: StageCard[] = [
    { id: "c1", title: "A", company: "Zeta", updatedAt: "2026-07-09T00:00:00Z", fit: 92, meta: {} },
    { id: "c2", title: "B", company: "Alpha", updatedAt: "2026-07-10T00:00:00Z", fit: 78, meta: {} },
    {
      id: "c3",
      title: "C",
      company: "Mid",
      updatedAt: "2026-07-08T00:00:00Z",
      fit: 87,
      app: app({ id: "c3", status: "draft" }),
      meta: {},
    },
  ];

  it("filters by fit threshold and needs-approval", () => {
    expect(cards.filter((c) => cardMatchesFilter(c, "high-fit")).map((c) => c.id)).toEqual([
      "c1",
      "c3",
    ]);
    expect(cards.filter((c) => cardMatchesFilter(c, "below-fit")).map((c) => c.id)).toEqual(["c2"]);
    expect(cards.filter((c) => cardMatchesFilter(c, "needs-approval")).map((c) => c.id)).toEqual([
      "c3",
    ]);
    expect(cards.filter((c) => cardMatchesFilter(c, "all"))).toHaveLength(3);
  });

  it("sorts by recency, fit and company without mutating input", () => {
    const original = [...cards];
    expect(sortCards(cards, "recent").map((c) => c.id)).toEqual(["c2", "c1", "c3"]);
    expect(sortCards(cards, "fit").map((c) => c.id)).toEqual(["c1", "c3", "c2"]);
    expect(sortCards(cards, "company").map((c) => c.id)).toEqual(["c2", "c3", "c1"]);
    expect(cards).toEqual(original);
  });

  it("viewStages applies both to every stage", () => {
    const stages = buildStages(
      [
        app({ id: "a1", status: "draft", fitScore: 90, updatedAt: "2026-07-09T00:00:00Z" }),
        app({ id: "a2", jobId: "j2", status: "draft", fitScore: 70, updatedAt: "2026-07-10T00:00:00Z" }),
      ],
      [],
    );
    const filtered = viewStages(stages, "high-fit", "fit");
    expect(filtered.find((s) => s.key === "ready")!.cards.map((c) => c.id)).toEqual(["a1"]);
  });
});
