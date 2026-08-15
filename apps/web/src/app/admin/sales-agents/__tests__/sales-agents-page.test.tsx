// @vitest-environment jsdom
/**
 * ADMIN-2.0 FE-2 (c) — /admin/sales-agents, the reseller management surface.
 *
 * RED-first: the page does not exist in this tree yet.
 *
 * THREE THINGS THIS SCREEN MUST NOT GET WRONG, and which the specs below pin:
 *
 * 1. THERE IS NO DELETE. BE-2 has no delete route by construction — a
 *    distributed referral code lives on in links and in the attribution history
 *    of every account it brought in, so "remove" is `status: "inactive"`. A
 *    Delete button here would promise an erasure the backend will never perform.
 *
 * 2. THE REFERRAL CODE IS NOT GUESSABLE. BE-2 mints codes with `secrets`
 *    precisely because a guessable code is an attribution somebody else can
 *    claim. The client-side suggestion therefore has to be CSPRNG-backed too —
 *    and when no CSPRNG is available it must yield the job to the server rather
 *    than fall back to a weak random.
 *
 * 3. THE COUNTS ARE THE API'S. `attributedSignups` / `convertedPaid` come from
 *    real rows; nothing on this page derives, estimates or rounds them.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../../lib/api/client";

vi.mock("next/link", () => ({
  // `...rest` is passed through so a `data-testid` on a <Link> reaches the DOM
  // the way it does in the real component.
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchSalesAgentsMock = vi.fn();
const createSalesAgentMock = vi.fn();
const updateSalesAgentMock = vi.fn();

vi.mock("../../../../lib/api/adminSalesAgents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api/adminSalesAgents")>();
  return {
    ...actual,
    fetchSalesAgents: (...a: unknown[]) => fetchSalesAgentsMock(...a),
    createSalesAgent: (...a: unknown[]) => createSalesAgentMock(...a),
    updateSalesAgent: (...a: unknown[]) => updateSalesAgentMock(...a),
  };
});

// eslint-disable-next-line import/first
import AdminSalesAgentsPage from "../page";

function agent(overrides: Record<string, unknown> = {}) {
  return {
    id: "agent-1",
    name: "Jane Reseller",
    email: "jane@partner.example",
    referralCode: "JANERES-K7M2QP4X",
    commissionPct: 12.5,
    status: "active",
    notes: null,
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:00:00Z",
    createdBy: "admin-1",
    attributedSignups: 7,
    convertedPaid: 2,
    ...overrides,
  };
}

async function renderPage(agents: unknown[] = [agent()]) {
  fetchSalesAgentsMock.mockResolvedValue({ agents, total: agents.length });
  render(<AdminSalesAgentsPage />);
  await waitFor(() => expect(fetchSalesAgentsMock).toHaveBeenCalled());
}

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the agent list", () => {
  it("shows each agent's real attributed counts, code, commission and status", async () => {
    await renderPage();
    const row = await screen.findByTestId("admin-sales-agent-row-agent-1");
    expect(row.textContent).toContain("Jane Reseller");
    expect(row.textContent).toContain("JANERES-K7M2QP4X");
    expect(within(row).getByTestId("admin-sales-agent-signups-agent-1").textContent).toBe("7");
    expect(within(row).getByTestId("admin-sales-agent-converted-agent-1").textContent).toBe("2");
    expect(row.textContent).toContain("12.5");
    expect(within(row).getByTestId("admin-sales-agent-status-agent-1").textContent).toMatch(
      /active/i,
    );
  });

  it("offers no delete anywhere — deactivation is the only removal", async () => {
    await renderPage();
    await screen.findByTestId("admin-sales-agent-row-agent-1");
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    expect(document.body.textContent).not.toMatch(/delete agent/i);
  });

  it("states honestly that there are no agents yet, rather than showing an empty grid", async () => {
    await renderPage([]);
    const empty = await screen.findByTestId("admin-sales-agents-empty");
    expect(empty.textContent).toMatch(/no sales agents/i);
  });
});

describe("the referral link", () => {
  it("is built from this deployment's own origin and the agent's code", async () => {
    await renderPage();
    const link = await screen.findByTestId("admin-sales-agent-link-agent-1");
    expect(link.textContent).toContain(`${window.location.origin}/signup?ref=JANERES-K7M2QP4X`);
  });

  it("copies the whole link to the clipboard", async () => {
    await renderPage();
    fireEvent.click(await screen.findByTestId("admin-sales-agent-copy-agent-1"));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        `${window.location.origin}/signup?ref=JANERES-K7M2QP4X`,
      ),
    );
  });

  it("marks an inactive agent's link as no longer attributing", async () => {
    await renderPage([agent({ status: "inactive" })]);
    const row = await screen.findByTestId("admin-sales-agent-row-agent-1");
    expect(row.textContent).toMatch(/no longer attribut/i);
  });
});

describe("creating an agent", () => {
  it("suggests an unguessable code from the name, in the backend's own format", async () => {
    await renderPage([]);
    fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Jane Doe" } });
    await waitFor(() => {
      const code = (screen.getByLabelText("Referral code") as HTMLInputElement).value;
      // SLUG-XXXXXXXX, uppercase, from the backend's unambiguous alphabet.
      expect(code).toMatch(/^JANEDOE-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}$/);
    });
  });

  it("sends the typed fields, with the commission as a number", async () => {
    await renderPage([]);
    createSalesAgentMock.mockResolvedValue(agent({ id: "agent-2", name: "Sam Partner" }));
    fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Sam Partner" } });
    fireEvent.change(screen.getByLabelText("Agent email (optional)"), {
      target: { value: "sam@partner.example" },
    });
    fireEvent.change(screen.getByLabelText("Referral code"), { target: { value: "sam-2026" } });
    fireEvent.change(screen.getByLabelText("Commission %"), { target: { value: "15" } });
    fireEvent.click(screen.getByTestId("admin-sales-agent-create"));

    await waitFor(() => expect(createSalesAgentMock).toHaveBeenCalled());
    expect(createSalesAgentMock.mock.calls[0]?.[0]).toMatchObject({
      name: "Sam Partner",
      email: "sam@partner.example",
      // Codes are stored uppercase server-side; sending the canonical form
      // means the admin sees the same string they will hand out.
      referralCode: "SAM-2026",
      commissionPct: 15,
    });
  });

  it("refuses an empty name without calling the API", async () => {
    await renderPage([]);
    fireEvent.click(screen.getByTestId("admin-sales-agent-create"));
    await waitFor(() => expect(screen.getByTestId("admin-sales-agents-error")).toBeTruthy());
    expect(createSalesAgentMock).not.toHaveBeenCalled();
  });

  it("surfaces a duplicate-code 409 in the backend's own words", async () => {
    await renderPage([]);
    createSalesAgentMock.mockRejectedValue(
      new ApiError("Referral code 'SAM-2026' is already in use.", 409),
    );
    fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "Sam Partner" } });
    fireEvent.click(screen.getByTestId("admin-sales-agent-create"));
    await waitFor(() =>
      expect(screen.getByTestId("admin-sales-agents-error").textContent).toContain(
        "already in use",
      ),
    );
  });
});

describe("status toggle IS the delete", () => {
  it("deactivates an active agent through PATCH status=inactive", async () => {
    await renderPage();
    updateSalesAgentMock.mockResolvedValue(agent({ status: "inactive" }));
    fireEvent.click(await screen.findByTestId("admin-sales-agent-toggle-agent-1"));
    await waitFor(() =>
      expect(updateSalesAgentMock).toHaveBeenCalledWith("agent-1", { status: "inactive" }),
    );
  });

  it("reactivates an inactive agent", async () => {
    await renderPage([agent({ status: "inactive" })]);
    updateSalesAgentMock.mockResolvedValue(agent({ status: "active" }));
    fireEvent.click(await screen.findByTestId("admin-sales-agent-toggle-agent-1"));
    await waitFor(() =>
      expect(updateSalesAgentMock).toHaveBeenCalledWith("agent-1", { status: "active" }),
    );
  });

  it("links to the agent's own commission report", async () => {
    await renderPage();
    const row = await screen.findByTestId("admin-sales-agent-row-agent-1");
    expect(within(row).getByRole("link", { name: /report/i }).getAttribute("href")).toBe(
      "/admin/sales-agents/agent-1",
    );
  });
});

/**
 * REFIX ROUND 1. This page carries a cross-link to `/admin/sales-agent`
 * (singular) so neither sales surface is lost. FE-2 described that page as an
 * external, Google-Sheet-driven process with no backend here — true of the
 * placeholder it was written against, false the moment `origin/main@382f0c2`
 * replaced it with the native in-app Sales AI Agent (real Gmail sends behind a
 * shadow/LIVE switch). The cross-link must describe the destination as it is.
 */
describe("the cross-link to the singular sales-agent page", () => {
  it("points at /admin/sales-agent and describes it as the native in-app agent", async () => {
    await renderPage();
    const link = screen.getByTestId("admin-sales-agents-native-link");
    expect(link.getAttribute("href")).toBe("/admin/sales-agent");
    const copy = (link.parentElement?.textContent ?? "").toLowerCase();
    expect(copy).toMatch(/in-app|native/);
    expect(copy).not.toMatch(/external|google sheet|google-sheet|outside this app/);
  });
});
