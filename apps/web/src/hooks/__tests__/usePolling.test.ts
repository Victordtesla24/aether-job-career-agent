// @vitest-environment jsdom
/**
 * GOLD-MASTER-V2 §11.2 / W-I item 1 — shared polling hook.
 *
 * §11.2 requires "a shared `usePolling(url, interval)` hook rather than
 * ad-hoc `setInterval` scattered per component". A repo-wide grep
 * (2026-07-31) found FIVE independent, copy-pasted `setInterval` /
 * `window.setInterval` call sites and ZERO shared hook:
 *   - src/components/sidebar.tsx:45           (30s, no visibility pause)
 *   - src/components/topbar.tsx:220           (60s, no visibility pause)
 *   - src/app/dashboard/agents/page.tsx:229    (job-run poll, ref-based)
 *   - src/app/dashboard/applications/page.tsx:452 (20s, visibility-paused)
 *   - src/app/dashboard/jobs/page.tsx:331       (20s, visibility-paused)
 * No `src/hooks/` directory existed before this file.
 *
 * This test imports the canonical hook from its expected location
 * (`../usePolling`, i.e. `apps/web/src/hooks/usePolling.ts`) and pins the
 * minimum contract every ad-hoc call site above already needs by hand:
 *   1. invoke the fetcher once on mount,
 *   2. invoke it again after `intervalMs`,
 *   3. stop invoking it after unmount (no state-update-after-unmount leak),
 *   4. pause while `document.visibilityState !== "visible"` — the
 *      applications/jobs pages already hand-roll this; sidebar/topbar don't,
 *      which is itself part of the "ad-hoc, inconsistent" defect.
 *
 * The hook does not exist yet, so this whole file is expected to fail at
 * module resolution (`Cannot find module '../usePolling'`) — that failure
 * IS the reproduction of the defect (no shared hook exists), not a mistake
 * in the test. A fixer implementing FIX-realtime should make this file's
 * import resolve and every `it()` below pass.
 *
 * The exact parameter name in §11.2 ("url") is taken loosely: every real
 * call site polls via a typed API-client function (`load()`, `tick()`),
 * never a raw fetch URL, so the contract tested here is
 * `usePolling(fetcher, intervalMs, options?)` — a callback, not a string.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// This import is expected to fail to resolve until the hook is built.
import { usePolling } from "../usePolling";

describe("usePolling — canonical shared polling hook (§11.2)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("invokes the fetcher immediately on mount", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 20_000));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("re-invokes the fetcher after the interval elapses, at the requested cadence", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 20_000));
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("stops polling after unmount", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() => usePolling(fetcher, 20_000));
    expect(fetcher).toHaveBeenCalledTimes(1);
    unmount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("pauses while the tab is hidden and resumes on visibilitychange", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });

    renderHook(() => usePolling(fetcher, 20_000));
    const callsAtMount = fetcher.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    // Hidden the whole time — must not have fired any *additional* poll.
    expect(fetcher.mock.calls.length).toBe(callsAtMount);

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher.mock.calls.length).toBeGreaterThan(callsAtMount);
  });
});
