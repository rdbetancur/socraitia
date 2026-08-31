"use client";

import { RELATION_COLORS } from "@/lib/theme";
import type { Briefing as BriefingData } from "@/lib/types";

/**
 * Arrival, not a widget.
 *
 * This is the only screen in Socraitia that reports rather than asks, and it
 * exists because the most valuable work the system does happens when nobody is
 * watching: claims verified, tensions found, echoes across projects. Every row
 * shows both sides in full and offers the one action worth taking on it.
 *
 * If nothing happened it does not render at all. Silence is honest.
 */

interface Props {
  data: BriefingData;
  projectTitle: string;
  onInterrogate: (nodeId: string) => void;
  onReveal: (nodeId: string) => void;
  onDismiss: () => void;
}

function Count({
  n,
  one,
  many,
  color,
}: {
  n: number;
  one: string;
  many: string;
  color?: string;
}) {
  if (!n) return null;
  return (
    <span className="brief-count">
      <b style={color ? { color } : undefined}>{n}</b> {n === 1 ? one : many}
    </span>
  );
}

/**
 * Attribution matters more here than anywhere else in the product: telling a
 * user "you said" about a sentence the Verifier fetched from the web would be
 * the single most damaging thing this screen could do.
 */
function sideTag(source?: string): string {
  if (source === "ingestion") return "from your library";
  if (source === "verifier") return "evidence found";
  return "you said";
}

/** Interrogate the user's own claim, never the evidence that contests it. */
function ownSide(t: BriefingData["tensions"][number]): string {
  return t.a.source === "user" ? t.a.node_id : t.b.node_id;
}

export default function Briefing({
  data,
  projectTitle,
  onInterrogate,
  onReveal,
  onDismiss,
}: Props) {
  const { counts } = data;

  return (
    <div className="brief-scrim" role="dialog" aria-label="Briefing">
      <div className="brief">
        <header className="brief-head">
          <div>
            <div className="meta">While you were away · {projectTitle}</div>
            <h2 className="brief-title">
              The instrument kept working.
            </h2>
          </div>
          <button type="button" className="brief-dismiss" onClick={onDismiss}>
            Enter the map
          </button>
        </header>

        <div className="brief-counts">
          <Count
            n={counts.tensions}
            one="tension detected"
            many="tensions detected"
            color="#f85149"
          />
          <Count
            n={counts.echoes}
            one="echo to another project"
            many="echoes to other projects"
            color="#7ee787"
          />
          <Count
            n={counts.verified}
            one="claim verified"
            many="claims verified"
            color="#58a6ff"
          />
          <Count n={counts.evidence} one="source found" many="sources found" />
          <Count
            n={counts.ingested}
            one="claim from your library"
            many="claims from your library"
          />
        </div>

        <div className="brief-body">
          {data.tensions.length > 0 && (
            <section className="brief-section">
              <div className="brief-section-head" style={{ color: "#f85149" }}>
                Where your claims are contested
              </div>
              {data.tensions.map((t) => (
                <div key={t.edge_id} className="brief-item brief-tension">
                  <div className="brief-side">
                    <span className="brief-side-tag">{sideTag(t.a.source)}</span>
                    <p>{t.a.text}</p>
                    {t.a.provenance ? (
                      <span className="brief-prov">{t.a.provenance}</span>
                    ) : null}
                  </div>
                  <div
                    className="brief-vs"
                    style={{ color: RELATION_COLORS.contradicts }}
                  >
                    contradicts
                  </div>
                  <div className="brief-side">
                    <span className="brief-side-tag">{sideTag(t.b.source)}</span>
                    <p>{t.b.text}</p>
                    {t.b.provenance ? (
                      <span className="brief-prov">{t.b.provenance}</span>
                    ) : null}
                  </div>
                  <div className="brief-actions">
                    <button
                      type="button"
                      className="interrogate-btn"
                      onClick={() => onInterrogate(ownSide(t))}
                    >
                      Interrogate
                    </button>
                    <button
                      type="button"
                      className="ghost-btn"
                      onClick={() => onReveal(ownSide(t))}
                    >
                      Show on map
                    </button>
                    <span className="meta">found by {t.by}</span>
                  </div>
                </div>
              ))}
            </section>
          )}

          {data.echoes.length > 0 && (
            <section className="brief-section">
              <div className="brief-section-head" style={{ color: "#7ee787" }}>
                Echoes across your projects
              </div>
              {data.echoes.map((e) => (
                <div key={e.edge_id} className="brief-item brief-echo">
                  <div className="brief-side">
                    <span className="brief-side-tag">here</span>
                    <p>{e.local.text}</p>
                  </div>
                  <div className="brief-vs" style={{ color: "#7ee787" }}>
                    resonates with · {e.similarity.toFixed(2)}
                  </div>
                  <div className="brief-side">
                    <span className="brief-side-tag">
                      {e.remote.project_title}
                    </span>
                    <p>{e.remote.text}</p>
                  </div>
                  <div className="brief-actions">
                    <button
                      type="button"
                      className="interrogate-btn"
                      onClick={() => onInterrogate(e.local.node_id)}
                    >
                      Interrogate
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {data.verified.length > 0 && (
            <section className="brief-section">
              <div className="brief-section-head" style={{ color: "#58a6ff" }}>
                Verified against external evidence
              </div>
              {data.verified.map((v) => (
                <div key={v.node_id} className="brief-item">
                  <p className="brief-claim">{v.text}</p>
                  {v.evidence.map((ev, i) => (
                    <p key={i} className="brief-evidence">
                      {ev}
                    </p>
                  ))}
                  <div className="brief-actions">
                    <button
                      type="button"
                      className="ghost-btn"
                      onClick={() => onReveal(v.node_id)}
                    >
                      Show on map
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {data.ingested.length > 0 && (
            <section className="brief-section">
              <div className="brief-section-head" style={{ color: "#3fb950" }}>
                New claims from literature you added
              </div>
              {data.ingested.map((it) => (
                <div key={it.node_id} className="brief-item">
                  <p className="brief-claim">{it.text}</p>
                  <span className="brief-prov">{it.provenance}</span>
                  <div className="brief-actions">
                    <button
                      type="button"
                      className="interrogate-btn"
                      onClick={() => onInterrogate(it.node_id)}
                    >
                      Interrogate
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
