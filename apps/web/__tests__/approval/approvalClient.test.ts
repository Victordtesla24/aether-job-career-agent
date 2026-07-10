import { describe, it, expect, vi } from "vitest";
import {
  ApprovalClient,
  isApprovable,
  createSubmitFn,
  type AgentStatusResponse,
} from "../../src/components/approval/approvalClient.js";

function jsonResponse(body: unknown, init: Partial<{ ok: boolean; status: number; statusText: string }> = {}) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    json: async () => body,
  } as unknown as Response;
}

describe("ApprovalClient.submitDecision", () => {
  it("POSTs to /api/agents/approve/:taskId with auth + body", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}));
    const client = new ApprovalClient({
      baseUrl: "https://api.test",
      fetchImpl: fetchImpl as unknown as typeof fetch,
      getToken: () => "jwt-123",
    });
    await client.submitDecision({ taskId: "t 1", decision: "approve", trustAgent: true });
    const [url, opts] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.test/api/agents/approve/t%201");
    expect(opts.method).toBe("POST");
    expect((opts.headers as Record<string, string>).Authorization).toBe("Bearer jwt-123");
    expect(JSON.parse(opts.body as string)).toEqual({ decision: "approve", trustAgent: true });
  });

  it("throws a descriptive error on non-2xx", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({}, { ok: false, status: 403, statusText: "Forbidden" }),
    );
    const client = new ApprovalClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(
      client.submitDecision({ taskId: "t1", decision: "reject", trustAgent: false }),
    ).rejects.toThrow(/reject failed \(403 Forbidden\)/);
  });

  it("omits Authorization when no token", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}));
    const client = new ApprovalClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await client.submitDecision({ taskId: "t1", decision: "edit", trustAgent: false });
    const [, opts] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect((opts.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});

describe("ApprovalClient.fetchStatus", () => {
  it("GETs status and returns parsed body", async () => {
    const body: AgentStatusResponse = {
      taskId: "t1",
      status: "WAITING_APPROVAL",
      progress: 60,
      checkpoint: { message: "Approve to submit", approvalRequired: true },
    };
    const fetchImpl = vi.fn(async () => jsonResponse(body));
    const client = new ApprovalClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    const res = await client.fetchStatus("t1");
    expect(res).toEqual(body);
    const [url, opts] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/agents/status/t1");
    expect(opts.method).toBe("GET");
  });

  it("throws on non-2xx", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({}, { ok: false, status: 404, statusText: "Not Found" }),
    );
    const client = new ApprovalClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchStatus("nope")).rejects.toThrow(/404 Not Found/);
  });
});

describe("isApprovable guard", () => {
  it("true only at WAITING_APPROVAL with approvalRequired", () => {
    expect(
      isApprovable({ taskId: "t", status: "WAITING_APPROVAL", progress: 50, checkpoint: { message: "", approvalRequired: true } }),
    ).toBe(true);
  });
  it("false for other statuses or when not required (guards fixture-as-live)", () => {
    expect(isApprovable({ taskId: "t", status: "COMPLETE", progress: 100 })).toBe(false);
    expect(
      isApprovable({ taskId: "t", status: "WAITING_APPROVAL", progress: 50, checkpoint: { message: "", approvalRequired: false } }),
    ).toBe(false);
  });
});

describe("createSubmitFn", () => {
  it("delegates to client.submitDecision", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}));
    const client = new ApprovalClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    const submit = createSubmitFn(client);
    await submit({ taskId: "t1", decision: "approve", trustAgent: false });
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});
