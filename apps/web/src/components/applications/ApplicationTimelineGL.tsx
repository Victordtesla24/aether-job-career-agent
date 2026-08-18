"use client";

/**
 * Application Timeline WebGL enhancement (SESSION TL-VIZ).
 *
 * WHAT THIS IS: soft gilt auras behind timeline nodes + a faint rail glow.
 * WHAT THIS IS NOT: a source of truth. Every title, date and status lives in
 * ApplicationTimeline's DOM. This receives only geometry already derived from
 * timeline-model.ts. Losing this file costs polish only.
 *
 * Discipline mirrors OrchestrationMapGL:
 *   1. Loaded via next/dynamic({ ssr: false })
 *   2. Mounted only when useRenderCapabilities().allowGl is true
 *   3. No travelling packets — motion-as-live-run is Agents-map vocabulary
 *   4. DPR capped at 2; draw loop parks when the tab is hidden
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";

const DPR_CAP = 2;
const GOLD = new THREE.Color("#C9A84C");

export type TimelineGlNode = {
  id: string;
  x: number;
  y: number;
  highlighted: boolean;
};

function makeGlowTexture(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.4, "rgba(255,255,255,0.45)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

export default function ApplicationTimelineGL({
  width,
  height,
  nodes,
}: {
  width: number;
  height: number;
  nodes: TimelineGlNode[];
}) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || width <= 0 || height <= 0) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      return;
    }

    const disposables: Array<{ dispose: () => void }> = [];
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(0, width, 0, height, -100, 100);
    camera.position.z = 10;

    renderer.setPixelRatio(
      Math.min(typeof window === "undefined" ? 1 : window.devicePixelRatio || 1, DPR_CAP),
    );
    renderer.setSize(width, height, false);
    renderer.setClearAlpha(0);
    const canvas = renderer.domElement;
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    canvas.style.pointerEvents = "none";
    canvas.setAttribute("aria-hidden", "true");
    host.appendChild(canvas);

    const glow = makeGlowTexture();
    disposables.push(glow);

    const auras: Array<{ sprite: THREE.Sprite; base: number; highlighted: boolean }> = [];
    for (const node of nodes) {
      const material = new THREE.SpriteMaterial({
        map: glow,
        color: GOLD,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        opacity: node.highlighted ? 0.42 : 0.14,
      });
      disposables.push(material);
      const sprite = new THREE.Sprite(material);
      sprite.position.set(node.x, node.y, 0);
      sprite.scale.set(node.highlighted ? 36 : 22, node.highlighted ? 36 : 22, 1);
      scene.add(sprite);
      auras.push({ sprite, base: material.opacity, highlighted: node.highlighted });
    }

    // Soft horizontal rail — decoration only.
    {
      const geo = new THREE.PlaneGeometry(Math.max(width - 48, 1), 2);
      const mat = new THREE.MeshBasicMaterial({
        color: GOLD,
        transparent: true,
        opacity: 0.06,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      disposables.push(geo, mat);
      const rail = new THREE.Mesh(geo, mat);
      rail.position.set(width / 2, height / 2, -1);
      scene.add(rail);
    }

    let raf = 0;
    let alive = true;
    const draw = (now: number) => {
      if (!alive) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        raf = requestAnimationFrame(draw);
        return;
      }
      const t = now / 1000;
      for (const a of auras) {
        if (!a.highlighted) continue;
        const mat = a.sprite.material as THREE.SpriteMaterial;
        mat.opacity = a.base * (0.85 + 0.15 * Math.sin(t * 1.6));
      }
      renderer.render(scene, camera);
      // Park when nothing is highlighted — one frame is enough.
      if (auras.some((a) => a.highlighted)) {
        raf = requestAnimationFrame(draw);
      }
    };

    renderer.render(scene, camera);
    if (auras.some((a) => a.highlighted)) {
      raf = requestAnimationFrame(draw);
    }

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      for (const d of disposables) d.dispose();
      renderer.dispose();
      if (canvas.parentNode === host) host.removeChild(canvas);
    };
  }, [width, height, nodes]);

  return (
    <div
      ref={hostRef}
      data-testid="timeline-gl"
      className="pointer-events-none absolute inset-0 z-0"
      aria-hidden="true"
    />
  );
}
