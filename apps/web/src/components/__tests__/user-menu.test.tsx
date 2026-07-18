// @vitest-environment jsdom
/**
 * UserMenu — the topbar account menu that finally gives the app a visible
 * Sign out control (MV-login-003). RED first: components/user-menu.tsx does
 * not exist yet.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: replaceMock }) }));

// eslint-disable-next-line import/first
import { UserMenu } from "../user-menu";

afterEach(() => {
  cleanup();
  replaceMock.mockReset();
  window.localStorage.clear();
});

describe("UserMenu (MV-login-003 logout)", () => {
  it("keeps the menu closed until the chip is clicked", () => {
    render(<UserMenu initials="VS" name="Vikram S." role="TPM" />);
    expect(screen.queryByRole("menuitem", { name: /sign out/i })).toBeNull();
  });

  it("exposes a Sign out control that clears the session and returns to /login", () => {
    window.localStorage.setItem("aether_token", "jwt-123");
    render(<UserMenu initials="VS" name="Vikram S." role="TPM" />);

    fireEvent.click(screen.getByRole("button", { name: /account menu/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /sign out/i }));

    expect(window.localStorage.getItem("aether_token")).toBeNull();
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  // MV-mobile-dashboard-001 / MV-mobile-dashboard-004: this desktop
  // account-identity chip (name + role text) has no responsive hide class,
  // so it renders in full at a 390px mobile viewport, crowding the topbar and
  // directly contributing to the header greeting/subtitle clipping bug. The
  // avatar (and its click target for the account menu) must stay reachable
  // at every width — only the redundant name/role TEXT should hide below the
  // `lg` breakpoint the rest of this shell already treats as the desktop
  // cutover (see the search box's `max-lg:hidden` in topbar.tsx).
  it("hides the name/role text below the lg breakpoint so it can't crowd the mobile header", () => {
    render(<UserMenu initials="VS" name="Vikram S." role="TPM" />);
    const nameNode = screen.getByText("Vikram S.");
    const textWrapper = nameNode.parentElement as HTMLElement;
    expect(textWrapper.className).toMatch(/\bmax-lg:hidden\b/);
  });

  it("keeps the avatar + account-menu button reachable regardless of the text hide", () => {
    render(<UserMenu initials="VS" name="Vikram S." role="TPM" />);
    const btn = screen.getByRole("button", { name: /account menu/i });
    expect(btn.className).not.toMatch(/hidden/);
    expect(screen.getByText("VS")).toBeTruthy();
  });
});
