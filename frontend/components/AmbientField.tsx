"use client";

import { useEffect, useRef } from "react";

/**
 * The empty canvas has to feel like an instrument waiting, not a broken
 * screen. This field runs under the graph at all times: faint drifting motes
 * and the occasional near-connection, so the stage is never still — even
 * before the first node exists. Opacity drops once the graph has structure,
 * so it stays atmosphere rather than competing with the data.
 */

type Mote = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  a: number;
};

const COUNT = 56;
const LINK_DIST = 132;

function seed(width: number, height: number): Mote[] {
  return Array.from({ length: COUNT }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: (Math.random() - 0.5) * 0.18,
    vy: (Math.random() - 0.5) * 0.18,
    r: 0.7 + Math.random() * 1.3,
    a: 0.14 + Math.random() * 0.22,
  }));
}

export default function AmbientField({
  width,
  height,
  occupied,
}: {
  width: number;
  height: number;
  occupied: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const motesRef = useRef<Mote[]>([]);

  useEffect(() => {
    if (width < 2 || height < 2) return;
    motesRef.current = seed(width, height);
  }, [width, height]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width < 2 || height < 2) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let frame = 0;
    let raf = 0;

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      const motes = motesRef.current;
      const field = occupied ? 0.32 : 1;

      for (const m of motes) {
        m.x += m.vx;
        m.y += m.vy;
        if (m.x < -8) m.x = width + 8;
        if (m.x > width + 8) m.x = -8;
        if (m.y < -8) m.y = height + 8;
        if (m.y > height + 8) m.y = -8;
      }

      ctx.lineWidth = 0.6;
      for (let i = 0; i < motes.length; i++) {
        for (let j = i + 1; j < motes.length; j++) {
          const a = motes[i];
          const b = motes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > LINK_DIST * LINK_DIST) continue;
          const t = 1 - Math.sqrt(d2) / LINK_DIST;
          ctx.strokeStyle = `rgba(88, 166, 255, ${t * 0.16 * field})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      const pulse = 0.72 + 0.28 * Math.sin(frame / 90);
      for (const m of motes) {
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(230, 237, 243, ${m.a * pulse * field})`;
        ctx.fill();
      }

      frame += 1;
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [width, height, occupied]);

  if (width < 2 || height < 2) return null;

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      aria-hidden
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        zIndex: 0,
      }}
    />
  );
}
