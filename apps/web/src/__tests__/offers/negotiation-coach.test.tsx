// @vitest-environment jsdom
/**
 * MV-offer-comparison-002 — the Negotiation Coach must never render a fabricated
 * "$0 base" counter. When the server sends suggestedCounter=null it shows an
 * honest "add an offer" state with no draft-email affordance; when it sends a
 * real computed number it shows it, and the draft email references that number
 * and contains no fabricated names/roles/cities.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NegotiationCoach } from "../../components/offers/NegotiationCoach";

afterEach(cleanup);

describe("NegotiationCoach honest counter (MV-offer-comparison-002)", () => {
  it("shows an honest add-an-offer state (no $0, no draft button) when counter is null", () => {
    render(
      <NegotiationCoach
        negotiation={{ insight: "Add an offer with a base salary.", suggestedCounter: null, leverage: [] }}
      />,
    );
    const counter = screen.getByTestId("suggested-counter");
    expect(counter.textContent ?? "").not.toContain("$0");
    expect((counter.textContent ?? "").toLowerCase()).toContain("add an offer");
    expect(screen.queryByTestId("draft-counter-btn")).toBeNull();
    expect(screen.queryByTestId("counter-email-draft")).toBeNull();
  });

  it("renders the computed counter and a draft email referencing it, with no fabricated specifics", () => {
    render(
      <NegotiationCoach
        negotiation={{
          insight: "Your strongest base offer is $185,000.",
          suggestedCounter: 204000,
          leverage: ["You hold 2 active offers — competing offers are your strongest leverage."],
        }}
      />,
    );
    expect(screen.getByTestId("suggested-counter").textContent ?? "").toContain("$204,000");

    fireEvent.click(screen.getByTestId("draft-counter-btn"));
    const draft = screen.getByTestId("counter-email-draft").textContent ?? "";
    expect(draft).toContain("$204,000");
    expect(draft).not.toContain("$0");
    expect(draft).not.toContain("Emma");
    expect(draft).not.toContain("Sydney");
    expect(draft).not.toContain("Senior TPM");
  });
});
