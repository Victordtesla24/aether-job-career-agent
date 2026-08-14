"use client";

/**
 * S-UI binding constraint 2 — the two facts that decide whether a WebGL
 * rendition may run at all:
 *
 *   1. `prefers-reduced-motion: reduce` — the viewer has asked the platform
 *      for less motion. A GPU particle field is exactly what they asked to be
 *      spared, so we render the static DOM/SVG equivalent instead.
 *   2. WebGL availability — a browser/driver with no usable context (or a
 *      hardened profile that blocks it) must still get the full map.
 *
 * Both resolve to `false` during SSR and on the very first client paint, so
 * the STATIC map is always what renders first and what a crawler, a
 * screen-reader-only pass, or a failed hydration sees. The enhanced layer is
 * strictly additive — it never becomes the only carrier of any fact.
 */
import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

/** Feature-detects a usable WebGL context WITHOUT leaking the probe canvas. */
export function detectWebgl(): boolean {
  if (typeof document === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2") ??
      canvas.getContext("webgl") ??
      canvas.getContext("experimental-webgl");
    if (!gl) return false;
    // Free the context immediately — browsers cap simultaneous WebGL contexts
    // (typically 8-16) and a leaked probe would count against the real one.
    const lose = (gl as WebGLRenderingContext).getExtension?.("WEBGL_lose_context");
    lose?.loseContext();
    return true;
  } catch {
    return false;
  }
}

export interface RenderCapabilities {
  /** The viewer asked for reduced motion. */
  reducedMotion: boolean;
  /** A WebGL context could be created in this browser. */
  webgl: boolean;
  /** Both checks passed AND we are past first paint — safe to mount the GL layer. */
  allowGl: boolean;
}

export function useRenderCapabilities(): RenderCapabilities {
  // `false`/`false` on the server AND on the first client render so hydration
  // is deterministic; the effect below upgrades on the client only.
  const [reducedMotion, setReducedMotion] = useState(false);
  const [webgl, setWebgl] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setWebgl(detectWebgl());
    setReady(true);

    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(QUERY);
    setReducedMotion(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    // Safari < 14 only has the deprecated addListener/removeListener pair.
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, []);

  return { reducedMotion, webgl, allowGl: ready && webgl && !reducedMotion };
}
