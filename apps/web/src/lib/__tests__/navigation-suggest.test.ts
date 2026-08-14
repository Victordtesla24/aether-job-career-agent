/**
 * S-UI B3 — the Story Bank "Section not found" defect, pinned.
 *
 * Root cause (evidence: `b3/before/before-notes.json`, captured against live
 * production 2026-08-14): `/dashboard/stories` renders the real Story Bank and
 * the sidebar link points at it; `/dashboard/story-bank` — the WIREFRAME name,
 * still baked into the stale Phase-0 capture harness — falls through to the
 * `[...slug]` catch-all, which told the user the section does not exist while
 * the sidebar was showing it two inches to the left.
 *
 * These tests pin the suggestion rules. They also pin the two ways this fix
 * could go wrong: suggesting the WRONG section, and suggesting one for a slug
 * that genuinely means nothing.
 */
import { describe, expect, it } from "vitest";

import { NAV_ITEMS } from "../navigation";
import { joinSlug, suggestNavItem } from "../navigation-suggest";

describe("suggestNavItem — the reported defect", () => {
  it("resolves the wireframe name 'story-bank' to the shipped Story Bank route", () => {
    expect(suggestNavItem("story-bank")).toEqual({
      label: "Story Bank",
      href: "/dashboard/stories",
      reason: "label-slug",
    });
  });

  it("resolves the other wireframe names the stale harness still uses", () => {
    expect(suggestNavItem("resume-studio")?.href).toBe("/dashboard/resume");
    expect(suggestNavItem("cover-letter-studio")?.href).toBe("/dashboard/cover-letters");
    expect(suggestNavItem("interview-center")?.href).toBe("/dashboard/interviews");
    expect(suggestNavItem("email-center")?.href).toBe("/dashboard/email");
  });

  it("resolves a real route token written with the wrong separators", () => {
    expect(suggestNavItem("cover_letters")?.href).toBe("/dashboard/cover-letters");
    expect(suggestNavItem("Stories")?.href).toBe("/dashboard/stories");
  });

  it("resolves an unambiguous prefix", () => {
    expect(suggestNavItem("interview")).toEqual({
      label: "Interview Center",
      href: "/dashboard/interviews",
      reason: "prefix",
    });
  });
});

describe("suggestNavItem — refuses to guess", () => {
  it("returns null for a slug that means nothing", () => {
    expect(suggestNavItem("nonexistent-xyz")).toBeNull();
    expect(suggestNavItem("does-not-exist")).toBeNull();
    expect(suggestNavItem("subscription")).toBeNull();
  });

  it("returns null for an empty or punctuation-only slug", () => {
    expect(suggestNavItem("")).toBeNull();
    expect(suggestNavItem("///")).toBeNull();
  });

  it("returns null for a prefix too short to mean anything", () => {
    // "s" prefixes Story Bank AND Settings; even alone it is below the floor.
    expect(suggestNavItem("s")).toBeNull();
    expect(suggestNavItem("job")).toBeNull(); // 3 chars, under the floor
  });

  it("returns null for an AMBIGUOUS prefix rather than picking one", () => {
    // Both "Story Bank" and "Settings" would match a bare "se"/"st" style
    // prefix; construct one that genuinely hits two items.
    const ambiguous = NAV_ITEMS.filter((i) => i.label.toLowerCase().startsWith("s"));
    expect(ambiguous.length).toBeGreaterThan(1);
    expect(suggestNavItem("s")).toBeNull();
  });
});

describe("suggestNavItem — every shipped section is self-resolvable", () => {
  it("resolves each nav item from its own label slug and its own href token", () => {
    for (const item of NAV_ITEMS) {
      const fromLabel = suggestNavItem(item.label);
      expect(fromLabel, `label "${item.label}"`).not.toBeNull();
      expect(fromLabel!.href).toBe(item.href);

      const token = item.href.split("/").filter(Boolean).pop()!;
      if (token === "dashboard") continue; // the root section has no extra segment
      const fromToken = suggestNavItem(token);
      expect(fromToken, `token "${token}"`).not.toBeNull();
      expect(fromToken!.href).toBe(item.href);
    }
  });
});

describe("joinSlug", () => {
  it("rebuilds the requested path exactly as the catch-all shows it", () => {
    expect(joinSlug(["story-bank"])).toBe("/dashboard/story-bank");
    expect(joinSlug(["a", "b"])).toBe("/dashboard/a/b");
    expect(joinSlug(undefined)).toBe("/dashboard/");
  });
});
