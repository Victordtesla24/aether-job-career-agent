// @vitest-environment jsdom
/**
 * S-UI-REBUILD §1.6 — the command palette.
 *
 * The load-bearing assertion in this file is the WIRING LAW: the palette
 * reuses `loadSearchIndex()` and `filterSearchHits()` unchanged, on the same
 * lazy-on-first-open trigger, with the same three API calls and the same
 * `href`s. If a future edit gives the palette its own index, its own
 * endpoint, or an eager load, "no new network behaviour" stops being true and
 * these tests fail.
 *
 * It also pins the two rules that keep the palette honest:
 *   - it NAVIGATES ONLY. There is no mutating command, because a "Run agent"
 *     or "Approve" entry would be new behaviour (§1.6 forbids it outright).
 *   - a query with no matches gets a DESIGNED empty state that names the
 *     query, never a blank box (doctrine D-θ).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));

const apiRequestMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/client", () => ({ apiRequest: apiRequestMock }));
const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));

// eslint-disable-next-line import/first
import { CommandPalette } from "../CommandPalette";
// eslint-disable-next-line import/first
import { NAV_ITEMS } from "../../../lib/navigation";

function Harness({ initiallyOpen = true }: { initiallyOpen?: boolean }) {
  return <CommandPalette open={initiallyOpen} onClose={() => undefined} />;
}

beforeEach(() => {
  window.localStorage.clear();
  apiRequestMock.mockImplementation((path: string) => {
    if (path === "/jobs?") {
      return Promise.resolve([
        { id: "j1", title: "Senior Business Analyst", company: "Nearmap" },
        { id: "j2", title: "Delivery Lead", company: "Atlassian" },
      ]);
    }
    return Promise.resolve([{ id: "a1", jobTitle: "Program Manager", company: "Canva" }]);
  });
  fetchAgentsMock.mockResolvedValue([{ name: "Tailoring Agent" }]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Command palette — wiring law (§1.6)", () => {
  it("loads the index lazily on first open, using the SAME three calls the top-bar search made", async () => {
    render(<Harness initiallyOpen={false} />);
    expect(apiRequestMock).not.toHaveBeenCalled();
    expect(fetchAgentsMock).not.toHaveBeenCalled();

    cleanup();
    render(<Harness />);
    await waitFor(() => expect(fetchAgentsMock).toHaveBeenCalledTimes(1));
    expect(apiRequestMock.mock.calls.map((call) => call[0])).toEqual(["/jobs?", "/applications"]);
  });

  it("keeps the >= 2 character rule — a single character matches no jobs/applications/agents", async () => {
    render(<Harness />);
    await waitFor(() => expect(fetchAgentsMock).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "n" } });
    expect(screen.queryByTestId("palette-row-/dashboard/jobs")).toBeNull();
  });

  it("routes to the hit's own unchanged href", async () => {
    render(<Harness />);
    await waitFor(() => expect(fetchAgentsMock).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "nearmap" } });
    const row = await screen.findByTestId("palette-row-/dashboard/jobs");
    fireEvent.mouseDown(within(row).getByRole("button"));
    expect(pushMock).toHaveBeenCalledWith("/dashboard/jobs");
  });
});

describe("Command palette — sections and keyboard (§1.6)", () => {
  it("shows the whole Navigate section with an empty query, and NO mutating command", async () => {
    render(<Harness />);
    const list = await screen.findByRole("listbox");
    const navigate = within(list).getByRole("group", { name: "Navigate" });
    const hrefs = Array.from(
      navigate.querySelectorAll<HTMLElement>("[data-testid^='palette-row-']"),
    ).map((node) => node.getAttribute("data-testid"));
    expect(hrefs).toEqual(NAV_ITEMS.map((item) => `palette-row-${item.href}`));

    // §1.6: navigation and selection only.
    expect(within(list).queryByText(/^run\b/i)).toBeNull();
    expect(within(list).queryByText(/^approve\b/i)).toBeNull();
  });

  it("moves an aria-activedescendant with the arrow keys and opens with Enter", async () => {
    render(<Harness />);
    const input = (await screen.findByRole("combobox")) as HTMLInputElement;
    expect(input.getAttribute("aria-activedescendant")).toBe(`palette-row-nav:${NAV_ITEMS[0]!.href}`);

    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe(`palette-row-nav:${NAV_ITEMS[1]!.href}`);

    fireEvent.keyDown(document, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith(NAV_ITEMS[1]!.href);
  });

  it("draws a designed empty state naming the query, never a blank box", async () => {
    render(<Harness />);
    await waitFor(() => expect(fetchAgentsMock).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "zzzz-nothing-matches-this" },
    });
    const empty = await screen.findByTestId("command-palette-empty");
    expect(empty.textContent).toContain("zzzz-nothing-matches-this");
    expect(empty.textContent).toMatch(/try a company, a role, or an agent name/i);
  });

  it("remembers recent selections client-side only (no request, no server state)", async () => {
    render(<Harness />);
    const list = await screen.findByRole("listbox");
    const row = within(list).getByTestId("palette-row-/dashboard/offers");
    fireEvent.mouseDown(within(row).getByRole("button"));

    const stored = JSON.parse(window.localStorage.getItem("aether.palette.recents") ?? "[]");
    expect(stored[0]?.href).toBe("/dashboard/offers");
    // Selecting a recent must not have talked to the server beyond the one
    // lazy index load.
    expect(apiRequestMock.mock.calls.map((call) => call[0])).toEqual(["/jobs?", "/applications"]);
  });
});
