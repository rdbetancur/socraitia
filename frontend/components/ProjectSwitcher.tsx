"use client";

import { useState } from "react";

import type { ProjectMeta } from "@/lib/types";

interface Props {
  currentId: string;
  projects: ProjectMeta[];
  disabled?: boolean;
  onSwitch: (projectId: string) => void;
  onCreate: (title: string, domain: string) => Promise<void>;
}

export default function ProjectSwitcher({
  currentId,
  projects,
  disabled,
  onSwitch,
  onCreate,
}: Props) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("");
  const [saving, setSaving] = useState(false);

  const current = projects.find((p) => p.id === currentId);

  async function submitNew() {
    const t = title.trim();
    if (!t || saving) return;
    setSaving(true);
    try {
      await onCreate(t, domain.trim());
      setTitle("");
      setDomain("");
      setCreating(false);
      setOpen(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="switcher">
      <button
        type="button"
        className="switcher-trigger"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="kv">
          project <b>{current?.title ?? currentId}</b>
        </span>
        <span className="switcher-caret">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div className="switcher-panel">
          {projects.map((p) => (
            <button
              type="button"
              key={p.id}
              className={`switcher-item ${p.id === currentId ? "active" : ""}`}
              onClick={() => {
                setOpen(false);
                if (p.id !== currentId) onSwitch(p.id);
              }}
            >
              <span>{p.title}</span>
              {p.domain && <span className="switcher-domain">{p.domain}</span>}
            </button>
          ))}

          {creating ? (
            <div className="switcher-form">
              <input
                autoFocus
                placeholder="Project name"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submitNew();
                  }
                }}
              />
              <input
                placeholder="Domain (optional)"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              />
              <div className="switcher-form-row">
                <button type="button" className="send" onClick={() => setCreating(false)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="send"
                  disabled={!title.trim() || saving}
                  onClick={submitNew}
                >
                  {saving ? "…" : "Create"}
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="switcher-item new"
              onClick={() => setCreating(true)}
            >
              + New project
            </button>
          )}
        </div>
      )}
    </div>
  );
}
