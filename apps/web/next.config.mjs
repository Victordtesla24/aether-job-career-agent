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
};

export default nextConfig;
