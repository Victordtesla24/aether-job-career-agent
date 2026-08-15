"use client";

/**
 * The orchestration map's WebGL enhancement layer (S-UI binding constraint 2).
 *
 * WHAT THIS IS: a GPU-rendered pass over the edge network that the SVG layer
 * already draws — glowing curved ribbons, a soft aura behind each node, and a
 * travelling energy packet on the edges that are genuinely carrying work.
 *
 * WHAT THIS IS NOT: a source of truth. Every fact on the map (agent, stage,
 * status, tier, metrics, thresholds, trend) lives in the DOM cards and the
 * semantic lists in `OrchestrationMap.tsx`. This component receives only
 * GEOMETRY plus an already-resolved edge/node state computed by
 * `orchestration-map-model.ts`. It cannot add a node, cannot add an edge, and
 * cannot make anything move that the model did not mark live. Deleting this
 * file would cost the product nothing but polish.
 *
 * DISCIPLINE (all four are load-bearing, not nice-to-haves):
 *   1. Loaded through `next/dynamic({ ssr: false })` from the map only — three
 *      never enters the main bundle or any other route's payload.
 *   2. `prefers-reduced-motion` and "no WebGL" are decided BEFORE this module
 *      is imported (see `useRenderCapabilities`), so a viewer who asked for
 *      stillness never even downloads it.
 *   3. The draw loop stops completely when the tab is hidden, when the map is
 *      scrolled out of view, and — the important one — when nothing is
 *      animating: with no live edge and no live node it renders ONE frame and
 *      parks. An idle system costs an idle GPU.
 *   4. Device pixel ratio is capped at 2.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";

const DPR_CAP = 2;
const PARTICLE_PERIOD_S = 2.2; // matches the SVG fallback's animateMotion dur
const CURVE_SAMPLES = 48;

const COLOR = {
  active: new THREE.Color("#C9A84C"),
  idle: new THREE.Color("#8B8BA3"),
  planned: new THREE.Color("#5A5A6E"),
  // S-UI aesthetics slice: a live node's aura is CORAL, matching the map's own
  // legend ("live run — the only thing that moves" beside a coral dot), the
  // DOM node's live dot and its CSS bloom. It was green, so the GPU layer and
  // the DOM layer disagreed on the colour of the single most important state
  // on the page. Presentation only — nothing decides WHICH nodes are live here.
  live: new THREE.Color("#C9A84C"),
} as const;

export interface GlEdge {
  key: string;
  state: "active" | "idle" | "planned";
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface GlNode {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  live: boolean;
}

/** Soft radial sprite used for node auras and travelling packets. */
function makeGlowTexture(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.35, "rgba(255,255,255,0.55)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

/**
 * Build a tapered ribbon mesh along a cubic bezier.
 *
 * Per-vertex RGBA (three supports a 4-component `color` attribute) gives the
 * ribbon a soft edge without a custom shader: the outer rail is transparent,
 * the centre rail carries the colour, and both ends fade so the curve reads as
 * flowing out of one card and into the next rather than butting against them.
 */
function buildRibbon(
  curve: THREE.CubicBezierCurve,
  halfWidth: number,
  color: THREE.Color,
  peakAlpha: number,
): THREE.Mesh {
  const pts = curve.getPoints(CURVE_SAMPLES);
  const positions: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];

  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const prev = pts[Math.max(0, i - 1)];
    const next = pts[Math.min(pts.length - 1, i + 1)];
    const tx = next.x - prev.x;
    const ty = next.y - prev.y;
    const len = Math.hypot(tx, ty) || 1;
    const nx = -ty / len;
    const ny = tx / len;

    const t = i / (pts.length - 1);
    // Fade the first and last 12% so the ribbon meets the cards softly.
    const endFade = Math.min(1, Math.min(t, 1 - t) / 0.12);

    // outer- / centre / outer+  (3 rails, 2 triangles strips)
    positions.push(p.x - nx * halfWidth, p.y - ny * halfWidth, 0);
    colors.push(color.r, color.g, color.b, 0);
    positions.push(p.x, p.y, 0);
    colors.push(color.r, color.g, color.b, peakAlpha * endFade);
    positions.push(p.x + nx * halfWidth, p.y + ny * halfWidth, 0);
    colors.push(color.r, color.g, color.b, 0);

    if (i < pts.length - 1) {
      const a = i * 3;
      const b = (i + 1) * 3;
      indices.push(a, a + 1, b, a + 1, b + 1, b);
      indices.push(a + 1, a + 2, b + 1, a + 2, b + 2, b + 1);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 4));
  geometry.setIndex(indices);

  const material = new THREE.MeshBasicMaterial({
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
  return new THREE.Mesh(geometry, material);
}

export default function OrchestrationMapGL({
  mapKey,
  width,
  height,
  edges,
  nodes,
}: {
  mapKey: string;
  width: number;
  height: number;
  edges: GlEdge[];
  nodes: GlNode[];
}) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || width <= 0 || height <= 0) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    } catch {
      // Capability was probed before mounting, but a context can still be
      // refused (too many live contexts, driver reset). Staying silent is
      // correct here: the SVG layer underneath already drew the same edges.
      return;
    }

    const disposables: Array<{ dispose: () => void }> = [];
    const scene = new THREE.Scene();
    // CSS-pixel coordinate space with y pointing DOWN, so geometry measured
    // from `getBoundingClientRect()` maps 1:1 with no conversion step (and
    // therefore cannot drift out of alignment with the DOM cards above).
    const camera = new THREE.OrthographicCamera(0, width, 0, height, -100, 100);
    camera.position.z = 10;

    renderer.setPixelRatio(Math.min(typeof window === "undefined" ? 1 : window.devicePixelRatio || 1, DPR_CAP));
    renderer.setSize(width, height, false);
    renderer.setClearAlpha(0);
    const canvas = renderer.domElement;
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    host.appendChild(canvas);

    const glow = makeGlowTexture();
    disposables.push(glow);

    // ---- node auras ------------------------------------------------------
    const auras: Array<{ sprite: THREE.Sprite; live: boolean; base: number }> = [];
    for (const node of nodes) {
      const material = new THREE.SpriteMaterial({
        map: glow,
        color: node.live ? COLOR.live : COLOR.idle,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        // The idle aura is dialled back (0.09 → 0.05): twenty-two additive
        // grey sprites were washing the whole map to a flat mid-grey and
        // flattening exactly the contrast the live node needs to stand out.
        // The live aura gains what the idle ones gave up.
        opacity: node.live ? 0.36 : 0.05,
      });
      disposables.push(material);
      const sprite = new THREE.Sprite(material);
      sprite.position.set(node.x + node.w / 2, node.y + node.h / 2, -1);
      sprite.scale.set(node.w * 1.25, node.h * 1.9, 1);
      scene.add(sprite);
      auras.push({ sprite, live: node.live, base: material.opacity });
    }

    // ---- edge ribbons + travelling packets --------------------------------
    const packets: Array<{ sprite: THREE.Sprite; curve: THREE.CubicBezierCurve; phase: number }> = [];
    edges.forEach((edge, i) => {
      const dx = Math.max(24, (edge.x2 - edge.x1) * 0.5);
      const curve = new THREE.CubicBezierCurve(
        new THREE.Vector2(edge.x1, edge.y1),
        new THREE.Vector2(edge.x1 + dx, edge.y1),
        new THREE.Vector2(edge.x2 - dx, edge.y2),
        new THREE.Vector2(edge.x2, edge.y2),
      );
      const color =
        edge.state === "active" ? COLOR.active : edge.state === "planned" ? COLOR.planned : COLOR.idle;

      // A planned transition gets a dimmer, thinner ribbon — the SVG layer
      // carries the dashes (the honest "roadmap" signal); this only tints.
      const halo = buildRibbon(curve, edge.state === "active" ? 9 : 6, color, edge.state === "active" ? 0.3 : 0.12);
      const core = buildRibbon(curve, edge.state === "planned" ? 1 : 1.6, color, edge.state === "active" ? 0.85 : 0.3);
      for (const mesh of [halo, core]) {
        scene.add(mesh);
        disposables.push(mesh.geometry, mesh.material as THREE.Material);
      }

      // MOTION IS A CLAIM. Only an edge the model marked `active` — meaning
      // its source stage holds a genuinely in-flight, NON-stalled run — gets a
      // packet. Nothing else on this canvas translates.
      if (edge.state === "active") {
        const material = new THREE.SpriteMaterial({
          map: glow,
          color: COLOR.active,
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          opacity: 0.95,
        });
        disposables.push(material);
        const sprite = new THREE.Sprite(material);
        sprite.scale.set(26, 26, 1);
        scene.add(sprite);
        packets.push({ sprite, curve, phase: (i * 0.37) % 1 });
      }
    });

    const animated = packets.length > 0 || auras.some((a) => a.live);

    // ---- draw loop --------------------------------------------------------
    const clock = new THREE.Clock();
    let raf = 0;
    let running = false;
    let visible = true;
    let onScreen = true;

    const draw = () => {
      const t = clock.getElapsedTime();
      for (const p of packets) {
        const u = (t / PARTICLE_PERIOD_S + p.phase) % 1;
        const pt = p.curve.getPointAt(u);
        p.sprite.position.set(pt.x, pt.y, 1);
        // Fade in and out at the ends so a packet never pops into existence.
        (p.sprite.material as THREE.SpriteMaterial).opacity =
          0.95 * Math.min(1, Math.min(u, 1 - u) / 0.12);
      }
      for (const a of auras) {
        if (!a.live) continue;
        (a.sprite.material as THREE.SpriteMaterial).opacity =
          a.base * (0.72 + 0.28 * Math.sin(t * 2.2));
      }
      renderer.render(scene, camera);
    };

    const tick = () => {
      draw();
      raf = requestAnimationFrame(tick);
    };

    const start = () => {
      if (running || !animated || !visible || !onScreen) return;
      running = true;
      clock.getDelta();
      raf = requestAnimationFrame(tick);
    };
    const stop = () => {
      if (!running) return;
      running = false;
      cancelAnimationFrame(raf);
    };

    // Nothing is moving on this map? Render exactly one frame and park. This
    // is the same rule the visuals obey, applied to the power budget.
    draw();
    start();

    const onVisibility = () => {
      visible = !document.hidden;
      if (visible) start();
      else stop();
    };
    document.addEventListener("visibilitychange", onVisibility);

    let io: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      io = new IntersectionObserver(
        (entries) => {
          onScreen = entries.some((e) => e.isIntersecting);
          if (onScreen) start();
          else stop();
        },
        { rootMargin: "120px" },
      );
      io.observe(host);
    }

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      io?.disconnect();
      for (const d of disposables) d.dispose();
      scene.clear();
      renderer.dispose();
      // Release the GPU context immediately — browsers cap simultaneous WebGL
      // contexts and this component remounts on every resize/tab switch.
      renderer.forceContextLoss();
      if (canvas.parentNode === host) host.removeChild(canvas);
    };
  }, [width, height, edges, nodes]);

  return (
    <div
      ref={hostRef}
      data-testid={`orchestration-gl-${mapKey}`}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0"
      style={{ width, height }}
    />
  );
}
