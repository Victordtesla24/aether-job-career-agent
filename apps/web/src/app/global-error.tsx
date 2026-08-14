"use client";

/**
 * Root-layout error boundary (O-5, S-FIX slice C). Next.js only invokes
 * global-error.tsx when the ROOT layout itself (app/layout.tsx) throws
 * during render — at that point the whole tree, including <html>/<body>, is
 * unmounted, so this file must supply its own. Before this, that failure
 * mode fell through to Next.js's stock, unbranded 500 page with no way back
 * into the app. See app-error-screen.tsx for the shared boundary UI (also
 * used by app/error.tsx for non-layout errors).
 */
import { AppErrorScreen } from "../components/app-error-screen";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <AppErrorScreen error={error} reset={reset} />
      </body>
    </html>
  );
}
