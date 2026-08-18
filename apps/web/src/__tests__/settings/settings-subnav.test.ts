/**
 * GAP-P4-062 — the Settings sub-nav order must match design/screens/
 * settings.html's settings-subnav-st06 list (Profile, Resume Management,
 * Portfolio Sync, Notifications, Agent Configuration, Integrations,
 * Privacy & Compliance). Production had Notifications at position 6 instead
 * of position 4.
 *
 * MV-settings-003 later appended an eighth entry, "Billing & Subscription",
 * absent from that wireframe (the wireframe never accounted for billing
 * self-service). SETUP-1 then appended a ninth, "Screening Answers", absent for
 * the same reason (the wireframe predates the Answer Bank). Both are asserted
 * to come AFTER the seven wireframe entries so neither can silently reorder
 * them and re-trip the GAP-P4-062 regression.
 *
 * The guard is written as "the seven are a prefix, in order" plus an explicit
 * index per appended entry, rather than as a frozen total length: a fixed
 * length turns every future addition into a failing test with no defect behind
 * it, which trains the next author to edit the guard instead of reading it.
 */
import { describe, expect, it } from "vitest";

import { SECTIONS } from "../../app/dashboard/settings/sections";

const WIREFRAME_ORDER = [
  "Profile",
  "Resume Management",
  "Portfolio Sync",
  "Notifications",
  "Agent Configuration",
  "Integrations",
  "Privacy & Compliance",
];

describe("Settings sub-nav order", () => {
  it("matches the settings.html wireframe order exactly for the seven original entries", () => {
    expect(SECTIONS.slice(0, WIREFRAME_ORDER.length).map((s) => s.label)).toEqual(WIREFRAME_ORDER);
  });

  it("places Notifications at position 4 (index 3), not position 6", () => {
    expect(SECTIONS.findIndex((s) => s.id === "notifications")).toBe(3);
  });

  it("appends Billing & Subscription (MV-settings-003) after the seven wireframe entries", () => {
    expect(SECTIONS[7]).toEqual({ id: "billing", label: "Billing & Subscription" });
  });

  it("appends Screening Answers (SETUP-1) after Billing, still after the wireframe seven", () => {
    expect(SECTIONS[8]).toEqual({ id: "screening", label: "Screening Answers" });
  });

  it("never lets an appended entry displace a wireframe-pinned one", () => {
    for (const [index, label] of WIREFRAME_ORDER.entries()) {
      expect(SECTIONS[index].label).toBe(label);
    }
    expect(new Set(SECTIONS.map((s) => s.id)).size).toBe(SECTIONS.length);
  });
});
