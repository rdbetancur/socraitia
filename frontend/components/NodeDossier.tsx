"use client";

import { NODE_COLORS, NODE_LABELS, RELATION_COLORS } from "@/lib/theme";
import type { Dossier, GraphNode, Relation } from "@/lib/types";

/**
 * A claim's biography, not a property inspector.
 *
 * Relations arrive from the API as (relation, node) pairs, which is the right
 * shape for a graph and the wrong shape for a reader: "contradicts →
 * a3f9c1" tells you nothing. So every relation is rendered as a sentence
 * containing the other claim's full text, and direction is folded into the
 * verb ("contradicts" vs "contradicted by") rather than shown as an arrow.
 *
 * Evidence is separated out of the relation list because it answers a
 * different question — not "what argues with this" but "did it survive
 * contact with the literature".
 */

interface Props {
  dossier: Dossier | null;
  loading: boolean;
  onClose: () => void;
  onInterrogate: (node: GraphNode) => void;
  onCenter: (node: GraphNode) => void;
  onJump: (nodeId: string) => void;
}

const PHRASING: Record<Relation, { out: string; in: string }> = {
  supports: { out: "supports", in: "is supported by" },
  contradicts: { out: "contradicts", in: "is contradicted by" },
  refines: { out: "refines", in: "is refined by" },
  questions: { out: "questions", in: "is questioned by" },
  answers: { out: "answers", in: "is answered by" },
  connects_to: { out: "connects to", in: "is connected from" },
};

function stamp(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  // Pinned to en-US: the rest of the interface is English, and a date that
  // switches language with the viewer's browser breaks the sentence around it.
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function Sentence({
  relation,
  direction,
  node,
  onJump,
}: {
  relation: Relation;
  direction: "in" | "out";
  node: GraphNode;
  onJump: (nodeId: string) => void;
}) {
  const verb = PHRASING[relation]?.[direction] ?? relation;
  return (
    <div
      className="rel-sentence"
      style={{ borderLeftColor: RELATION_COLORS[relation] }}
      onClick={() => onJump(node.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onJump(node.id)}
    >
      <span className="rel-verb" style={{ color: RELATION_COLORS[relation] }}>
        {verb}
      </span>{" "}
      <span className="rel-target">{node.text}</span>
    </div>
  );
}

export default function NodeDossier({
  dossier,
  loading,
  onClose,
  onInterrogate,
  onCenter,
  onJump,
}: Props) {
  if (!dossier && !loading) return null;

  const node = dossier?.node;
  const evidenceIn = (dossier?.incoming ?? []).filter(
    (r) => r.node.type === "evidence",
  );
  const argumentsIn = (dossier?.incoming ?? []).filter(
    (r) => r.node.type !== "evidence",
  );
  const argumentsOut = dossier?.outgoing ?? [];
  const supporting = evidenceIn.filter((r) => r.relation === "supports");
  const contradicting = evidenceIn.filter((r) => r.relation === "contradicts");

  return (
    <aside className="dossier">
      <header className="panel-title">
        <span>{loading ? "Loading dossier\u2026" : "Node dossier"}</span>
        <button className="close-x" onClick={onClose} aria-label="Close">
          &#10005;
        </button>
      </header>

      {dossier && node && (
        <div className="dossier-body">
          <div className="dossier-typeline">
            <span
              className={`swatch ${node.type === "note" ? "swatch-note" : ""}`}
              style={{ background: NODE_COLORS[node.type] }}
            />
            <span className="meta" style={{ color: NODE_COLORS[node.type] }}>
              {NODE_LABELS[node.type] ?? node.type}
            </span>
            {node.status === "verification_pending" && (
              <span className="bdg bdg-pending">verifying</span>
            )}
            {node.status === "verified" && (
              <span className="bdg bdg-verified">verified</span>
            )}
            {/* Evidence lives in its own section but still counts as tension:
                a claim contested by the literature is contested. */}
            {[...(dossier.incoming ?? []), ...argumentsOut].some(
              (r) => r.relation === "contradicts",
            ) && <span className="bdg bdg-tension">tension</span>}
          </div>

          <p className="dossier-text">{node.text}</p>

          <p className="dossier-origin">
            {node.source === "ingestion"
              ? `From your library — ${node.provenance || "uploaded document"}`
              : node.source === "verifier"
                ? `Found by the Verifier${node.created_at ? ` on ${stamp(node.created_at)}` : ""}`
                : node.provenance
                  ? node.provenance
                  : `Said in conversation${node.created_at ? `, ${stamp(node.created_at)}` : ""}`}
          </p>

          <div className="dossier-actions">
            <button
              type="button"
              className="interrogate-btn"
              onClick={() => onInterrogate(node)}
            >
              Interrogate this
            </button>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => onCenter(node)}
            >
              Center on canvas
            </button>
          </div>

          {(argumentsOut.length > 0 || argumentsIn.length > 0) && (
            <div className="rel-group">
              <div className="rel-head">In the argument</div>
              {argumentsOut.map((r, i) => (
                <Sentence
                  key={`o-${r.node.id}-${i}`}
                  relation={r.relation}
                  direction="out"
                  node={r.node}
                  onJump={onJump}
                />
              ))}
              {argumentsIn.map((r, i) => (
                <Sentence
                  key={`i-${r.node.id}-${i}`}
                  relation={r.relation}
                  direction="in"
                  node={r.node}
                  onJump={onJump}
                />
              ))}
            </div>
          )}

          <div className="rel-group">
            <div className="rel-head">Verification story</div>
            {node.status === "verification_pending" ? (
              <p className="dossier-story">
                Queued for the Verifier. Evidence will arrive here on its own.
              </p>
            ) : evidenceIn.length === 0 ? (
              <p className="dossier-story">
                {node.type === "claim"
                  ? node.verified_at
                    ? `Checked ${stamp(node.verified_at)} — no external evidence attached.`
                    : "Not checked against external sources."
                  : "Only claims are put to the literature."}
              </p>
            ) : (
              <>
                <p className="dossier-story">
                  {supporting.length} supporting,{" "}
                  {contradicting.length} contradicting
                  {node.verified_at ? ` · ${stamp(node.verified_at)}` : ""}
                </p>
                {evidenceIn.map((r, i) => (
                  <Sentence
                    key={`e-${r.node.id}-${i}`}
                    relation={r.relation}
                    direction="in"
                    node={r.node}
                    onJump={onJump}
                  />
                ))}
              </>
            )}
          </div>

          {(dossier.echoes?.length ?? 0) > 0 && (
            <div className="rel-group">
              <div className="rel-head">Echoes elsewhere</div>
              {dossier.echoes.map((echo, i) => (
                <div
                  className="rel-sentence"
                  key={`${echo.node_id}-${i}`}
                  style={{ borderLeftColor: "#7ee787" }}
                >
                  <span className="rel-verb" style={{ color: "#7ee787" }}>
                    resonates with
                  </span>{" "}
                  <span className="rel-target">{echo.text}</span>{" "}
                  <span className="rel-where">
                    in {echo.project_title}
                    {echo.similarity ? ` · ${echo.similarity.toFixed(2)}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}

          <dl className="dossier-grid">
            <dt>id</dt>
            <dd>{node.id}</dd>
            <dt>session</dt>
            <dd>{node.session_id || "\u2014"}</dd>
            <dt>degree</dt>
            <dd>{node.degree}</dd>
            <dt>created</dt>
            <dd>{node.created_at || "\u2014"}</dd>
          </dl>
        </div>
      )}
    </aside>
  );
}
