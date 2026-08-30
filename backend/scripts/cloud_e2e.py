"""Cloud Run Phase 2+3 E2E: turn + verifier + idempotency.

Uses a throwaway project so the demo graph is not the test fixture.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request

API = "https://socraitia-api-424012738412.us-central1.run.app"
TOKEN = "socraitia-push-2026"


def _req(method: str, path: str, body: dict | None = None, timeout: float = 120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode())


def stream_turn(project_id: str, session_id: str, message: str, mode: str = "dialogue"):
    body = json.dumps(
        {
            "project_id": project_id,
            "session_id": session_id,
            "message": message,
            "mode": mode,
        }
    ).encode()
    req = urllib.request.Request(
        API + "/api/turn",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    events = []
    started = time.time()
    with urllib.request.urlopen(req, timeout=180) as res:
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
                ev = json.loads(line[5:].strip())
                events.append(ev)
                kind = ev.get("type")
                extra = ev.get("line") or ev.get("text", "")[:80] or ev.get("message", "")
                print(f"  [{kind}] {extra}", flush=True)
    print(f"  turn elapsed {time.time() - started:.1f}s, {len(events)} events")
    return events


def wait_verified(project_id: str, before_ids: set[str], timeout: float = 90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        graph = _req("GET", f"/api/graph/{project_id}")
        claims = [n for n in graph["nodes"] if n["type"] == "claim" and n["id"] not in before_ids]
        evidence = [n for n in graph["nodes"] if n["type"] == "evidence"]
        tensions = [e for e in graph["edges"] if e["relation"] == "contradicts"]
        pending = [n for n in claims if n.get("status") == "verification_pending"]
        verified = [n for n in claims if n.get("status") == "verified"]
        print(
            f"  poll claims={len(claims)} pending={len(pending)} verified={len(verified)} "
            f"evidence={len(evidence)} tensions={len(tensions)}",
            flush=True,
        )
        if claims and not pending:
            return graph, time.time()
        time.sleep(4)
    return _req("GET", f"/api/graph/{project_id}"), None


def push_twice(project_id: str, node_id: str, text: str):
    payload = {
        "project_id": project_id,
        "node_id": node_id,
        "text": text,
        "user_id": "demo-researcher",
    }
    envelope = {
        "message": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}
    }
    a = _req("POST", f"/internal/pubsub/claims?token={TOKEN}", envelope, timeout=90)
    b = _req("POST", f"/internal/pubsub/claims?token={TOKEN}", envelope, timeout=90)
    return a, b


def main() -> int:
    created = _req(
        "POST",
        "/api/projects",
        {"title": "Phase 2 Cloud E2E", "domain": "deploy verification"},
    )
    pid = created["id"]
    print(f"project {pid}", flush=True)
    boot = _req("GET", f"/api/bootstrap?project_id={pid}")
    sid = boot["session_id"]
    before = {n["id"] for n in boot["nodes"]}

    print("\n== turn 1 (search-groundable claim) ==", flush=True)
    t0 = time.time()
    ev1 = stream_turn(
        pid,
        sid,
        "Intelligent tutoring systems produce about a one-standard-deviation "
        "learning gain over conventional classroom instruction.",
    )
    turn1_s = time.time() - t0

    print("\n== turn 2 (opposing claim, same project) ==", flush=True)
    ev2 = stream_turn(
        pid,
        sid,
        "Classroom lecture with periodic quizzes outperforms one-to-one intelligent "
        "tutoring for long-term retention.",
    )

    queued = any(
        e.get("type") == "agent" and "VERIFIER:async" in e.get("agent", "")
        for e in ev1 + ev2
    )
    print(f"\nverifier queued in turn stream: {queued}")
    print(f"turn 1 wall {turn1_s:.1f}s")

    print("\n== wait for async verification ==", flush=True)
    wait_started = time.time()
    graph, done_at = wait_verified(pid, before, timeout=120)
    latency = None if done_at is None else done_at - wait_started
    claims = [n for n in graph["nodes"] if n["type"] == "claim"]
    evidence = [n for n in graph["nodes"] if n["type"] == "evidence"]
    tensions = [e for e in graph["edges"] if e["relation"] == "contradicts"]
    print(f"async visible after {latency}s" if latency else "STILL PENDING after 120s")
    print(f"claims={[ (n['id'], n['status']) for n in claims ]}")
    print(f"evidence={len(evidence)} tensions={len(tensions)}")
    for n in evidence:
        print(f"  evidence: {n['text'][:160]}")

    print("\n== idempotency (same push twice) ==", flush=True)
    if claims:
        c = claims[0]
        before_n = len(graph["nodes"])
        before_e = len(graph["edges"])
        a, b = push_twice(pid, c["id"], c["text"])
        after = _req("GET", f"/api/graph/{pid}")
        print("first", a)
        print("second", b)
        print(
            f"nodes {before_n} -> {len(after['nodes'])}, "
            f"edges {before_e} -> {len(after['edges'])}"
        )
        if b.get("status") != "duplicate":
            print("WARN: second push was not duplicate", file=sys.stderr)
            return 2
        if len(after["nodes"]) != before_n:
            print("WARN: redelivery created nodes", file=sys.stderr)
            return 3
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
