"use client";

/**
 * Sankey Flow — SVG funnel per wireframe sankey-view-at41.
 *
 * Geometry mirrors the wireframe frame (1120×380, nodes at fixed x, all
 * vertically centred on y=180). Node heights scale with the stage values via
 * a power curve tuned so the canonical figures (847→412→156→23→4) reproduce
 * the wireframe's node heights (~300/200/110/40/12).
 */
import { useId } from "react";

import type { SankeyData } from "./tracker-api";

const FRAME_W = 1120;
const NODE_W = 14;
const CY = 180;
const MAX_H = 300;
const MIN_H = 12;
const NODE_X = [40, 290, 540, 790, 1040];

function nodeHeight(value: number, max: number): number {
  if (max <= 0) return MIN_H;
  return Math.max(MIN_H, MAX_H * Math.pow(value / max, 0.55));
}

export default function SankeyFlow({ data }: { data: SankeyData }) {
  const gradientNs = useId().replace(/[:]/g, "");
  const max = Math.max(...data.stages.map((s) => s.value), 1);
  const nodes = data.stages.map((s, i) => {
    const h = nodeHeight(s.value, max);
    return { ...s, x: NODE_X[i] ?? 40 + i * 250, h, top: CY - h / 2, bottom: CY + h / 2 };
  });

  const flows = nodes.slice(0, -1).map((from, i) => {
    const to = nodes[i + 1];
    const x1 = from.x + NODE_W;
    const x2 = to.x;
    const mx = (x1 + x2) / 2;
    return {
      id: `${gradientNs}-f${i}`,
      from,
      to,
      path:
        `M${x1},${from.top} C${mx},${from.top} ${mx},${to.top} ${x2},${to.top} ` +
        `L${x2},${to.bottom} C${mx},${to.bottom} ${mx},${from.bottom} ${x1},${from.bottom} Z`,
      dropX: (x1 + x2) / 2,
      dropY: Math.max(from.bottom - 4, to.bottom + 14),
      dropoff: data.dropoffs[i],
    };
  });

  return (
    <div className="glass mt-4 overflow-x-auto rounded-2xl border border-white/10 p-6">
      <svg
        viewBox={`0 0 ${FRAME_W} 380`}
        className="w-full min-w-[1000px]"
        role="img"
        aria-label={`Application flow sankey: ${data.stages
          .map((s) => `${s.label} ${s.value}`)
          .join(", ")}`}
        data-testid="sankey-svg"
      >
        <defs>
          {flows.map((f) => (
            <linearGradient key={f.id} id={f.id} x1="0" x2="1">
              <stop offset="0" stopColor={f.from.color} stopOpacity="0.5" />
              <stop offset="1" stopColor={f.to.color} stopOpacity="0.45" />
            </linearGradient>
          ))}
        </defs>
        {flows.map((f) => (
          <path key={`p-${f.id}`} d={f.path} fill={`url(#${f.id})`} />
        ))}
        {nodes.map((n) => (
          <rect key={n.key} x={n.x} y={n.top} width={NODE_W} height={n.h} rx={3} fill={n.color} />
        ))}
        {nodes.map((n, i) => (
          <g key={`t-${n.key}`}>
            <text
              x={n.x + NODE_W / 2}
              y={n.top - 10}
              fill="#F4F4F8"
              fontSize="12"
              fontWeight="600"
              textAnchor="middle"
            >
              {n.label}
            </text>
            <text
              x={n.x + NODE_W / 2}
              y={348}
              fill={i === 0 ? "#818CF8" : n.color}
              fontSize="13"
              fontWeight="700"
              textAnchor="middle"
              fontFamily="'JetBrains Mono', monospace"
            >
              {n.value}
            </text>
          </g>
        ))}
        {flows.map((f) =>
          f.dropoff ? (
            <text
              key={`d-${f.id}`}
              x={f.dropX}
              y={f.dropY}
              fill="#F87171"
              fontSize="10.5"
              textAnchor="middle"
              fontFamily="'JetBrains Mono', monospace"
            >
              {/* Defense-in-depth (MV-application-tracker-006): the backend
                  cumulative model keeps this >= 0, but never let a stray
                  negative render as the broken literal "−-3" — clamp here
                  too so a data anomaly degrades to "−0", not nonsense. */}
              −{Math.max(0, f.dropoff.count)} · {f.dropoff.reason}
            </text>
          ) : null,
        )}
      </svg>
      <p className="mt-4 text-center text-[11px] text-aether-muted-dim" data-testid="sankey-insight">
        {data.insight}
      </p>
    </div>
  );
}
