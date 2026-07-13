import { describe, expect, it } from "vitest";

import type { NetworkingContact, NetworkingSummary } from "../../../../lib/api/workspaces";
import { STAGE_ACCENT, buildPipelineColumns, initials, totalContacts } from "../lib";

/**
 * Regression coverage for GAP-P4-052: the Networking page must render a
 * Kanban board of per-contact cards bound to real contacts, not a tab/pill
 * summary — and stages with no real contacts must show an honest empty
 * state rather than fabricated cards.
 */

function contact(overrides: Partial<NetworkingContact> = {}): NetworkingContact {
  return { name: "Sarah L.", role: "Recruiter", company: "Atlassian", warmth: 2, ...overrides };
}

/** A pipeline fixture matching the shape GET /workspaces/networking/summary
 * returns after bucketing real Contact rows by stage — one real contact in
 * "New", every other stage genuinely empty. */
function pipelineFixture(): NetworkingSummary["pipeline"] {
  return [
    { stage: "New", count: 1, contacts: [contact()] },
    { stage: "Warm", count: 0, contacts: [] },
    { stage: "Active", count: 0, contacts: [] },
    { stage: "Scheduled", count: 0, contacts: [] },
    { stage: "Placed", count: 0, contacts: [] },
  ];
}

describe("buildPipelineColumns", () => {
  it("renders one column per stage, carrying real contacts into their column", () => {
    const columns = buildPipelineColumns(pipelineFixture());
    expect(columns.map((c) => c.stage)).toEqual(["New", "Warm", "Active", "Scheduled", "Placed"]);
    expect(columns[0].count).toBe(1);
    expect(columns[0].contacts).toEqual([contact()]);
  });

  it("gives every contact-less stage an honest empty column (no fabricated cards)", () => {
    const columns = buildPipelineColumns(pipelineFixture());
    const emptyColumns = columns.filter((c) => c.stage !== "New");
    for (const col of emptyColumns) {
      expect(col.count).toBe(0);
      expect(col.contacts).toEqual([]);
    }
  });

  it("merges locally-added contacts into the New column and adds to its count", () => {
    const added = [contact({ name: "New Guy", company: "Acme", warmth: 1 })];
    const columns = buildPipelineColumns(pipelineFixture(), added);
    const newColumn = columns.find((c) => c.stage === "New")!;
    expect(newColumn.count).toBe(2);
    expect(newColumn.contacts.map((c) => c.name)).toEqual(["New Guy", "Sarah L."]);
  });

  it("does not leak locally-added contacts into other columns", () => {
    const added = [contact({ name: "New Guy" })];
    const columns = buildPipelineColumns(pipelineFixture(), added);
    for (const col of columns.filter((c) => c.stage !== "New")) {
      expect(col.contacts).toEqual([]);
      expect(col.count).toBe(0);
    }
  });

  it("preserves multiple real contacts within the same stage", () => {
    const fixture: NetworkingSummary["pipeline"] = [
      {
        stage: "Active",
        count: 2,
        contacts: [
          contact({ name: "Priya R.", company: "ANZ" }),
          contact({ name: "Mark K.", company: "Canva" }),
        ],
      },
    ];
    const columns = buildPipelineColumns(fixture);
    expect(columns[0].count).toBe(2);
    expect(columns[0].contacts).toHaveLength(2);
  });
});

describe("totalContacts", () => {
  it("sums server-reported contacts with locally-added ones", () => {
    const stats = { contacts: 1, activeConversations: 0, referralsInFlight: 0, responseRate: 0 };
    expect(totalContacts(stats, [])).toBe(1);
    expect(totalContacts(stats, [contact(), contact()])).toBe(3);
  });
});

describe("initials", () => {
  it("takes the first letter of up to the first two words, upper-cased", () => {
    expect(initials("Sarah L.")).toBe("SL");
    expect(initials("Dan")).toBe("D");
    expect(initials("mark k")).toBe("MK");
  });
});

describe("STAGE_ACCENT", () => {
  it("defines an accent for every wireframe pipeline stage", () => {
    expect(Object.keys(STAGE_ACCENT).sort()).toEqual(
      ["Active", "New", "Placed", "Scheduled", "Warm"].sort(),
    );
  });
});
