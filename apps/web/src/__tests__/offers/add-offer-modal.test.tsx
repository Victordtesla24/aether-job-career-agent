// @vitest-environment jsdom
/**
 * MV-offer-comparison-003 — the Add-Offer modal must cover the full viewport so
 * background Topbar controls are not clickable. The dialog was rendered as a
 * non-first child of a `space-y-6` container, which injected a 24px top margin
 * onto its `fixed inset-0` root. The fix portals the overlay to document.body,
 * so it is a direct child of <body> and resolves against the viewport.
 * MV-offer-comparison-001/006 — submit persists via onAdd with the chosen currency.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddOfferModal } from "../../components/offers/AddOfferModal";

afterEach(cleanup);

describe("AddOfferModal portal + persistence (MV-003 / MV-001 / MV-006)", () => {
  it("portals the overlay to document.body as a direct, full-viewport child", () => {
    const { container } = render(
      <AddOfferModal open onClose={() => {}} onAdd={async () => {}} />,
    );
    // Portaled content is NOT inside the RTL render container...
    expect(container.querySelector('[data-testid="add-offer-modal"]')).toBeNull();
    // ...it is mounted as a direct child of <body>, escaping the space-y flow.
    const modal = screen.getByTestId("add-offer-modal");
    expect(modal.parentElement).toBe(document.body);
    expect(modal.className).toContain("fixed");
    expect(modal.className).toContain("inset-0");
  });

  it("renders nothing when closed", () => {
    render(<AddOfferModal open={false} onClose={() => {}} onAdd={async () => {}} />);
    expect(screen.queryByTestId("add-offer-modal")).toBeNull();
  });

  it("submits the offer (with the chosen currency) through onAdd", async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    render(<AddOfferModal open onClose={() => {}} onAdd={onAdd} />);

    const field = (name: string) => document.body.querySelector(`[name="${name}"]`) as HTMLElement;
    expect(field("currency")).toBeTruthy();

    fireEvent.change(field("company"), { target: { value: "Acme" } });
    fireEvent.change(field("base"), { target: { value: "200000" } });
    fireEvent.change(field("location"), { target: { value: "Sydney" } });
    fireEvent.change(field("currency"), { target: { value: "USD" } });
    fireEvent.click(screen.getByTestId("add-offer-submit"));

    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      company: "Acme",
      base: 200000,
      location: "Sydney",
      currency: "USD",
    });
  });
});
