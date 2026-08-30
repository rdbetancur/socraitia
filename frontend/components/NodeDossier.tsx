"use client";

import { NODE_COLORS, NODE_LABELS, RELATION_COLORS } from "@/lib/theme";
import type { Dossier, Relation } from "@/lib/types";

interface Props {
  dossier: Dossier | null;
  loading: boolean;
  onClose: () => void;
  onInterrogate: (node: Dossier["node"]) => void;
}

function RelationGroup({
  title,
  items,
  arrow,
}: {
  title: string;
  items: { relation: Relation; node: { id: string; text: string } }[];
  arrow: string;
}) {
  if (items.length === 0) return null;
  return (
    <div className="rel-group">
      <div className="rel-head">
        {title} ({items.length})
      </div>
      {items.map((item, i) => (
        <div
          className="rel-item"
          key={`${item.node.id}-${i}`}
          style={{ borderLeftColor: RELATION_COLORS[item.relation] }}
        >
          <span
            className="rel-tag"
            style={{ color: RELATION_COLORS[item.relation] }}
          >
            {arrow} {item.relation.toUpperCase()}
          </span>
          {item.node.text}
        </div>
      ))}
    </div>
  );
}

/** Provenance for one node: what it is, where it came from, what argues with it. */
export default function NodeDossier({ dossier, loading, onClose, onInterrogate }: Props) {
  if (!dossier && !loading) return null;

  return (
    <aside className="dossier">
      <header className="panel-title">
        <span>{loading ? "Loading dossier\u2026" : "Node dossier"}</span>
        <button className="close-x" onClick={onClose} aria-label="Close">
          &#10005;
        </button>
      </header>

      {dossier && (
        <div className="dossier-body">
          <div
            className="meta"
            style={{ color: NODE_COLORS[dossier.node.type], marginBottom: 7 }}
          >
            {NODE_LABELS[dossier.node.type] ?? dossier.node.type}
          </div>
          <p className="dossier-text">{dossier.node.text}</p>

          <button
            type="button"
            className="interrogate-btn"
            onClick={() => onInterrogate(dossier.node)}
          >
            Interrogate this
          </button>

          <dl className="dossier-grid">
            <dt>id</dt>
            <dd>{dossier.node.id}</dd>
            <dt>source</dt>
            <dd>{dossier.node.source}</dd>
            {dossier.node.provenance ? (
              <>
                <dt>from</dt>
                <dd>{dossier.node.provenance}</dd>
              </>
            ) : null}
            <dt>status</dt>
            <dd>
              {dossier.node.status === "verification_pending"
                ? "verification pending"
                : dossier.node.status === "verified"
                  ? "verified"
                  : dossier.node.status}
            </dd>
            <dt>session</dt>
            <dd>{dossier.node.session_id || "\u2014"}</dd>
            <dt>degree</dt>
            <dd>{dossier.node.degree}</dd>
            <dt>created</dt>
            <dd>{dossier.node.created_at || "\u2014"}</dd>
          </dl>

          <RelationGroup
            title="Argues into this"
            items={dossier.incoming}
            arrow="←"
          />
          <RelationGroup
            title="This argues into"
            items={dossier.outgoing}
            arrow="→"
          />

          {(dossier.echoes?.length ?? 0) > 0 && (
            <div className="rel-group">
              <div className="rel-head">
                Connects across projects ({dossier.echoes.length})
              </div>
              {dossier.echoes.map((echo, i) => (
                <div
                  className="rel-item"
                  key={`${echo.node_id}-${i}`}
                  style={{ borderLeftColor: "#7ee787" }}
                >
                  <span className="rel-tag" style={{ color: "#7ee787" }}>
                    → {echo.project_title.toUpperCase()}
                    {echo.similarity
                      ? `  ${echo.similarity.toFixed(2)}`
                      : ""}
                  </span>
                  {echo.text}
                </div>
              ))}
            </div>
          )}

          {dossier.incoming.length === 0 &&
            dossier.outgoing.length === 0 &&
            !(dossier.echoes?.length) && (
              <div className="meta">no relations recorded yet</div>
            )}
        </div>
      )}
    </aside>
  );
}
