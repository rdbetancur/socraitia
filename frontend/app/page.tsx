"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AgentFeed from "@/components/AgentFeed";
import ChatRail from "@/components/ChatRail";
import GraphCanvas from "@/components/GraphCanvas";
import NodeDossier from "@/components/NodeDossier";
import ProjectSwitcher from "@/components/ProjectSwitcher";
import {
  createProject,
  endSession,
  fetchBootstrap,
  fetchDossier,
  sendFeedback,
  streamTurn,
  uploadDocuments,
  watchProject,
} from "@/lib/api";
import { NODE_COLORS, NODE_LABELS } from "@/lib/theme";
import type {
  Bootstrap,
  Dossier,
  FeedbackVerdict,
  FeedLine,
  GraphLink,
  GraphNode,
  LearnerModel,
  Message,
  TurnEvent,
  TurnMode,
} from "@/lib/types";

type Status = "connecting" | "ready" | "working" | "down";

export default function Console() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [feed, setFeed] = useState<FeedLine[]>([]);
  const [exchange, setExchange] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [dossierLoading, setDossierLoading] = useState(false);
  const [learner, setLearner] = useState<LearnerModel | null>(null);
  const [dragging, setDragging] = useState(false);
  const [ingestFlash, setIngestFlash] = useState(false);
  const [focusNode, setFocusNode] = useState<GraphNode | null>(null);

  const applyBoot = useCallback((data: Bootstrap) => {
    setBoot(data);
    setNodes(data.nodes);
    setLinks(data.edges);
    setMessages([]);
    setFeed([]);
    setExchange(1);
    setSelectedId(null);
    setDossier(null);
    setLearner(data.learner_model ?? null);
    setStatus("ready");
  }, []);

  useEffect(() => {
    fetchBootstrap()
      .then(applyBoot)
      .catch(() => setStatus("down"));
  }, [applyBoot]);

  const switchProject = useCallback(
    (projectId: string) => {
      setStatus("connecting");
      fetchBootstrap(projectId)
        .then(applyBoot)
        .catch(() => setStatus("down"));
    },
    [applyBoot],
  );

  const newProject = useCallback(
    async (title: string, domain: string) => {
      const created = await createProject(title, domain);
      setStatus("connecting");
      const data = await fetchBootstrap(created.id);
      applyBoot(data);
    },
    [applyBoot],
  );

  const ingest = useCallback((event: TurnEvent) => {
    if (event.type === "agent") {
      setFeed((prev) => {
        if (prev.some((l) => l.line === event.line)) return prev;
        return [...prev, { agent: event.agent, line: event.line, at: event.at }];
      });
    } else if (event.type === "graph_diff") {
      const born = Date.now();
      setNodes((prev) => {
        const known = new Set(prev.map((n) => n.id));
        const fresh = event.nodes
          .filter((n) => !known.has(n.id))
          .map((n) => ({ ...n, bornAt: born }));
        return fresh.length ? [...prev, ...fresh] : prev;
      });
      setLinks((prev) => {
        const known = new Set(prev.map((l) => l.id));
        const fresh = event.edges
          .filter((l) => l.relation !== "connects_to" && !known.has(l.id))
          .map((l) => ({ ...l, bornAt: born }));
        return fresh.length ? [...prev, ...fresh] : prev;
      });
    } else if (event.type === "node_status") {
      setNodes((prev) =>
        prev.map((n) => {
          const updated = event.nodes.find((u) => u.id === n.id);
          return updated ? { ...n, status: updated.status } : n;
        }),
      );
    } else if (event.type === "learner") {
      setLearner(event.learner_model);
    } else if (event.type === "echoes") {
      setNodes((prev) =>
        prev.map((n) => {
          const updated = event.nodes.find((u) => u.id === n.id);
          return updated ? { ...n, echoes: updated.echoes } : n;
        }),
      );
    }
  }, []);

  useEffect(() => {
    if (!boot?.project_id) return;
    return watchProject(boot.project_id, ingest);
  }, [boot?.project_id, ingest]);

  const selectNode = useCallback(
    (node: GraphNode | null) => {
      setSelectedId(node?.id ?? null);
      setDossier(null);
      if (!node || !boot) return;
      setDossierLoading(true);
      fetchDossier(boot.project_id, node.id)
        .then(setDossier)
        .catch(() => setDossier(null))
        .finally(() => setDossierLoading(false));
    },
    [boot],
  );

  const send = useCallback(
    async (text: string, mode: TurnMode) => {
      if (!boot) return;
      setStatus("working");
      if (mode === "note") {
        setMessages((prev) => [...prev, { role: "user", text, kind: "note" }]);
      } else {
        setMessages((prev) => [
          ...prev,
          { role: "user", text },
          { role: "partner", text: "", streaming: true },
        ]);
      }

      try {
        for await (const event of streamTurn({
          project_id: boot.project_id,
          session_id: boot.session_id,
          message: text,
          mode,
          focus_node_id: focusNode?.id ?? null,
        })) {
          if (event.type === "token") {
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, text: last.text + event.text };
              return next;
            });
          } else if (
            event.type === "agent" ||
            event.type === "graph_diff" ||
            event.type === "echoes" ||
            event.type === "node_status" ||
            event.type === "learner"
          ) {
            ingest(event);
          } else if (event.type === "done") {
            setExchange(event.exchange + 1);
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.streaming) {
                next[next.length - 1] = {
                  ...last,
                  streaming: false,
                  exchange: event.exchange,
                };
              }
              return next;
            });
          } else if (event.type === "error") {
            setFeed((prev) => [
              ...prev,
              { agent: "SYSTEM", line: `[SYSTEM] ${event.message}`, at: event.at },
            ]);
          }
        }
        setStatus("ready");
      } catch (err) {
        setStatus("down");
        setFeed((prev) => [
          ...prev,
          {
            agent: "SYSTEM",
            line: `[SYSTEM] connection lost: ${String(err)}`,
            at: new Date().toISOString(),
          },
        ]);
      }
    },
    [boot, focusNode],
  );

  const giveFeedback = useCallback(
    async (ex: number, question: string, verdict: FeedbackVerdict) => {
      if (!boot) return;
      setMessages((prev) =>
        prev.map((m) => (m.exchange === ex ? { ...m, feedback: verdict } : m)),
      );
      try {
        const result = await sendFeedback({
          project_id: boot.project_id,
          session_id: boot.session_id,
          exchange: ex,
          question,
          verdict,
        });
        setFeed((prev) => [
          ...prev,
          {
            agent: "MODELER",
            line: result.line,
            at: new Date().toISOString(),
          },
        ]);
      } catch (err) {
        setFeed((prev) => [
          ...prev,
          {
            agent: "SYSTEM",
            line: `[SYSTEM] feedback failed: ${String(err)}`,
            at: new Date().toISOString(),
          },
        ]);
      }
    },
    [boot],
  );

  const startNewSession = useCallback(async () => {
    if (!boot) return;
    setStatus("working");
    try {
      const ended = await endSession(boot.project_id, boot.session_id);
      const data = await fetchBootstrap(boot.project_id);
      applyBoot(data);
      if (ended.learner_model) setLearner(ended.learner_model);
      if (ended.line) {
        setFeed([
          {
            agent: "MODELER",
            line: ended.line,
            at: new Date().toISOString(),
          },
        ]);
      }
    } catch (err) {
      setStatus("down");
      setFeed((prev) => [
        ...prev,
        {
          agent: "SYSTEM",
          line: `[SYSTEM] could not end session: ${String(err)}`,
          at: new Date().toISOString(),
        },
      ]);
    }
  }, [boot, applyBoot]);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (!boot || !files.length) return;
      setIngestFlash(true);
      setTimeout(() => setIngestFlash(false), 3200);
      setFeed((prev) => [
        ...prev,
        {
          agent: "INGESTION",
          line: `[INGESTION] ${files.map((f) => f.name).join(", ")} → uploading`,
          at: new Date().toISOString(),
        },
      ]);
      try {
        await uploadDocuments(boot.project_id, files);
      } catch (err) {
        setFeed((prev) => [
          ...prev,
          {
            agent: "SYSTEM",
            line: `[SYSTEM] upload failed: ${String(err)}`,
            at: new Date().toISOString(),
          },
        ]);
      }
    },
    [boot],
  );

  const onDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = Array.from(e.dataTransfer.files).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf"),
      );
      await uploadFiles(files);
    },
    [uploadFiles],
  );

  const tensions = useMemo(
    () => links.filter((l) => l.relation === "contradicts").length,
    [links],
  );
  const gaps = useMemo(() => nodes.filter((n) => n.type === "gap").length, [nodes]);
  const echoCount = useMemo(
    () => nodes.reduce((n, node) => n + (node.echoes?.length ?? 0), 0),
    [nodes],
  );

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">SOCRAITIA</div>
        <div className="topbar-meta">
          <ProjectSwitcher
            currentId={boot?.project_id ?? ""}
            projects={boot?.projects ?? []}
            disabled={status === "working"}
            onSwitch={switchProject}
            onCreate={newProject}
          />
          <span className="kv">
            session <b>{boot?.session_id ?? "—"}</b>
          </span>
          <button
            type="button"
            className="session-end"
            disabled={status === "working" || !boot}
            onClick={startNewSession}
          >
            New session
          </button>
          <span className="kv">
            model <b>{boot?.models.socratic ?? "—"}</b>@
            <b>{boot?.models.location ?? "—"}</b>
          </span>
          <span className="live">
            <span
              className={`dot ${
                status === "working" ? "working" : status === "down" ? "down" : ""
              }`}
            />
            {status.toUpperCase()}
          </span>
        </div>
      </header>

      <div className="main">
        <div
          className={`stage${dragging ? " stage-drop" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {dragging && (
            <div className="drop-hint">Drop a paper onto the map</div>
          )}
          <GraphCanvas
            nodes={nodes}
            links={links}
            selectedId={selectedId}
            onSelect={selectNode}
          />
          {nodes.length === 0 && status !== "connecting" && (
            <div className="stage-empty">
              <h2>Type what you're thinking. Watch it become a map.</h2>
              <p>or drop a paper onto the canvas</p>
            </div>
          )}
          {ingestFlash && (
            <div className="ingest-flash">
              <span>document entering the map</span>
            </div>
          )}
          <NodeDossier
            dossier={dossier}
            loading={dossierLoading}
            onClose={() => selectNode(null)}
            onInterrogate={(node) => {
              setFocusNode(node);
              selectNode(null);
            }}
          />
        </div>

        <div className="rail">
          <ChatRail
            messages={messages}
            busy={status === "working"}
            exchange={exchange}
            onSend={send}
            onFeedback={giveFeedback}
            onUpload={uploadFiles}
            focusText={focusNode?.text ?? null}
            onClearFocus={() => setFocusNode(null)}
          />
          <AgentFeed lines={feed} />
        </div>
      </div>

      <footer className="statusbar">
        <span>
          {nodes.length} nodes · {links.length} edges
        </span>
        <span style={{ color: tensions ? "#f85149" : undefined }}>
          {tensions} tension{tensions === 1 ? "" : "s"}
        </span>
        <span style={{ color: echoCount ? "#7ee787" : undefined }}>
          {echoCount} echo{echoCount === 1 ? "" : "es"}
        </span>
        <span>
          {nodes.filter((n) => n.status === "verification_pending").length} pending
        </span>
        <span>{gaps} argument gaps</span>
        <span>
          learner {learner?.scaffolding_level ?? "none"}
          {learner?.blind_spots?.length
            ? ` · ${learner.blind_spots.length} blind spot${learner.blind_spots.length === 1 ? "" : "s"}`
            : ""}
        </span>
        <div className="legend">
          {Object.entries(NODE_COLORS).map(([type, color]) => (
            <span className="legend-item" key={type}>
              <span
                className={`swatch ${type === "note" ? "swatch-note" : ""}`}
                style={{ background: color }}
              />
              {NODE_LABELS[type]}
            </span>
          ))}
        </div>
      </footer>
    </div>
  );
}
