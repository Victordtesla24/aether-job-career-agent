/**
 * W-13 (QA #2, wave-3.5): GET /workspaces/emails/inbox now bounds the list to
 * the most recent threads with `body` truncated to a snippet (was 723KB /
 * ~148 full bodies on every load). `fetchEmailThreadBody` is the detail
 * panel's on-demand fetch for ONE thread's real, full content via
 * `?thread_id=<id>` — this locks in that it hits the right endpoint/param and
 * degrades honestly (null) when the thread isn't found, rather than throwing
 * or silently returning a truncated snippet.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchEmailThreadBody } from "../../lib/api/workspaces";

function mockFetchOnce(body: unknown, status = 200) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  return vi.fn().mockResolvedValue(response);
}

describe("fetchEmailThreadBody (W-13 detail-panel full-body fetch)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls /workspaces/emails/inbox with the thread_id query param", async () => {
    const fetchMock = mockFetchOnce({ messages: [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchEmailThreadBody("thread-abc-123", { token: "test-token" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/workspaces/emails/inbox?thread_id=thread-abc-123");
  });

  it("URL-encodes the thread id", async () => {
    const fetchMock = mockFetchOnce({ messages: [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchEmailThreadBody("thread with spaces", { token: "test-token" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("thread_id=thread%20with%20spaces");
  });

  it("returns the real, full body for the matching thread", async () => {
    const fullBody = "Recruiter message. ".repeat(30);
    vi.stubGlobal(
      "fetch",
      mockFetchOnce({
        messages: [{ id: "thread-abc-123", body: fullBody }],
      }),
    );

    const body = await fetchEmailThreadBody("thread-abc-123", { token: "test-token" });
    expect(body).toBe(fullBody);
  });

  it("returns null (honest empty state) when the thread isn't in the response", async () => {
    vi.stubGlobal("fetch", mockFetchOnce({ messages: [] }));

    const body = await fetchEmailThreadBody("missing-thread", { token: "test-token" });
    expect(body).toBeNull();
  });
});
