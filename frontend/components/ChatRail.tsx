"use client";

import { useEffect, useRef, useState } from "react";

import type {
  FeedbackVerdict,
  Message,
  SessionPulse,
  TurnMode,
} from "@/lib/types";

interface Props {
  messages: Message[];
  busy: boolean;
  exchange: number;
  pulse: SessionPulse;
  onSend: (text: string, mode: TurnMode) => void;
  onFeedback: (exchange: number, question: string, verdict: FeedbackVerdict) => void;
  onUpload: (files: File[]) => void;
  focusText: string | null;
  onClearFocus: () => void;
}

/** Progress has to be felt, so the pulse is quiet but never absent once work starts. */
function Pulse({ pulse }: { pulse: SessionPulse }) {
  if (!pulse.nodes && !pulse.edges) return null;
  return (
    <div className="pulse">
      <span className="pulse-label">this session</span>
      <span className="pulse-stat">
        <b>+{pulse.nodes}</b> node{pulse.nodes === 1 ? "" : "s"}
      </span>
      {pulse.tensions > 0 && (
        <span className="pulse-stat pulse-tension">
          <b>{pulse.tensions}</b> tension
          {pulse.tensions === 1 ? "" : "s"} surfaced
        </span>
      )}
      {pulse.gaps > 0 && (
        <span className="pulse-stat pulse-gap">
          <b>{pulse.gaps}</b> gap{pulse.gaps === 1 ? "" : "s"}
        </span>
      )}
      {pulse.echoes > 0 && (
        <span className="pulse-stat pulse-echo">
          <b>{pulse.echoes}</b> echo{pulse.echoes === 1 ? "" : "es"}
        </span>
      )}
    </div>
  );
}

export default function ChatRail({
  messages,
  busy,
  exchange,
  pulse,
  onSend,
  onFeedback,
  onUpload,
  focusText,
  onClearFocus,
}: Props) {
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<TurnMode>("dialogue");
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function submit() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    onSend(text, mode);
  }

  const note = mode === "note";

  return (
    <section className="dialogue">
      <header className="panel-title">
        <span>{note ? "Quick note" : "Dialogue"}</span>
        <span style={{ color: "#3a4048" }}>
          {note ? "no question" : `exchange ${exchange}`}
        </span>
      </header>

      <Pulse pulse={pulse} />

      {focusText && (
        <div className="focus-chip">
          <span className="focus-chip-label">focused on</span>
          <span className="focus-chip-text">
            {focusText.length > 72 ? `${focusText.slice(0, 71)}…` : focusText}
          </span>
          <button
            type="button"
            className="focus-chip-clear"
            onClick={onClearFocus}
            aria-label="Clear focus"
          >
            &#10005;
          </button>
        </div>
      )}

      <div className="messages">
        {messages.length === 0 && (
          <div style={{ color: "#3a4048", fontSize: 13, lineHeight: 1.6 }}>
            {note
              ? "Capture a fragment. It becomes a pin on the map — no question asked."
              : "Type what you're thinking. Watch it become a map."}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i}>
            <div className="msg-label">
              {m.kind === "note" ? "NOTE" : m.role === "user" ? "YOU" : "SOCRAITIA"}
            </div>
            <div
              className={
                m.kind === "note"
                  ? "msg-note"
                  : m.role === "user"
                    ? "msg-user"
                    : "msg-partner"
              }
            >
              <span className={m.streaming ? "caret" : undefined}>{m.text}</span>
            </div>
            {m.role === "partner" && !m.streaming && m.text && m.exchange ? (
              <div className="feedback">
                {m.feedback ? (
                  <span className="feedback-noted">
                    noted — {m.feedback}
                  </span>
                ) : (
                  <>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onFeedback(m.exchange!, m.text, "helped")}
                    >
                      this helped
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onFeedback(m.exchange!, m.text, "missed")}
                    >
                      this missed
                    </button>
                  </>
                )}
              </div>
            ) : null}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <div className="mode-toggle">
          <button
            type="button"
            className={!note ? "on" : ""}
            disabled={busy}
            onClick={() => setMode("dialogue")}
          >
            Argument
          </button>
          <button
            type="button"
            className={note ? "on" : ""}
            disabled={busy}
            onClick={() => setMode("note")}
          >
            Quick note
          </button>
        </div>
        <textarea
          value={draft}
          placeholder={note ? "Capture a fragment…" : "Advance your argument…"}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="composer-row">
          <button
            type="button"
            className="upload-btn"
            disabled={busy}
            title="Add a PDF to the map"
            onClick={() => fileRef.current?.click()}
          >
            + document
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length) onUpload(files);
              e.target.value = "";
            }}
          />
          <span className="meta">
            {busy
              ? "agents working"
              : note
                ? "skips socratic · maps + embeds"
                : "enter to send · shift+enter newline"}
          </span>
          <button className="send" onClick={submit} disabled={busy || !draft.trim()}>
            {busy ? "…" : note ? "Pin" : "Send"}
          </button>
        </div>
      </div>
    </section>
  );
}
