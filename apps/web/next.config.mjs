/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow an alternate build output directory so an e2e "companion" build
  // (baked with AETHER_API_PROXY pointing at an isolated test API) can coexist
  // with the production `.next` build in the same working tree. Must be set at
  // BOTH build time and start time (`next start` reads the same env).
  distDir: process.env.AETHER_WEB_DIST_DIR ?? ".next",
  // Fonts and Font Awesome are loaded via <link> tags in the root layout rather
  // than next/font so that `next build` never needs network access at build time
  // (keeps CI and offline builds deterministic).

  // Mirror the production nginx rule (`location /api/ → FastAPI :8000`) so a
  // standalone `next start` (dev, Playwright e2e) serves the same-origin
  // `/api` contract the browser client relies on.
  async rewrites() {
    const apiOrigin = process.env.AETHER_API_PROXY ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${apiOrigin}/:path*` }];
  },

  // The wireframe spec addresses the screen as /dashboard/cover-letter; the
  // workspace lives at the plural route (SC-CL-01).
  async redirects() {
    return [
      // NOTE: the root path `/` is intentionally NOT redirected here anymore.
      // Auth state lives in localStorage (invisible to the server), so a
      // static config/middleware redirect cannot tell an authenticated user
      // from an anonymous one. The root client page (`src/app/page.tsx`) reads
      // the session once and routes in a SINGLE hop — authenticated →
      // /dashboard, anonymous → /pricing — instead of the previous two-hop
      // `/` → /dashboard → (client) /pricing bounce for logged-out visitors.
      {
        source: "/dashboard/cover-letter",
        destination: "/dashboard/cover-letters",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
