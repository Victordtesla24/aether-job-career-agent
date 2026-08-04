/**
 * F-02 (PROD-UAT-2026-08-03) — the discovery search target must be derived
 * from the SIGNED-IN user, and must never be substituted with someone else's.
 *
 * The defect this guards: /dashboard/jobs posted a literal
 * `{query: "delivery lead, product owner, program manager, business analyst",
 *   location: "Australia"}` for every user, so a Senior Data Scientist with an
 * empty profile had 1,621 project-management postings dumped into their
 * account. The rule encoded here is that `deriveSearchTarget` has NO default
 * query of its own: with nothing configured it returns `needs-input`, which
 * the UI turns into a question, never into a search.
 */
import { describe, expect, it } from "vitest";

import { deriveSearchTarget } from "../search-target";

describe("deriveSearchTarget (F-02)", () => {
  it("uses the signed-in user's own target role and location", () => {
    const target = deriveSearchTarget({
      targetRole: "Senior Data Scientist",
      location: "Sydney, Australia",
    });
    expect(target).toEqual({
      status: "ready",
      query: "Senior Data Scientist",
      location: "Sydney, Australia",
      source: "profile",
    });
  });

  it("gives two different users two different queries", () => {
    const a = deriveSearchTarget({ targetRole: "Senior Data Scientist", location: "Sydney, Australia" });
    const b = deriveSearchTarget({ targetRole: "Registered Nurse", location: "Auckland, New Zealand" });
    expect(a.status).toBe("ready");
    expect(b.status).toBe("ready");
    expect(a).not.toEqual(b);
  });

  it("trims surrounding whitespace rather than treating it as a real value", () => {
    expect(deriveSearchTarget({ targetRole: "  Data Engineer  ", location: " Perth, WA " })).toEqual({
      status: "ready",
      query: "Data Engineer",
      location: "Perth, WA",
      source: "profile",
    });
  });

  it("asks instead of searching when the profile has no target role", () => {
    const target = deriveSearchTarget({ targetRole: "", location: "Melbourne, Australia" });
    expect(target.status).toBe("needs-input");
    if (target.status !== "needs-input") throw new Error("unreachable");
    expect(target.missing).toEqual(["role"]);
    // The known half is offered back as a prefill, never as a licence to run.
    expect(target.location).toBe("Melbourne, Australia");
  });

  it("asks instead of searching when the profile has no location", () => {
    const target = deriveSearchTarget({ targetRole: "Senior Data Scientist", location: "" });
    expect(target.status).toBe("needs-input");
    if (target.status !== "needs-input") throw new Error("unreachable");
    expect(target.missing).toEqual(["location"]);
    expect(target.role).toBe("Senior Data Scientist");
  });

  it("asks — and prefills nothing — for a brand-new empty profile", () => {
    const target = deriveSearchTarget({ targetRole: "", location: "" });
    expect(target.status).toBe("needs-input");
    if (target.status !== "needs-input") throw new Error("unreachable");
    expect(target.missing).toEqual(["role", "location"]);
    expect(target.role).toBe("");
    expect(target.location).toBe("");
  });

  it("asks when the profile could not be loaded at all — never guesses", () => {
    expect(deriveSearchTarget(null).status).toBe("needs-input");
    expect(deriveSearchTarget(undefined).status).toBe("needs-input");
  });

  it("never emits a query the user did not supply", () => {
    // Exhaustive over the empty-profile shapes: no branch may produce a
    // `ready` target carrying a role nobody typed. This is the assertion that
    // fails if a "sensible default" is ever reintroduced.
    for (const profile of [
      null,
      undefined,
      { targetRole: "", location: "" },
      { targetRole: "   ", location: "   " },
      { targetRole: "", location: "Australia" },
    ]) {
      expect(deriveSearchTarget(profile).status).toBe("needs-input");
    }
  });

  it("treats a role typed into the prompt as the user's own, not the profile's", () => {
    const target = deriveSearchTarget(
      { targetRole: "", location: "" },
      { role: "Senior Data Scientist", location: "Sydney, Australia" },
    );
    expect(target).toEqual({
      status: "ready",
      query: "Senior Data Scientist",
      location: "Sydney, Australia",
      source: "entered",
    });
  });

  it("still asks when the prompt itself was left half-empty", () => {
    expect(deriveSearchTarget({ targetRole: "", location: "" }, { role: "Data Scientist", location: "  " }).status)
      .toBe("needs-input");
  });
});
