// @vitest-environment jsdom
/**
 * R1.2 — the shared "what this tells you / what to do next" affordance.
 *
 * The ledger requires every metric visualisation to carry a one-line decision
 * annotation. Analytics already has its local DecisionGuidance; this is the
 * SHARED component the admin surfaces use. RED first: the component and its
 * contract (both lines rendered, testid stable, no empty guidance allowed by
 * type) are asserted before any integration lands.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionGuidance } from "../ui/decision-guidance";

describe("DecisionGuidance (shared)", () => {
  it("renders both the 'what this tells you' and 'what to do next' lines", () => {
    render(
      <DecisionGuidance
        tellsYou="whether paid demand is growing."
        next="if flat for two weeks, review pricing."
      />
    );
    const el = screen.getByTestId("decision-guidance");
    expect(el.textContent).toContain("What this tells you");
    expect(el.textContent).toContain("whether paid demand is growing.");
    expect(el.textContent).toContain("What to do next");
    expect(el.textContent).toContain("if flat for two weeks, review pricing.");
  });

  it("honours a caller-supplied testid so multiple panels stay distinguishable", () => {
    render(<DecisionGuidance testId="guidance-spend" tellsYou="a" next="b" />);
    expect(screen.getByTestId("guidance-spend")).toBeTruthy();
  });
});
