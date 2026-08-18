"use client";

import dynamic from "next/dynamic";
/**
 * Application Timeline — horizontal swimlanes (SESSION TL-VIZ / TL-VIZ-R2).
 *
 * Accessible DOM/SVG is the product. Framer Motion dresses the entrance.
 * An optional Three.js overlay (ApplicationTimelineGL) paints ribbons, rails
 * and status-coloured auras only — it never carries a fact this component
 * does not already render.
 */
import { motion, useReducedMotion } from "framer-motion";
import { useRenderCapabilities } from "../../hooks/useRenderCapabilities";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  buildTimelineModel,
  STATUS_NODE_COLOR,
  type TimelinePayload,
} from "./timeline-model";
import { buildTimelineGlGeometry } from "./timeline-gl-geometry";
import type { FilterKey, SortKey } from "./tracker-lib";

const ApplicationTimelineGL = dynamic(() => import("./ApplicationTimelineGL"), {
  ssr: false,
  loading: () => null,
});

const LANE_H = 80;
const LABEL_W = 220;
const PAD_X = 28;
const VIEWPORT_H = "min(calc(100dvh - 300px), 1120px)";

const LEGEND: Array<{ key: keyof typeof STATUS_NODE_COLOR; label: string }> = [
  { key: "draft", label: "Ready" },
  { key: "submitted", label: "Submitted" },
  { key: "screening", label: "In review" },
  { key: "interview", label: "Interview" },
  { key: "offer", label: "Offer" },
  { key: "rejected", label: "Rejected" },
  { key: "withdrawn", label: "Withdrawn" },
];

export default function ApplicationTimeline({
  payload,
  error = null,
  onRetry,
  onOpenDetail,
  filter = "all",
  sort = "recent",
  pendingApprovalIds,
}: {
  payload: TimelinePayload | null;
  error?: string | null;
  onRetry?: () => void;
  onOpenDetail: (applicationId: string) => void;
  filter?: FilterKey;
  sort?: SortKey;
  pendingApprovalIds?: ReadonlySet<string>;
}) {
  const reduceMotion = useReducedMotion();
  const { allowGl } = useRenderCapabilities();
  const [glSize, setGlSize] = useState({ w: 0, h: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [hoverAppId, setHoverAppId] = useState<string | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [panX, setPanX] = useState(0);
  const velocityRef = useRef(0);
  const lastMoveRef = useRef<{ x: number; t: number } | null>(null);
  const inertiaRaf = useRef(0);
  const dragRef = useRef<{ active: boolean; startX: number; origin: number }>({
    active: false,
    startX: 0,
    origin: 0,
  });

  const model = useMemo(() => {
    if (!payload) {
      return buildTimelineModel(
        { items: [], range: { start: null, end: null } },
        { filter, sort, pendingApprovalIds },
      );
    }
    return buildTimelineModel(payload, { filter, sort, pendingApprovalIds });
  }, [payload, filter, sort, pendingApprovalIds]);

  useEffect(() => {
    const el = trackRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (!cr) return;
      setGlSize({ w: Math.round(cr.width), h: Math.round(cr.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [model.lanes.length, model.empty]);

  const glGeo = useMemo(
    () =>
      buildTimelineGlGeometry(model, {
        width: glSize.w,
        labelW: LABEL_W,
        padX: PAD_X,
        laneH: LANE_H,
        hoverId,
        hoverAppId,
      }),
    [model, glSize.w, hoverId, hoverAppId],
  );

  const focusNode = useMemo(() => {
    if (!hoverId) return null;
    for (const lane of model.lanes) {
      const node = lane.nodes.find((n) => n.id === hoverId);
      if (node) return { lane, node };
    }
    return null;
  }, [hoverId, model.lanes]);

  const stopInertia = useCallback(() => {
    if (inertiaRaf.current) {
      cancelAnimationFrame(inertiaRaf.current);
      inertiaRaf.current = 0;
    }
  }, []);

  const startInertia = useCallback(() => {
    stopInertia();
    if (reduceMotion || Math.abs(velocityRef.current) < 0.4) return;
    const step = () => {
      velocityRef.current *= 0.92;
      if (Math.abs(velocityRef.current) < 0.35) {
        velocityRef.current = 0;
        inertiaRaf.current = 0;
        return;
      }
      setPanX((x) => x + velocityRef.current);
      inertiaRaf.current = requestAnimationFrame(step);
    };
    inertiaRaf.current = requestAnimationFrame(step);
  }, [reduceMotion, stopInertia]);

  useEffect(() => () => stopInertia(), [stopInertia]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      stopInertia();
      velocityRef.current = 0;
      lastMoveRef.current = { x: e.clientX, t: performance.now() };
      dragRef.current = { active: true, startX: e.clientX, origin: panX };
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    },
    [panX, stopInertia],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current.active) return;
    const now = performance.now();
    const prev = lastMoveRef.current;
    if (prev) {
      const dt = Math.max(now - prev.t, 1);
      velocityRef.current = ((e.clientX - prev.x) / dt) * 16;
    }
    lastMoveRef.current = { x: e.clientX, t: now };
    const dx = e.clientX - dragRef.current.startX;
    setPanX(dragRef.current.origin + dx);
  }, []);

  const onPointerUp = useCallback(() => {
    dragRef.current.active = false;
    startInertia();
  }, [startInertia]);

  const onKeyDownScroller = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      setPanX((x) => x + 64);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      setPanX((x) => x - 64);
    } else if (e.key === "Home") {
      e.preventDefault();
      setPanX(0);
    }
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    if (!e.shiftKey) return;
    e.preventDefault();
    setPanX((x) => x - e.deltaY);
  }, []);

  return (
    <section
      className="elev-1 relative overflow-hidden rounded-[14px] border border-white/[0.06]"
      data-testid="timeline-view"
      style={{ maxHeight: VIEWPORT_H }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] px-5 py-3">
        <div className="min-w-0">
          <h2 className="type-card-title text-[13px] tracking-[0.06em] text-[color:var(--fg-1,#F5F1E8)]">
            Timeline
          </h2>
          {!model.empty ? (
            <p className="mt-0.5 text-[11px] text-aether-muted-dim">
              {model.lanes.length} application
              {model.lanes.length === 1 ? "" : "s"} · drag or Shift+scroll to pan
            </p>
          ) : null}
        </div>
        {!model.empty && model.range.start && model.range.end ? (
          <p className="mono text-[10px] text-aether-muted-dim">
            {new Date(model.range.start).toLocaleDateString("en-AU", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
            {" — "}
            {new Date(model.range.end).toLocaleDateString("en-AU", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </p>
        ) : null}
      </div>

      {!error && !model.empty ? (
        <div
          className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-white/[0.04] px-5 py-2"
          data-testid="timeline-legend"
          aria-hidden="true"
        >
          {LEGEND.map((item) => (
            <span
              key={item.key}
              className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.06em] text-aether-muted-dim"
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: STATUS_NODE_COLOR[item.key] }}
              />
              {item.label}
            </span>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="space-y-3 px-5 py-8">
          <p className="text-sm text-aether-muted">{error}</p>
          {onRetry ? (
            <button
              type="button"
              data-testid="timeline-retry"
              onClick={onRetry}
              className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[12px] font-semibold text-gold transition hover:bg-gold/15"
            >
              Retry
            </button>
          ) : null}
        </div>
      ) : model.empty ? (
        <div className="relative overflow-hidden px-5 py-20">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-8 top-1/2 h-px -translate-y-1/2 bg-gradient-to-r from-transparent via-gold/30 to-transparent"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute left-1/2 top-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gold/[0.06] blur-2xl"
          />
          <div className="relative mx-auto max-w-md text-center">
            <p className="text-sm text-aether-muted">No applications yet.</p>
            <p className="mt-2 text-[12px] text-aether-muted-dim">
              Status transitions will appear here as horizontal swimlanes once
              you add roles to the pipeline.
            </p>
          </div>
        </div>
      ) : (
        <div
          ref={scrollerRef}
          role="region"
          aria-label="Application status timeline"
          tabIndex={0}
          onKeyDown={onKeyDownScroller}
          onWheel={onWheel}
          className="relative outline-none focus-visible:ring-1 focus-visible:ring-gold/40"
          style={{ maxHeight: VIEWPORT_H }}
        >
          <div
            className="sticky top-0 z-10 flex border-b border-white/[0.05] bg-[#0F0F12]/95 backdrop-blur-sm"
            style={{ paddingLeft: LABEL_W + PAD_X, paddingRight: PAD_X }}
          >
            <div className="relative h-9 w-full">
              {model.axisTicks.map((t) => (
                <span
                  key={t.at}
                  className="mono absolute top-2 -translate-x-1/2 text-[10px] tabular-nums text-aether-muted-dim"
                  style={{ left: `${t.x * 100}%` }}
                >
                  {t.label}
                </span>
              ))}
            </div>
          </div>

          <div
            ref={trackRef}
            className="relative cursor-grab active:cursor-grabbing"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            style={{
              transform: `translateX(${panX}px)`,
              minHeight: Math.min(model.lanes.length, 40) * LANE_H + 24,
            }}
          >
            {allowGl ? (
              <ApplicationTimelineGL
                width={Math.max(glSize.w, 1)}
                height={Math.max(glSize.h, model.lanes.length * LANE_H, 1)}
                nodes={glGeo.nodes}
                edges={glGeo.edges}
                rails={glGeo.rails}
              />
            ) : null}
            {model.lanes.map((lane, i) => {
              const laneHot =
                hoverAppId === lane.applicationId ||
                lane.nodes.some((n) => n.id === hoverId);
              return (
                <motion.div
                  key={lane.applicationId}
                  data-testid={`timeline-lane-${lane.applicationId}`}
                  className="relative flex items-stretch border-b border-white/[0.04]"
                  style={{
                    height: LANE_H,
                    background: laneHot
                      ? "linear-gradient(90deg, rgba(201,168,76,0.06), transparent 42%)"
                      : undefined,
                  }}
                  initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: reduceMotion ? 0 : 0.35,
                    delay: reduceMotion ? 0 : Math.min(i, 12) * 0.03,
                    ease: [0.25, 1, 0.5, 1],
                  }}
                >
                  <div
                    className="sticky left-0 z-[1] flex shrink-0 flex-col justify-center border-r border-white/[0.06] bg-[#0F0F12]/92 px-4 backdrop-blur-sm"
                    style={{ width: LABEL_W }}
                  >
                    <p className="truncate text-[12px] font-semibold text-[color:var(--fg-1,#F5F1E8)]">
                      {lane.jobTitle}
                    </p>
                    <p className="truncate text-[11px] text-aether-muted-dim">
                      {lane.company}
                    </p>
                    {typeof lane.application.fitScore === "number" ? (
                      <p className="mono mt-0.5 text-[10px] text-aether-muted-dim">
                        Fit {Math.round(lane.application.fitScore)}
                      </p>
                    ) : null}
                  </div>

                  <div className="relative flex-1" style={{ minWidth: 560 }}>
                    <div
                      aria-hidden="true"
                      className="absolute left-7 right-7 top-1/2 h-px -translate-y-1/2 bg-white/[0.08]"
                    />
                    <svg
                      className="pointer-events-none absolute inset-0 h-full w-full"
                      aria-hidden="true"
                    >
                      {lane.nodes.slice(0, -1).map((n, idx) => {
                        const next = lane.nodes[idx + 1]!;
                        const y = LANE_H / 2;
                        return (
                          <line
                            key={`${n.id}-c`}
                            x1={`${n.x * 100}%`}
                            y1={y}
                            x2={`${next.x * 100}%`}
                            y2={y}
                            stroke={
                              laneHot
                                ? "rgba(201,168,76,0.45)"
                                : "rgba(201,168,76,0.22)"
                            }
                            strokeWidth={laneHot ? 2 : 1.5}
                            strokeLinecap="round"
                          />
                        );
                      })}
                    </svg>

                    {lane.nodes.map((node) => {
                      const hot = hoverId === node.id;
                      return (
                        <button
                          key={node.id}
                          type="button"
                          data-testid={`timeline-node-${node.id}`}
                          aria-label={`${node.label} — ${lane.jobTitle} at ${lane.company}, ${new Date(node.at).toLocaleString("en-AU")}${node.note ? `. ${node.note}` : ""}`}
                          title={
                            node.note
                              ? `${node.label} · ${node.note}`
                              : `${node.label} · ${new Date(node.at).toLocaleDateString("en-AU")}`
                          }
                          onClick={() => onOpenDetail(lane.applicationId)}
                          onMouseEnter={() => {
                            setHoverId(node.id);
                            setHoverAppId(lane.applicationId);
                          }}
                          onMouseLeave={() => {
                            setHoverId(null);
                            setHoverAppId(null);
                          }}
                          onFocus={() => {
                            setHoverId(node.id);
                            setHoverAppId(lane.applicationId);
                          }}
                          onBlur={() => {
                            setHoverId(null);
                            setHoverAppId(null);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onOpenDetail(lane.applicationId);
                            }
                          }}
                          className="group absolute top-1/2 z-[2] flex -translate-x-1/2 -translate-y-1/2 flex-col items-center outline-none"
                          style={{
                            left: `calc(${PAD_X}px + (100% - ${PAD_X * 2}px) * ${node.x})`,
                          }}
                        >
                          <span
                            className="rounded-full border-2 border-[#0F0F12] transition group-hover:scale-125 group-focus-visible:scale-125 group-focus-visible:ring-2 group-focus-visible:ring-gold/50"
                            style={{
                              width: hot ? 16 : 14,
                              height: hot ? 16 : 14,
                              backgroundColor: node.color,
                              boxShadow: hot
                                ? `0 0 18px ${node.color}99`
                                : "0 0 12px rgba(201,168,76,0.28)",
                            }}
                          />
                          <span
                            className={`mt-1 max-w-[110px] truncate text-center text-[9px] font-medium uppercase tracking-[0.08em] transition ${
                              hot
                                ? "text-[color:var(--fg-2)] opacity-100"
                                : "text-aether-muted-dim opacity-70 group-hover:opacity-100 group-focus-visible:opacity-100"
                            }`}
                          >
                            {node.label}
                          </span>
                          {node.genesis ? (
                            <span className="sr-only">{node.note}</span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </motion.div>
              );
            })}
          </div>

          {focusNode ? (
            <div
              data-testid="timeline-focus"
              className="pointer-events-none absolute bottom-3 right-4 z-[3] max-w-xs rounded-lg border border-gold/25 bg-[#16161A]/95 px-3.5 py-2.5 shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur-md"
            >
              <p className="text-[11px] font-semibold text-[color:var(--fg-1,#F5F1E8)]">
                {focusNode.lane.jobTitle}
              </p>
              <p className="text-[10px] text-aether-muted-dim">
                {focusNode.lane.company}
              </p>
              <p className="mt-1.5 text-[11px] text-[color:var(--fg-2)]">
                <span
                  className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle"
                  style={{ backgroundColor: focusNode.node.color }}
                />
                {focusNode.node.label}
                {" · "}
                {new Date(focusNode.node.at).toLocaleString("en-AU", {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
              {focusNode.node.note ? (
                <p className="mt-1 text-[10px] text-aether-muted-dim">
                  {focusNode.node.note}
                </p>
              ) : null}
            </div>
          ) : null}

          {model.lanes.some((l) => l.nodes.some((n) => n.genesis)) ? (
            <p className="border-t border-white/[0.05] px-5 py-2.5 text-[11px] text-aether-muted-dim">
              Earlier transitions were not observed.
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
