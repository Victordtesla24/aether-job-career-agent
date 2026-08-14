// @vitest-environment jsdom
/**
 * S-UI-REBUILD §2.5 / doctrine D-κ — the shell survives reduced motion.
 *
 * The spec's acceptance test is: *"run the sweep twice, once with
 * `reducedMotion: 'reduce'`. Both runs must assert the same visible text."*
 * That is exactly what this file does at unit level for the shell frame,
 * because the frame is on screen 100% of the time and is where a
 * motion-carried meaning would do the most damage.
 *
 * The other half of the contract is structural: `MotionConfig
 * reducedMotion="user"` must sit at the SHELL ROOT (not only inside
 * `template.tsx`), so it covers the rail, the command bar, the tab bar and
 * the sheet as well as the routed page. Framer then drops transform/position
 * animation and keeps opacity, automatically, for every `motion` element in
 * the tree — which is why no individual shell component hand-rolls a
 * reduced-motion branch for its transitions.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}));

const fetchSettingsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/workspaces", () => ({ fetchSettings: fetchSettingsMock }));
const fetchAgentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/agents", () => ({ fetchAgents: fetchAgentsMock }));
const fetchApprovalsMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/approvals", () => ({ fetchApprovals: fetchApprovalsMock }));
const fetchSubscriptionMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/billing", () => ({ fetchSubscription: fetchSubscriptionMock }));
const fetchMeMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/admin", () => ({ fetchMe: fetchMeMock }));

// eslint-disable-next-line import/first
import { AppShell } from "../AppShell";

/** jsdom ships no `matchMedia`; the OS preference is simulated here. */
function setPrefersReducedMotion(reduce: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? reduce : false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

async function renderShellText(): Promise<string> {
  const { container } = render(
    <AppShell supportEmail="help@example-operator.com">
      <p>Routed page content</p>
    </AppShell>,
  );
  await waitFor(() => expect(fetchSettingsMock).toHaveBeenCalled());
  await screen.findByText("Good", { exact: false }).catch(() => null);
  await waitFor(() => expect(screen.getByTestId("app-rail")).toBeTruthy());
  return (container.textContent ?? "").replace(/\s+/g, " ").trim();
}

beforeEach(() => {
  fetchSettingsMock.mockResolvedValue({ profile: { fullName: "Vikram Sarkar", targetRole: "" } });
  fetchAgentsMock.mockResolvedValue([]);
  fetchApprovalsMock.mockResolvedValue([]);
  fetchSubscriptionMock.mockResolvedValue(null);
  fetchMeMock.mockResolvedValue({ id: "u1", email: "u@example.com", isAdmin: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Shell under prefers-reduced-motion (D-κ)", () => {
  it("communicates exactly the same facts, in the same words, with motion reduced", async () => {
    setPrefersReducedMotion(false);
    const normal = await renderShellText();
    cleanup();

    setPrefersReducedMotion(true);
    const reduced = await renderShellText();

    expect(reduced).toBe(normal);
    // Sanity: the shell really did render something worth comparing.
    expect(normal).toContain("Aether");
    expect(normal).toContain("Routed page content");
  });

  it("still reaches every mobile section with motion reduced", async () => {
    setPrefersReducedMotion(true);
    render(
      <AppShell supportEmail={null}>
        <p>page</p>
      </AppShell>,
    );
    fireEvent.click(screen.getByTestId("mobile-nav-trigger"));
    const sheet = await screen.findByTestId("mobile-nav-sheet");
    expect(sheet.querySelectorAll("[data-testid^='mobile-nav-link-']").length).toBe(13);
  });
});
