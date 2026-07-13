/**
 * GAP-P4-062 — the Settings sub-nav order must match design/screens/
 * settings.html's settings-subnav-st06 list (Profile, Resume Management,
 * Portfolio Sync, Notifications, Agent Configuration, Integrations,
 * Privacy & Compliance). Production had Notifications at position 6 instead
 * of position 4.
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
  it("matches the settings.html wireframe order exactly", () => {
    expect(SECTIONS.map((s) => s.label)).toEqual(WIREFRAME_ORDER);
  });

  it("places Notifications at position 4 (index 3), not position 6", () => {
    expect(SECTIONS.findIndex((s) => s.id === "notifications")).toBe(3);
  });
});
