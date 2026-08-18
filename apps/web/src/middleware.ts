import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "aether_token";

/**
 * HTTP gate for /admin/* (not /admin-login). Anonymous HTML was previously a
 * 200 cached shell; the real data gate remains AdminUser on the API.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname === "/admin-login" || pathname.startsWith("/admin-login/")) {
    return NextResponse.next();
  }
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.search = `?next=${encodeURIComponent(pathname + request.nextUrl.search)}`;
    const redirect = NextResponse.redirect(login);
    redirect.headers.set("Cache-Control", "private, no-store");
    return redirect;
  }
  const response = NextResponse.next();
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = {
  matcher: ["/admin", "/admin/:path*"],
};
