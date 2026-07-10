import { describe, it, expect } from "vitest";
import {
  STAGES,
  addContact,
  buildPipeline,
  computeResponseRate,
  computeStats,
  initialsFor,
  isPipelineEmpty,
  moveContact,
  totalContacts,
  warmthStars,
} from "./crm";
import {
  DEMO_CONTACTS,
  DEMO_RESPONSE_COUNTERS,
  DEMO_STAGE_COUNTS,
} from "./fixtures";
import type { Contact } from "./types";

let seq = 0;
const idFactory = () => `gen-${++seq}`;

describe("STAGES (SC-NTWRK-007)", () => {
  it("declares the five wireframe stages in order", () => {
    expect(STAGES.map((s) => s.stage)).toEqual([
      "new",
      "warm",
      "active",
      "scheduled",
      "placed",
    ]);
  });
});

describe("initialsFor (SC-NTWRK-009)", () => {
  it("uses first+last initial for multi-word names", () => {
    expect(initialsFor("Sarah L.")).toBe("SL");
    expect(initialsFor("Priya R.")).toBe("PR");
  });
  it("handles single-word and empty names", () => {
    expect(initialsFor("Cher")).toBe("CH");
    expect(initialsFor("   ")).toBe("?");
  });
});

describe("buildPipeline (SC-NTWRK-007/008)", () => {
  it("groups demo contacts into ordered columns with authoritative counts", () => {
    const cols = buildPipeline(DEMO_CONTACTS, DEMO_STAGE_COUNTS);
    expect(cols.map((c) => c.stage)).toEqual([
      "new",
      "warm",
      "active",
      "scheduled",
      "placed",
    ]);
    expect(cols.map((c) => c.count)).toEqual([14, 10, 12, 7, 5]);
    // each column materialises exactly its one sample card
    expect(cols.every((c) => c.contacts.length === 1)).toBe(true);
  });

  it("falls back to materialised count when no authoritative counts supplied", () => {
    const cols = buildPipeline(DEMO_CONTACTS);
    expect(cols.every((c) => c.count === 1)).toBe(true);
  });
});

describe("computeStats (SC-NTWRK-006)", () => {
  it("reproduces the four wireframe stat cards exactly", () => {
    const cols = buildPipeline(DEMO_CONTACTS, DEMO_STAGE_COUNTS);
    const stats = computeStats(cols, DEMO_RESPONSE_COUNTERS);
    expect(stats).toEqual({
      totalContacts: 48,
      activeThreads: 12,
      referralsSecured: 5,
      responseRate: 41,
    });
  });
});

describe("computeResponseRate (SC-NTWRK-006)", () => {
  it("rounds to whole percent", () => {
    expect(computeResponseRate({ contacted: 49, replied: 20 })).toBe(41);
  });
  it("returns 0 when nobody contacted (no divide-by-zero)", () => {
    expect(computeResponseRate({ contacted: 0, replied: 0 })).toBe(0);
  });
  it("clamps replies that exceed contacted to 100%", () => {
    expect(computeResponseRate({ contacted: 5, replied: 9 })).toBe(100);
  });
});

describe("totalContacts / isPipelineEmpty (SC-NTWRK-017)", () => {
  it("empty pipeline reports empty", () => {
    const cols = buildPipeline([], { new: 0, warm: 0, active: 0, scheduled: 0, placed: 0 });
    expect(totalContacts(cols)).toBe(0);
    expect(isPipelineEmpty(cols)).toBe(true);
  });
  it("populated pipeline is not empty", () => {
    const cols = buildPipeline(DEMO_CONTACTS, DEMO_STAGE_COUNTS);
    expect(isPipelineEmpty(cols)).toBe(false);
  });
});

describe("warmthStars (SC-NTWRK-010)", () => {
  it("maps warmth to filled/empty flags", () => {
    expect(warmthStars(0)).toEqual([false, false, false]);
    expect(warmthStars(2)).toEqual([true, true, false]);
    expect(warmthStars(3)).toEqual([true, true, true]);
  });
});

describe("addContact (SC-NTWRK-005/018)", () => {
  it("creates a new-stage contact from valid input", () => {
    const res = addContact({ name: "Ada Lovelace", company: "Analytical", role: "Engineer" }, idFactory);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.contact.stage).toBe("new");
      expect(res.contact.warmth).toBe(0);
      expect(res.contact.initials).toBe("AL");
      expect(res.contact.relationship).toBe("recruiter");
    }
  });

  it("rejects blank/whitespace fields with per-field errors", () => {
    const res = addContact({ name: "  ", company: "", role: "" }, idFactory);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.errors).toEqual({
        name: "Name is required.",
        company: "Company is required.",
        role: "Role is required.",
      });
    }
  });
});

describe("moveContact (SC-NTWRK-008)", () => {
  const base: Contact[] = [{ ...DEMO_CONTACTS[0] }];

  it("moves a contact to a valid stage immutably", () => {
    const next = moveContact(base, "nw08", "warm");
    expect(next).not.toBe(base);
    expect(next[0].stage).toBe("warm");
    expect(base[0].stage).toBe("new");
  });
  it("is a no-op for unknown stage", () => {
    expect(moveContact(base, "nw08", "archived")).toBe(base);
  });
  it("is a no-op for unknown id", () => {
    expect(moveContact(base, "nope", "warm")).toBe(base);
  });
});
