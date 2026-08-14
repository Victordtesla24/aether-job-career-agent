// @vitest-environment jsdom
/**
 * S-UI B3 — the aha moment may not out-claim its measurements.
 *
 * This hero is the most persuasive surface in the product, which makes it the
 * most dangerous one: it is where a "wow" number would be cheapest to fake.
 * These tests pin the four refusals that keep it honest.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import AhaHero, { type AhaHeroProps } from "../AhaHero";

const BASE: AhaHeroProps = {
  jobTitle: "Graduate Project Controller",
  company: "KBR",
  beforeAts: 55,
  afterAts: 59,
  unmeasuredReason: null,
  changesRequested: 3,
  changesApplied: 3,
  changesDropped: 0,
  evidenceCovered: 3,
  evidenceTotal: 3,
  versionLabel: "Tailored — Graduate Project Controller @ KBR",
};

function renderHero(overrides: Partial<AhaHeroProps> = {}) {
  render(<AhaHero {...BASE} {...overrides} />);
  return screen.getByTestId("aha-hero");
}

afterEach(cleanup);

describe("AhaHero — the measured case", () => {
  it("prints both scores and the exact signed delta", () => {
    renderHero();
    expect(screen.getByTestId("aha-ats-before").textContent).toBe("55");
    expect(screen.getByTestId("aha-ats-after").textContent).toBe("59");
    expect(screen.getByTestId("aha-ats-delta").textContent).toBe("+4");
  });

  it("prints a NEGATIVE delta rather than hiding it", () => {
    renderHero({ beforeAts: 62, afterAts: 58 });
    expect(screen.getByTestId("aha-ats-delta").textContent).toBe("-4");
  });

  it("prints ±0 rather than blank when the tailoring moved nothing", () => {
    renderHero({ beforeAts: 60, afterAts: 60 });
    expect(screen.getByTestId("aha-ats-delta").textContent).toBe("±0");
  });
});

describe("AhaHero — refuses to claim what was not measured", () => {
  it("shows a dash and the API's own reason when a half is unmeasured", () => {
    const hero = renderHero({
      afterAts: null,
      unmeasuredReason: "the semantic scoring model was unavailable",
    });
    expect(screen.getByTestId("aha-ats-after").textContent).toBe("—");
    expect(screen.getByTestId("aha-ats-delta").textContent).toBe("not measured");
    expect(hero.textContent).toMatch(/semantic scoring model was unavailable/);
    // The measured half must not be silently turned into a delta.
    expect(screen.getByTestId("aha-ats-delta").textContent).not.toMatch(/\d/);
  });

  it("never subtracts against a missing baseline", () => {
    renderHero({ beforeAts: null, unmeasuredReason: null });
    expect(screen.getByTestId("aha-ats-before").textContent).toBe("—");
    expect(screen.getByTestId("aha-ats-delta").textContent).toBe("not measured");
  });
});

describe("AhaHero — the Verified chip is gated on the API's own counts", () => {
  it("earns the verified wording only when nothing was dropped", () => {
    renderHero();
    const chip = screen.getByTestId("aha-verified-chip");
    expect(chip.textContent).toMatch(/Verified · all 3 changes present/);
  });

  it("states the shortfall — never 'verified' — when changes were dropped", () => {
    const chip = renderHero({ changesApplied: 2, changesDropped: 1 }).querySelector(
      '[data-testid="aha-verified-chip"]',
    )!;
    expect(chip.textContent).toMatch(/2 of 3 changes verified in the file/);
    expect(chip.textContent).not.toMatch(/^Verified/);
  });

  it("says verification is unavailable — not 'verified' — when the report is absent", () => {
    const chip = renderHero({
      changesRequested: null,
      changesApplied: null,
      changesDropped: null,
    }).querySelector('[data-testid="aha-verified-chip"]')!;
    expect(chip.textContent).toMatch(/verification not available/i);
    expect(chip.textContent).not.toMatch(/all \d+ changes present/);
  });
});

describe("AhaHero — the evidence claim is counted, not asserted", () => {
  it("makes the absolute claim only when every change carries an evidence ref", () => {
    const hero = renderHero({ evidenceCovered: 3, evidenceTotal: 3 });
    expect(hero.textContent).toMatch(/Every rewritten line below traces back to evidence/);
  });

  it("states the exact coverage when some changes have no evidence ref", () => {
    const hero = renderHero({ evidenceCovered: 2, evidenceTotal: 5 });
    expect(hero.textContent).toMatch(/2 of 5 rewritten lines carry an evidence reference/);
    expect(hero.textContent).not.toMatch(/Every rewritten line below traces/);
  });
});

describe("AhaHero — the loading state claims nothing at all", () => {
  it("renders a skeleton instead of a premature 'not measured' verdict", () => {
    const hero = renderHero({
      loading: true,
      beforeAts: null,
      afterAts: null,
      changesRequested: null,
      changesApplied: null,
      changesDropped: null,
      evidenceCovered: 0,
      evidenceTotal: 0,
    });
    expect(hero.getAttribute("data-state")).toBe("loading");
    expect(hero.getAttribute("aria-busy")).toBe("true");
    expect(hero.textContent).not.toMatch(/not measured/i);
    expect(hero.textContent).not.toMatch(/verification not available/i);
    expect(screen.queryByTestId("aha-ats-delta")).toBeNull();
  });
});
