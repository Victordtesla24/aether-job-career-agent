/**
 * GAP-P4-062 — the Settings sub-nav order must match design/screens/
 * settings.html's settings-subnav-st06 list (Profile, Resume Management,
 * Portfolio Sync, Notifications, Agent Configuration, Integrations,
 * Privacy & Compliance). Production had Notifications at position 6 instead
 * of position 4.
 *
 * MV-settings-003 later appended an eighth entry, "Billing & Subscription",
 * absent from that wireframe (the wireframe never accounted for billing
 * self-service). It is asserted to come AFTER the seven wireframe entries so
 * it can never silently reorder them and re-trip the GAP-P4-062 regression.
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
    expect(SECTIONS.length).toBe(8);
    expect(SECTIONS[SECTIONS.length - 1]).toEqual({ id: "billing", label: "Billing & Subscription" });
  });
});
