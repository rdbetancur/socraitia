"use client";

import { useMemo, useState } from "react";

import { tensionPairs, type AttentionMap } from "@/lib/attention";
import { NODE_COLORS, NODE_LABELS } from "@/lib/theme";
import type { GraphLink, GraphNode } from "@/lib/types";

/**
 * The panel and the canvas are two views of one object.
 *
 * The canvas is unbeatable at showing shape and unusable for finding a
 * specific sentence: at seventy nodes every label is a truncated fragment. So
 * the panel carries the text. Selection is shared in both directions, and the
 * top of the panel is not an index at all — it is the list of things the graph
 * is currently asking the user to resolve.
 */

const TYPE_ORDER = ["gap", "claim", "question", "concept", "evidence", "note"];

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  attention: AttentionMap;
  selectedId: string | null;
  onSelect: (node: GraphNode) => void;
  onInterrogate: (node: GraphNode) => void;
  onCollapse: () => void;
}

/** Same attribution rule as the briefing: never credit the user with evidence. */
function sideTag(source: string): string {
  if (source === "ingestion") return "from your library";
  if (source === "verifier") return "evidence found";
  return "you said";
}

function Badges({ badges }: { badges: { tension: boolean; echo: boolean; pending: boolean } }) {
  return (
    <>
      {badges.tension && <span className="bdg bdg-tension">tension</span>}
      {badges.echo && <span className="bdg bdg-echo">echo</span>}
      {badges.pending && <span className="bdg bdg-pending">verifying</span>}
    </>
  );
}

export default function NodePanel({
  nodes,
  links,
  attention,
  selectedId,
  onSelect,
  onInterrogate,
  onCollapse,
}: Props) {
  const [query, setQuery] = useState("");
  const [showAttention, setShowAttention] = useState(true);

  const tensions = useMemo(() => tensionPairs(nodes, links), [nodes, links]);

  const gaps = useMemo(
    () =>
      nodes
        .filter((n) => n.type === "gap")
        .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [nodes],
  );

  const echoNodes = useMemo(
    () =>
      nodes
        .filter((n) => (n.echoes?.length ?? 0) > 0)
        .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")),
    [nodes],
  );

  const attentionCount = tensions.length + gaps.length + echoNodes.length;

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = q
      ? nodes.filter(
          (n) =>
            n.text.toLowerCase().includes(q) ||
            (n.provenance ?? "").toLowerCase().includes(q),
        )
      : nodes;
    const byType = new Map<string, GraphNode[]>();
    for (const n of matched) {
      const bucket = byType.get(n.type) ?? [];
      bucket.push(n);
      byType.set(n.type, bucket);
    }
    for (const bucket of byType.values()) {
      bucket.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    }
    return TYPE_ORDER.filter((t) => byType.has(t)).map((t) => ({
      type: t,
      items: byType.get(t) ?? [],
    }));
  }, [nodes, query]);

  const matchCount = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <aside className="panel">
      <div className="panel-title">
        <span>Index · {nodes.length} nodes</span>
        <button
          type="button"
          className="panel-collapse"
          onClick={onCollapse}
          title="Collapse for full canvas"
        >
          hide
        </button>
      </div>

      {/* Outside the scroll area on purpose: with several open tensions the
          attention section is taller than the panel, and a filter you have to
          scroll to find is not an instant filter. */}
      <div className="panel-filter">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="filter every thought…"
          spellCheck={false}
        />
        {query && (
          <button type="button" onClick={() => setQuery("")} title="clear">
            ×
          </button>
        )}
      </div>

      <div className="panel-scroll">
        {attentionCount > 0 && !query && (
          <section className="attn">
            <button
              type="button"
              className="attn-head"
              onClick={() => setShowAttention((v) => !v)}
            >
              <span>Requires your attention</span>
              <span className="attn-n">{attentionCount}</span>
            </button>

            {showAttention && (
              <div className="attn-body">
                {tensions.map((t) => {
                  const own = t.a.source === "user" ? t.a : t.b;
                  return (
                    <div key={t.edgeId} className="attn-item attn-tension">
                      <div className="attn-kind">contradiction</div>
                      <span className="attn-side">{sideTag(t.a.source)}</span>
                      <p
                        className="attn-claim"
                        onClick={() => onSelect(t.a)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => e.key === "Enter" && onSelect(t.a)}
                      >
                        {t.a.text}
                      </p>
                      <div className="attn-vs">contradicts</div>
                      <span className="attn-side">{sideTag(t.b.source)}</span>
                      <p
                        className="attn-claim"
                        onClick={() => onSelect(t.b)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => e.key === "Enter" && onSelect(t.b)}
                      >
                        {t.b.text}
                      </p>
                      <button
                        type="button"
                        className="interrogate-btn interrogate-sm"
                        onClick={() => onInterrogate(own)}
                      >
                        Interrogate
                      </button>
                    </div>
                  );
                })}

                {gaps.map((n) => (
                  <div key={n.id} className="attn-item attn-gap">
                    <div className="attn-kind">unexplored gap</div>
                    <p
                      className="attn-claim"
                      onClick={() => onSelect(n)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && onSelect(n)}
                    >
                      {n.text}
                    </p>
                    <button
                      type="button"
                      className="interrogate-btn interrogate-sm"
                      onClick={() => onInterrogate(n)}
                    >
                      Interrogate
                    </button>
                  </div>
                ))}

                {echoNodes.map((n) => (
                  <div key={n.id} className="attn-item attn-echo-item">
                    <div className="attn-kind">
                      echo · {n.echoes?.[0]?.project_title}
                    </div>
                    <p
                      className="attn-claim"
                      onClick={() => onSelect(n)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && onSelect(n)}
                    >
                      {n.text}
                    </p>
                    <p className="attn-remote">{n.echoes?.[0]?.text}</p>
                    <button
                      type="button"
                      className="interrogate-btn interrogate-sm"
                      onClick={() => onInterrogate(n)}
                    >
                      Interrogate
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {query && (
          <div className="panel-matches meta">
            {matchCount} match{matchCount === 1 ? "" : "es"}
          </div>
        )}

        {groups.map((group) => (
          <section key={group.type} className="idx-group">
            <div className="idx-group-head">
              <span
                className={`swatch ${group.type === "note" ? "swatch-note" : ""}`}
                style={{ background: NODE_COLORS[group.type] }}
              />
              {NODE_LABELS[group.type]}
              <span className="idx-group-n">{group.items.length}</span>
            </div>
            {group.items.map((n) => {
              const badges = attention[n.id];
              return (
                <div
                  key={n.id}
                  className={`idx-row${selectedId === n.id ? " idx-row-on" : ""}${
                    badges?.heat === 0 ? " idx-row-settled" : ""
                  }`}
                  onClick={() => onSelect(n)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && onSelect(n)}
                >
                  <p className="idx-text">{n.text}</p>
                  <div className="idx-meta">
                    {badges && <Badges badges={badges} />}
                    {n.source === "ingestion" && (
                      <span className="bdg bdg-doc">literature</span>
                    )}
                    {badges?.verified && <span className="meta">verified</span>}
                    {n.provenance ? (
                      <span className="idx-prov">{n.provenance}</span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </section>
        ))}

        {nodes.length > 0 && matchCount === 0 && (
          <div className="panel-empty meta">nothing matches</div>
        )}
      </div>
    </aside>
  );
}
