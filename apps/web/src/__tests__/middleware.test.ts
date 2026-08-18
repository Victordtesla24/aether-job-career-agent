import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "../middleware";

function request(path: string, cookie?: string): NextRequest {
  const headers = new Headers();
  if (cookie) headers.set("cookie", `aether_token=${cookie}`);
  return new NextRequest(`https://aether.local${path}`, { headers });
}

describe("admin HTTP gate", () => {
  it("redirects anonymous /admin HTML to login with next= and no-store", () => {
    const res = middleware(request("/admin"));
    expect(res.status).toBeGreaterThanOrEqual(300);
    expect(res.status).toBeLessThan(400);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/login?next=");
    expect(decodeURIComponent(location)).toContain("/admin");
    expect(res.headers.get("cache-control")).toBe("private, no-store");
  });

  it("lets a cookied session through /admin with private no-store", () => {
    const res = middleware(request("/admin/sales-agent", "jwt.token"));
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("private, no-store");
  });

  it("does not gate /admin-login", () => {
    const res = middleware(request("/admin-login"));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });
});
