/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Fonts and Font Awesome are loaded via <link> tags in the root layout rather
  // than next/font so that `next build` never needs network access at build time
  // (keeps CI and offline builds deterministic).
};

export default nextConfig;
