import type {
  Bootstrap,
  Briefing,
  Dossier,
  FeedbackVerdict,
  LearnerModel,
  ProjectMeta,
  TurnEvent,
  TurnMode,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8080";

export async function fetchBootstrap(projectId?: string): Promise<Bootstrap> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const res = await fetch(`${API_BASE}/api/bootstrap${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`bootstrap failed: ${res.status}`);
  return res.json();
}

export async function createProject(
  title: string,
  domain = "",
): Promise<ProjectMeta> {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, domain }),
  });
  if (!res.ok) throw new Error(`create project failed: ${res.status}`);
  return res.json();
}

export async function sendFeedback(body: {
  project_id: string;
  session_id: string;
  exchange: number;
  question: string;
  verdict: FeedbackVerdict;
}): Promise<{ status: string; entry: { question_type: string }; line: string }> {
  const res = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`feedback failed: ${res.status}`);
  return res.json();
}

export async function endSession(
  projectId: string,
  sessionId: string,
): Promise<{ status: string; learner_model?: LearnerModel; line?: string; change?: string }> {
  const res = await fetch(`${API_BASE}/api/session/end`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`session end failed: ${res.status}`);
  return res.json();
}

export async function uploadDocuments(
  projectId: string,
  files: File[],
): Promise<{ results: { doc_id: string; filename: string; status: string }[] }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await fetch(`${API_BASE}/api/ingest?project_id=${encodeURIComponent(projectId)}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`ingest failed: ${res.status}`);
  return res.json();
}

export async function fetchBriefing(
  projectId: string,
  full = false,
): Promise<Briefing> {
  const q = full ? "?full=true" : "";
  const res = await fetch(`${API_BASE}/api/briefing/${projectId}${q}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`briefing failed: ${res.status}`);
  return res.json();
}

export async function markBriefingSeen(projectId: string): Promise<void> {
  await fetch(`${API_BASE}/api/briefing/${projectId}/seen`, { method: "POST" });
}

export async function fetchDossier(
  projectId: string,
  nodeId: string,
): Promise<Dossier> {
  const res = await fetch(`${API_BASE}/api/node/${projectId}/${nodeId}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`dossier failed: ${res.status}`);
  return res.json();
}

export function watchProject(
  projectId: string,
  onEvent: (event: TurnEvent) => void,
): () => void {
  let src: EventSource | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (closed) return;
    src = new EventSource(`${API_BASE}/api/watch/${projectId}`);
    src.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data) as TurnEvent);
      } catch {
        /* ignore a broken frame */
      }
    };
    src.onerror = () => {
      src?.close();
      if (closed) return;
      retry = setTimeout(connect, 2500);
    };
  };
  connect();

  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    src?.close();
  };
}

export async function* streamTurn(body: {
  project_id: string;
  session_id: string;
  message: string;
  mode: TurnMode;
  focus_node_id?: string | null;
}): AsyncGenerator<TurnEvent> {
  const res = await fetch(`${API_BASE}/api/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`turn failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        yield JSON.parse(line.slice(5).trim()) as TurnEvent;
      } catch {
        // A frame we cannot parse is worth skipping, not worth killing the turn.
      }
    }
  }
}
