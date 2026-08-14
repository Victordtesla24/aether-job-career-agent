// @vitest-environment jsdom
/**
 * D-QDEPTH — QueueStatusBadge honesty contract.
 *
 * Renders ONLY when there is real, actionable backlog to report
 * (`queuedJobs >= 1`). Both an empty queue (`0`) and a Redis outage
 * (`state: "unavailable"` / `queuedJobs: null`) must render nothing —
 * "honest quiet" rather than a permanent chip or a surfaced infra error.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchQueueStatusMock = vi.hoisted(() => vi.fn());
vi.mock("../../../lib/api/queueStatus", () => ({ fetchQueueStatus: fetchQueueStatusMock }));

// eslint-disable-next-line import/first
import { QueueStatusBadge } from "../QueueStatusBadge";

beforeEach(() => {
  fetchQueueStatusMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("QueueStatusBadge", () => {
  it("renders 'N jobs queued' when the queue has 1 or more jobs", async () => {
    fetchQueueStatusMock.mockResolvedValue({ queuedJobs: 5, state: "ok" });
    render(<QueueStatusBadge />);

    const badge = await screen.findByTestId("queue-status-badge");
    expect(badge.textContent).toContain("5 jobs queued");
  });

  it("uses the singular 'job' for exactly 1 queued job", async () => {
    fetchQueueStatusMock.mockResolvedValue({ queuedJobs: 1, state: "ok" });
    render(<QueueStatusBadge />);

    const badge = await screen.findByTestId("queue-status-badge");
    expect(badge.textContent).toContain("1 job queued");
    expect(badge.textContent).not.toContain("1 jobs");
  });

  it("renders nothing when the queue is empty (queuedJobs: 0)", async () => {
    fetchQueueStatusMock.mockResolvedValue({ queuedJobs: 0, state: "ok" });
    const { container } = render(<QueueStatusBadge />);

    await waitFor(() => expect(fetchQueueStatusMock).toHaveBeenCalled());
    expect(screen.queryByTestId("queue-status-badge")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("renders nothing when the server reports 'unavailable' — never surfaces the infra error", async () => {
    fetchQueueStatusMock.mockResolvedValue({ queuedJobs: null, state: "unavailable" });
    const { container } = render(<QueueStatusBadge />);

    await waitFor(() => expect(fetchQueueStatusMock).toHaveBeenCalled());
    expect(screen.queryByTestId("queue-status-badge")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("renders nothing when the fetch itself rejects (network failure)", async () => {
    fetchQueueStatusMock.mockRejectedValue(new Error("network down"));
    const { container } = render(<QueueStatusBadge />);

    await waitFor(() => expect(fetchQueueStatusMock).toHaveBeenCalled());
    expect(screen.queryByTestId("queue-status-badge")).toBeNull();
    expect(container.textContent).toBe("");
  });
});
