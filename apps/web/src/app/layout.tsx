import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aether Career Agent",
  description:
    "Aether Career Agent autonomously discovers roles, tailors your resume, and manages applications end to end.",
};

/**
 * Root layout. Inter / JetBrains Mono and Font Awesome are pulled in via <link>
 * tags (not next/font) so builds never require network access — this keeps CI
 * and offline builds deterministic.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
        <link
          rel="stylesheet"
          href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
