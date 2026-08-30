"""Phase 4 loop against the public API: feedback → next-turn adapt → modeler → new session."""

from __future__ import annotations

import json
import time
import urllib.request

API = "https://socraitia-api-424012738412.us-central1.run.app"


def req(method: str, path: str, body: dict | None = None, timeout: float = 180):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(r, timeout=timeout) as res:
        raw = res.read().decode()
        return json.loads(raw) if raw else {}


def stream_turn(pid: str, sid: str, message: str) -> list[dict]:
    body = json.dumps(
        {"project_id": pid, "session_id": sid, "message": message, "mode": "dialogue"}
    ).encode()
    r = urllib.request.Request(
        API + "/api/turn",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    events = []
    with urllib.request.urlopen(r, timeout=180) as res:
        buf = ""
        while True:
            chunk = res.read(256)
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                line = next((l for l in frame.split("\n") if l.startswith("data:")), "")
                if not line:
                    continue
                events.append(json.loads(line[5:].strip()))
    return events


def show(label: str, events: list[dict]) -> str:
    q = "".join(e.get("text", "") for e in events if e.get("type") == "token")
    adapted = [
        e.get("line", "")
        for e in events
        if e.get("type") == "agent" and "adapted:" in (e.get("line") or "")
    ]
    modeler = [
        e.get("line", "")
        for e in events
        if e.get("type") == "agent" and e.get("agent") == "MODELER"
    ]
    print(f"\n== {label} ==")
    print(f"  question: {q[:220]}")
    for line in adapted:
        print(f"  {line}")
    for line in modeler:
        print(f"  {line}")
    return q


def main() -> None:
    created = req("POST", "/api/projects", {"title": "Phase 4 Learner Loop", "domain": "phase4"})
    pid = created["id"]
    boot = req("GET", f"/api/bootstrap?project_id={pid}")
    sid = boot["session_id"]
    print(f"project {pid} session {sid}")
    print(f"learner before: {boot.get('learner_model')}")

    q1 = show(
        "turn 1",
        stream_turn(
            pid,
            sid,
            "Mastery learning should be the default pacing model in every public high school.",
        ),
    )
    fb = req(
        "POST",
        "/api/feedback",
        {
            "project_id": pid,
            "session_id": sid,
            "exchange": 1,
            "question": q1,
            "verdict": "missed",
        },
    )
    print(f"  feedback: {fb.get('entry')}")

    show(
        "turn 2 (must show last feedback=missed)",
        stream_turn(
            pid,
            sid,
            "Not every school — I mean the ones that already have the staffing to support it.",
        ),
    )

    show(
        "turn 3 (modeler checkpoint)",
        stream_turn(
            pid,
            sid,
            "The real constraint is teacher time, not the theory of mastery itself.",
        ),
    )

    ended = req("POST", "/api/session/end", {"project_id": pid, "session_id": sid})
    print(f"\n== session end ==\n  {ended.get('status')} {ended.get('change')}")
    print(f"  model: {ended.get('learner_model')}")

    boot2 = req("GET", f"/api/bootstrap?project_id={pid}")
    print(f"\nnew session {boot2['session_id']} (graph nodes={len(boot2.get('nodes', []))})")
    print(f"learner loaded: {boot2.get('learner_model')}")
    show(
        "new session turn 1 (must show scaffolding adapted)",
        stream_turn(
            boot2["project_id"],
            boot2["session_id"],
            "I still think mastery learning is right, but only where teachers have time.",
        ),
    )


if __name__ == "__main__":
    main()
