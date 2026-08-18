"use client";

/**
 * Application Timeline WebGL enhancement (SESSION TL-VIZ-R2).
 *
 * WHAT THIS IS: status-coloured auras, ribbon connectors, soft lane rails,
 * and hover bloom. WHAT THIS IS NOT: a source of truth — every title, date
 * and status lives in ApplicationTimeline's DOM. Geometry comes only from
 * timeline-gl-geometry.ts. Losing this file costs polish only.
 *
 * Discipline mirrors OrchestrationMapGL:
 *   1. Loaded via next/dynamic({ ssr: false })
 *   2. Mounted only when useRenderCapabilities().allowGl is true
 *   3. Motion is hover-reactive (or parked) — never invents a live-run claim
 *   4. DPR capped at 2; draw loop parks when the tab is hidden / off-screen
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";

import type {
  TimelineGlEdge,
  TimelineGlNode,
  TimelineGlRail,
} from "./timeline-gl-geometry";

const DPR_CAP = 2;
const CURVE_SAMPLES = 40;
const GOLD = new THREE.Color("#C9A84C");

function makeGlowTexture(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(
      size / 2,
      size / 2,
      0,
      size / 2,
      size / 2,
      size / 2,
    );
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
    const p = pts[i]!;
    const prev = pts[Math.max(0, i - 1)]!;
    const next = pts[Math.min(pts.length - 1, i + 1)]!;
    const tx = next.x - prev.x;
    const ty = next.y - prev.y;
    const len = Math.hypot(tx, ty) || 1;
    const nx = -ty / len;
    const ny = tx / len;
    const t = i / (pts.length - 1);
    const endFade = Math.min(1, Math.min(t, 1 - t) / 0.12);

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
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
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

export type { TimelineGlNode, TimelineGlEdge, TimelineGlRail };

export default function ApplicationTimelineGL({
  width,
  height,
  nodes,
  edges,
  rails,
}: {
  width: number;
  height: number;
  nodes: TimelineGlNode[];
  edges: TimelineGlEdge[];
  rails: TimelineGlRail[];
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  // The WebGL context lives on its own lifecycle (resize only), so a hover —
  // which changes `nodes`/`edges`/`rails` — rebuilds the scene meshes without
  // ever destroying and recreating the GPU context. Recreating it on every
  // mouse enter/leave flickered and exhausted the browser's context cap during
  // scrubbing; the sibling OrchestrationMapGL keeps its context alive the same
  // way and only tears it down for a genuine resize.
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.OrthographicCamera | null>(null);
  const glowRef = useRef<THREE.Texture | null>(null);

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

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(0, width, 0, height, -100, 100);
    camera.position.z = 10;

    renderer.setPixelRatio(
      Math.min(
        typeof window === "undefined" ? 1 : window.devicePixelRatio || 1,
        DPR_CAP,
      ),
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

    rendererRef.current = renderer;
    sceneRef.current = scene;
    cameraRef.current = camera;
    glowRef.current = glow;

    return () => {
      glow.dispose();
      scene.clear();
      renderer.dispose();
      // Release the GPU context immediately — browsers cap simultaneous WebGL
      // contexts and this component remounts on every resize.
      renderer.forceContextLoss();
      if (canvas.parentNode === host) host.removeChild(canvas);
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      glowRef.current = null;
    };
  }, [width, height]);

  useEffect(() => {
    const host = hostRef.current;
    const renderer = rendererRef.current;
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    const glow = glowRef.current;
    if (
      !host ||
      !renderer ||
      !scene ||
      !camera ||
      !glow ||
      width <= 0 ||
      height <= 0
    ) {
      return;
    }

    const disposables: Array<{ dispose: () => void }> = [];
    const objects: THREE.Object3D[] = [];

    {
      const geo = new THREE.PlaneGeometry(
        Math.max(width - 40, 1),
        Math.max(height, 1),
      );
      const mat = new THREE.MeshBasicMaterial({
        color: GOLD,
        transparent: true,
        opacity: 0.018,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      disposables.push(geo, mat);
      const wash = new THREE.Mesh(geo, mat);
      wash.position.set(width / 2, height / 2, -2);
      scene.add(wash);
      objects.push(wash);
    }

    for (const rail of rails) {
      const span = Math.max(rail.x1 - rail.x0, 1);
      const geo = new THREE.PlaneGeometry(span, rail.highlighted ? 3.2 : 1.6);
      const mat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(rail.color),
        transparent: true,
        opacity: rail.highlighted ? 0.16 : 0.05,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      disposables.push(geo, mat);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set((rail.x0 + rail.x1) / 2, rail.y, -1);
      scene.add(mesh);
      objects.push(mesh);
    }

    for (const edge of edges) {
      const dx = Math.max(28, Math.abs(edge.x2 - edge.x1) * 0.45);
      const curve = new THREE.CubicBezierCurve(
        new THREE.Vector2(edge.x1, edge.y1),
        new THREE.Vector2(edge.x1 + dx, edge.y1),
        new THREE.Vector2(edge.x2 - dx, edge.y2),
        new THREE.Vector2(edge.x2, edge.y2),
      );
      const color = new THREE.Color(edge.color);
      const peak = edge.highlighted ? 0.55 : 0.22;
      const halo = buildRibbon(
        curve,
        edge.highlighted ? 10 : 6,
        color,
        peak * 0.45,
      );
      const core = buildRibbon(
        curve,
        edge.highlighted ? 2.2 : 1.4,
        color,
        peak,
      );
      for (const mesh of [halo, core]) {
        scene.add(mesh);
        objects.push(mesh);
        disposables.push(mesh.geometry, mesh.material as THREE.Material);
      }
    }

    const auras: Array<{
      sprite: THREE.Sprite;
      base: number;
      highlighted: boolean;
    }> = [];
    for (const node of nodes) {
      const material = new THREE.SpriteMaterial({
        map: glow,
        color: new THREE.Color(node.color),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        opacity: node.highlighted ? 0.55 : node.genesis ? 0.1 : 0.2,
      });
      disposables.push(material);
      const sprite = new THREE.Sprite(material);
      sprite.position.set(node.x, node.y, 0);
      const scale = node.highlighted ? 48 : node.genesis ? 20 : 28;
      sprite.scale.set(scale, scale, 1);
      scene.add(sprite);
      objects.push(sprite);
      auras.push({
        sprite,
        base: material.opacity,
        highlighted: node.highlighted,
      });

      if (node.highlighted) {
        const ringMat = new THREE.SpriteMaterial({
          map: glow,
          color: GOLD,
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          opacity: 0.28,
        });
        disposables.push(ringMat);
        const ring = new THREE.Sprite(ringMat);
        ring.position.set(node.x, node.y, 1);
        ring.scale.set(64, 64, 1);
        scene.add(ring);
        objects.push(ring);
        auras.push({ sprite: ring, base: 0.28, highlighted: true });
      }
    }

    const animated = auras.some((a) => a.highlighted);
    const timeOriginMs = performance.now();
    let raf = 0;
    let running = false;
    let visible = true;
    let onScreen = true;

    const draw = () => {
      const t = (performance.now() - timeOriginMs) / 1000;
      for (const a of auras) {
        if (!a.highlighted) continue;
        const mat = a.sprite.material as THREE.SpriteMaterial;
        mat.opacity = a.base * (0.78 + 0.22 * Math.sin(t * 2.1));
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
      raf = requestAnimationFrame(tick);
    };
    const stop = () => {
      if (!running) return;
      running = false;
      cancelAnimationFrame(raf);
    };

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
      for (const o of objects) scene.remove(o);
      for (const d of disposables) d.dispose();
    };
  }, [width, height, nodes, edges, rails]);

  return (
    <div
      ref={hostRef}
      data-testid="timeline-gl"
      className="pointer-events-none absolute inset-0 z-0"
      aria-hidden="true"
    />
  );
}
