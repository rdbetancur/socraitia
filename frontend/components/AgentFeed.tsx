"use client";

import { useEffect, useRef } from "react";

import { AGENT_COLORS } from "@/lib/theme";
import type { FeedLine } from "@/lib/types";

/**
 * The engine room, on stage.
 *
 * These are the backend's own agent log lines, streamed over the same SSE
 * connection as the response, so what the judge reads here is literally what
 * Cloud Run logged — not a UI narration of it.
 */
export default function AgentFeed({ lines }: { lines: FeedLine[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lines.length]);

  return (
    <section className="feed">
      <header className="panel-title">
        <span>Agent activity</span>
        <span style={{ color: "#3a4048" }}>{lines.length}</span>
      </header>
      <div className="feed-lines">
        {lines.length === 0 && (
          <div style={{ color: "#3a4048" }}>
            awaiting first exchange&hellip;
          </div>
        )}
        {lines.map((line, i) => {
          const time = line.at.slice(11, 19);
          const body = line.line.replace(/^\[[^\]]+\]\s*/, "");
          return (
            <div className="feed-line" key={`${line.at}-${i}`}>
              <span className="feed-time">{time}</span>
              <span
                className="feed-agent"
                style={{ color: AGENT_COLORS[line.agent] ?? "#8b949e" }}
              >
                [{line.agent}]
              </span>
              <span className="feed-msg">{body}</span>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </section>
  );
}
