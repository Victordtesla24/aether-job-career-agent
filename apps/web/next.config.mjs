/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
      {
        // Root forwards to the dashboard (AuthGuard bounces unauthenticated
        // visitors to /login). A config redirect — not a page-level
        // redirect() — because a statically prerendered redirect() ships a
        // 307 with no Location header, stranding non-JS clients.
        source: "/",
        destination: "/dashboard",
        permanent: false,
      },
      {
        source: "/dashboard/cover-letter",
        destination: "/dashboard/cover-letters",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
