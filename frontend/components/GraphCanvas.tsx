"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import AmbientField from "@/components/AmbientField";
import { NODE_COLORS, PULSE_MS, RELATION_COLORS } from "@/lib/theme";
import type { GraphLink, GraphNode } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  selectedId: string | null;
  onSelect: (node: GraphNode | null) => void;
}

const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';

function radius(node: GraphNode): number {
  return 3.4 + Math.min(node.degree ?? 0, 9) * 0.72;
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}\u2026`;
}

export default function GraphCanvas({
  nodes,
  links,
  selectedId,
  onSelect,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Spread the layout out well past the defaults. Node labels are the payload
  // here, not the dots, so the layout has to leave room for text.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg?.d3Force) return;
    fg.d3Force("charge")?.strength(-560).distanceMax(900);
    fg.d3Force("link")?.distance(135).strength(0.4);
  }, [size.width]);

  /**
   * Camera follows the growth.
   *
   * Refitting on every diff with a long transition reads as the instrument
   * panning to keep the new structure in frame, which is what makes the graph
   * feel like it is being built rather than redrawn.
   */
  useEffect(() => {
    if (nodes.length === 0) return;
    const timer = setTimeout(() => fgRef.current?.zoomToFit(700, 140), 420);
    return () => clearTimeout(timer);
  }, [nodes.length]);

  /**
   * Ambient motion.
   *
   * A force graph normally freezes once the simulation cools, which makes a
   * live artifact look like a screenshot. Nudging every node by a fraction of a
   * pixel per tick keeps it breathing without ever displacing the layout,
   * because velocity decay damps the nudge before it accumulates.
   */
  const onEngineTick = useCallback(() => {
    for (const node of nodes as any[]) {
      node.vx = (node.vx ?? 0) + (Math.random() - 0.5) * 0.055;
      node.vy = (node.vy ?? 0) + (Math.random() - 0.5) * 0.055;
    }
  }, [nodes]);

  const drawNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, scale: number) => {
      const color = NODE_COLORS[node.type] ?? "#8b949e";
      const r = radius(node);
      const isActive = node.id === selectedId || node.id === hoverId;

      // Creation pulse: the most-watched animation in the demo. A bright
      // flash on the node itself, then two staggered expanding rings — the
      // second ring is what reads as "the map just grew" on compressed video.
      if (node.bornAt) {
        const age = Date.now() - node.bornAt;
        if (age < PULSE_MS) {
          const t = age / PULSE_MS;
          for (const [delay, reach] of [
            [0, 30],
            [0.18, 44],
          ] as const) {
            const rt = Math.min(Math.max((t - delay) / (1 - delay), 0), 1);
            if (rt <= 0 || rt >= 1) continue;
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + rt * reach, 0, Math.PI * 2);
            ctx.strokeStyle = color;
            ctx.globalAlpha = (1 - rt) * 0.75;
            ctx.lineWidth = (2.2 - rt * 1.4) / scale;
            ctx.stroke();
          }
          ctx.globalAlpha = 1;
          if (t < 0.22) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + 1.5, 0, Math.PI * 2);
            ctx.fillStyle = "#ffffff";
            ctx.globalAlpha = (1 - t / 0.22) * 0.85;
            ctx.fill();
            ctx.globalAlpha = 1;
          }
        }
      }

      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = isActive ? 18 : 8;
      ctx.beginPath();
      if (node.type === "note") {
        // Pins, not orbs: a note is a capture, not a claim.
        ctx.save();
        ctx.translate(node.x, node.y);
        ctx.rotate(Math.PI / 4);
        ctx.rect(-r, -r, r * 2, r * 2);
        ctx.fill();
        ctx.restore();
      } else {
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;

      if (node.echoes?.length) {
        // Cross-project echo: one of the strongest ideas in the product, so
        // the badge is deliberately loud — a dashed comet to a bright dot
        // with its own halo.
        const ex = node.x + r + 12;
        const ey = node.y - 10;
        ctx.beginPath();
        ctx.arc(ex, ey, 4.6, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(126, 231, 135, 0.18)";
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(node.x + r + 1, node.y - 1);
        ctx.lineTo(ex, ey);
        ctx.setLineDash([1.8, 1.8]);
        ctx.strokeStyle = "#7ee787";
        ctx.globalAlpha = 0.9;
        ctx.lineWidth = 1.2 / scale;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.arc(ex, ey, 2.4, 0, Math.PI * 2);
        ctx.fillStyle = "#7ee787";
        ctx.shadowColor = "#7ee787";
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1;
      }

      if (node.id === selectedId) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4.5, 0, Math.PI * 2);
        ctx.strokeStyle = "#e6edf3";
        ctx.lineWidth = 1.1 / scale;
        ctx.stroke();
      }

      if (node.type === "claim" && node.status === "verification_pending") {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 2.6, 0, Math.PI * 2);
        ctx.setLineDash([1.6, 2.2]);
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.6;
        ctx.lineWidth = 0.9 / scale;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      } else if (node.type === "claim" && node.status === "verified") {
        ctx.beginPath();
        ctx.arc(node.x + r + 2.2, node.y - r - 1.4, 1.8, 0, Math.PI * 2);
        ctx.fillStyle = "#3fb950";
        ctx.fill();
      }

      // Labels carry the meaning, but at 70+ nodes and low zoom they are
      // unreadable noise. Declutter: zoomed out, only active, high-degree or
      // freshly-born nodes speak; zooming in brings every label back.
      const recent = node.bornAt && Date.now() - node.bornAt < 9000;
      const prominent = isActive || recent || (node.degree ?? 0) >= 4;
      if (scale < 0.85 && !prominent) return;
      const label = truncate(node.text, isActive ? 74 : 34);
      const fontSize = 4.1;
      ctx.font = `${fontSize}px ${MONO}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";

      const padding = 1.3;
      const width = ctx.measureText(label).width;
      const top = node.y + r + 3;
      ctx.fillStyle = isActive ? "rgba(20,23,28,0.96)" : "rgba(8,9,11,0.78)";
      ctx.fillRect(
        node.x - width / 2 - padding,
        top - padding,
        width + padding * 2,
        fontSize + padding * 2,
      );

      ctx.fillStyle = isActive ? "#e6edf3" : "#7d868f";
      ctx.fillText(label, node.x, top);
    },
    [selectedId, hoverId],
  );

  const drawLink = useCallback(
    (link: any, ctx: CanvasRenderingContext2D, scale: number) => {
      const a = link.source;
      const b = link.target;
      if (!a?.x || !b?.x) return;

      const tension = link.relation === "contradicts";
      const color = RELATION_COLORS[link.relation] ?? "#27476b";

      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = color;
      ctx.lineWidth = (tension ? 2.4 : 0.85) / scale;

      if (tension) {
        // Tensions are the most valuable thing on screen, so they are the only
        // element allowed to move on their own: a slow breathing glow, bright
        // enough to survive video compression.
        const beat = 0.55 + 0.45 * Math.sin(Date.now() / 620);
        ctx.shadowColor = color;
        ctx.shadowBlur = 10 + beat * 16;
        ctx.globalAlpha = 0.8 + beat * 0.2;
      } else {
        ctx.globalAlpha = 0.55;
      }
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;

      // Arrowhead, so relation direction is readable without hovering.
      const angle = Math.atan2(b.y - a.y, b.x - a.x);
      const tipDistance = radius(b) + 2.2;
      const tipX = b.x - Math.cos(angle) * tipDistance;
      const tipY = b.y - Math.sin(angle) * tipDistance;
      const len = (tension ? 5 : 3.8) / scale;
      ctx.beginPath();
      ctx.moveTo(tipX, tipY);
      ctx.lineTo(
        tipX - Math.cos(angle - 0.42) * len,
        tipY - Math.sin(angle - 0.42) * len,
      );
      ctx.lineTo(
        tipX - Math.cos(angle + 0.42) * len,
        tipY - Math.sin(angle + 0.42) * len,
      );
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = tension ? 0.95 : 0.6;
      ctx.fill();
      ctx.globalAlpha = 1;
    },
    [],
  );

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  return (
    <div ref={wrapRef} style={{ position: "absolute", inset: 0 }}>
      {size.width > 0 && (
        <ForceGraph2D
          ref={fgRef}
          width={size.width}
          height={size.height}
          graphData={data as any}
          backgroundColor="rgba(0,0,0,0)"
          nodeRelSize={4}
          nodeCanvasObject={drawNode}
          nodePointerAreaPaint={(node: any, color: string, ctx: any) => {
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius(node) + 5, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();
          }}
          linkCanvasObject={drawLink}
          linkCanvasObjectMode={() => "replace"}
          onNodeClick={(node: any) => onSelect(node as GraphNode)}
          onBackgroundClick={() => onSelect(null)}
          onNodeHover={(node: any) => setHoverId(node ? node.id : null)}
          onEngineTick={onEngineTick}
          cooldownTime={Infinity}
          d3AlphaDecay={0.012}
          d3VelocityDecay={0.42}
          warmupTicks={60}
          enableNodeDrag
        />
      )}
      <AmbientField
        width={size.width}
        height={size.height}
        occupied={nodes.length > 0}
      />
    </div>
  );
}
