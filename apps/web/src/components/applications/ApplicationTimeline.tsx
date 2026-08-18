"use client";

/**
 * Application Timeline — horizontal swimlanes (SESSION TL-VIZ).
 *
 * Accessible DOM/SVG is the product. Framer Motion dresses the entrance.
 * An optional Three.js overlay (ApplicationTimelineGL) may paint glow only —
 * it never carries a fact this component does not already render.
 */
import { motion, useReducedMotion } from "framer-motion";
import { useCallback, useMemo, useRef, useState } from "react";

import {
  buildTimelineModel,
  type TimelinePayload,
} from "./timeline-model";
import type { FilterKey, SortKey } from "./tracker-lib";

const LANE_H = 72;
const LABEL_W = 200;
const PAD_X = 24;
const VIEWPORT_H = "min(calc(100dvh - 300px), 1120px)";

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
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [panX, setPanX] = useState(0);
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

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { active: true, startX: e.clientX, origin: panX };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }, [panX]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current.active) return;
    const dx = e.clientX - dragRef.current.startX;
    setPanX(dragRef.current.origin + dx);
  }, []);

  const onPointerUp = useCallback(() => {
    dragRef.current.active = false;
  }, []);

  const onKeyDownScroller = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setPanX((x) => x + 48);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setPanX((x) => x - 48);
      }
    },
    [],
  );

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
      <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3">
        <h2 className="type-card-title text-[13px] tracking-[0.06em] text-[color:var(--fg-1,#F5F1E8)]">
          Timeline
        </h2>
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
        <div className="relative px-5 py-16">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-5 top-1/2 h-px -translate-y-1/2 bg-gradient-to-r from-transparent via-gold/25 to-transparent"
          />
          <p className="relative text-center text-sm text-aether-muted-dim">
            No applications yet.
          </p>
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
          {/* Axis */}
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
            {model.lanes.map((lane, i) => (
              <motion.div
                key={lane.applicationId}
                data-testid={`timeline-lane-${lane.applicationId}`}
                className="relative flex items-stretch border-b border-white/[0.04]"
                style={{ height: LANE_H }}
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
                </div>

                <div className="relative flex-1" style={{ minWidth: 480 }}>
                  {/* Rail */}
                  <div
                    aria-hidden="true"
                    className="absolute left-6 right-6 top-1/2 h-px -translate-y-1/2 bg-white/[0.08]"
                  />
                  {/* Connectors */}
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
                          stroke="rgba(201,168,76,0.28)"
                          strokeWidth={1.5}
                          strokeLinecap="round"
                        />
                      );
                    })}
                  </svg>

                  {lane.nodes.map((node) => (
                    <button
                      key={node.id}
                      type="button"
                      data-testid={`timeline-node-${node.id}`}
                      aria-label={`${node.label} — ${lane.jobTitle} at ${lane.company}, ${new Date(node.at).toLocaleString("en-AU")}${node.note ? `. ${node.note}` : ""}`}
                      title={
                        node.note
                          ? `${node.label} · ${node.note}`
                          : node.label
                      }
                      onClick={() => onOpenDetail(lane.applicationId)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onOpenDetail(lane.applicationId);
                        }
                      }}
                      className="group absolute top-1/2 z-[2] flex -translate-x-1/2 -translate-y-1/2 flex-col items-center outline-none"
                      style={{ left: `calc(${PAD_X}px + (100% - ${PAD_X * 2}px) * ${node.x})` }}
                    >
                      <span
                        className="h-3.5 w-3.5 rounded-full border-2 border-[#0F0F12] shadow-[0_0_12px_rgba(201,168,76,0.35)] transition group-hover:scale-125 group-focus-visible:scale-125 group-focus-visible:ring-2 group-focus-visible:ring-gold/50"
                        style={{ backgroundColor: node.color }}
                      />
                      <span className="mt-1 max-w-[96px] truncate text-center text-[9px] font-medium uppercase tracking-[0.08em] text-aether-muted-dim opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100">
                        {node.label}
                      </span>
                      {node.genesis ? (
                        <span className="sr-only">{node.note}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>

          {/* Genesis note once, if any lane has a genesis node */}
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
