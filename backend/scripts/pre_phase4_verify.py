"""Pre-Phase-4 check: delayed contradiction outside the last-6 window.

Hits the public Cloud Run API on project `ai-in-education`. Does not change
application code. Prints enough for a human report: who wrote the
`contradicts` edge (Cartographer same-turn vs Verifier async), latency, and
whether the next Socratic question surfaces the tension.
"""

from __future__ import annotations

import json
import time
import urllib.request

API = "https://socraitia-api-424012738412.us-central1.run.app"
PROJECT = "ai-in-education"
TARGET = "Los tutores de IA reemplazarán a los profesores humanos en un plazo de cinco años"

FILLERS = [
    "City libraries should stay open until midnight on weekdays because late hours are when working students actually study.",
    "Sourdough fermentation produces a more digestible loaf than commercial yeast because the long rise breaks down gluten proteins.",
    "Protected bike lanes increase cycling rates more than helmet-mandate campaigns because perceived safety, not equipment, is the binding constraint.",
    "Jazz improvisation is taught better through transcription than through scale drills, because the ear learns vocabulary in context.",
    "Climate communication that leads with local flood risk outperforms abstract global-temperature charts for moving municipal policy.",
]

CONTRADICTION = (
    "Los tutores de IA no van a reemplazar a los profesores humanos en un plazo "
    "de cinco años; los docentes seguirán siendo los instructores principales."
)

FOLLOW = (
    "Eso no niega que la IA tenga un rol en el aula; niega solo el plazo de "
    "cinco años como reemplazo."
)


def get(path: str, timeout: float = 60) -> dict:
    with urllib.request.urlopen(API + path, timeout=timeout) as res:
        return json.loads(res.read().decode())


def stream_turn(session_id: str, message: str) -> list[dict]:
    body = json.dumps(
        {
            "project_id": PROJECT,
            "session_id": session_id,
            "message": message,
            "mode": "dialogue",
        }
    ).encode()
    req = urllib.request.Request(
        API + "/api/turn",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    events: list[dict] = []
    t0 = time.time()
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
    events.append({"type": "_wall", "elapsed": time.time() - t0})
    return events


def summarize_turn(label: str, events: list[dict]) -> None:
    wall = next((e["elapsed"] for e in events if e.get("type") == "_wall"), 0)
    question = "".join(e.get("text", "") for e in events if e.get("type") == "token")
    carto = [e.get("line", "") for e in events if e.get("type") == "agent" and "CARTOGRAPHER" in e.get("agent", "")]
    ver = [e.get("line", "") for e in events if e.get("type") == "agent" and "VERIFIER" in e.get("agent", "")]
    diffs = [e for e in events if e.get("type") == "graph_diff"]
    new_nodes = [n for d in diffs for n in d.get("nodes", [])]
    new_edges = [e for d in diffs for e in d.get("edges", [])]
    print(f"\n== {label} ({wall:.1f}s) ==")
    print(f"  socratic: {question[:240]}")
    for line in carto:
        print(f"  {line}")
    for line in ver:
        print(f"  {line}")
    for n in new_nodes:
        print(f"  +node {n.get('type')} {n.get('id')} {n.get('text', '')[:90]}")
    for e in new_edges:
        print(f"  +edge {e.get('relation')} agent={e.get('created_by_agent')} {e.get('source')} -> {e.get('target')}")


def edge_key(e: dict) -> tuple:
    return (e.get("id"), e.get("relation"), e.get("source"), e.get("target"), e.get("created_by_agent"))


def main() -> None:
    boot = get(f"/api/bootstrap?project_id={PROJECT}")
    sid = boot["session_id"]
    before_edges = {edge_key(e) for e in boot["edges"]}
    print(f"session {sid}")
    print(f"graph before: {len(boot['nodes'])} nodes / {len(boot['edges'])} edges")
    print(f"target prior claim: {TARGET}")

    for i, msg in enumerate(FILLERS, 1):
        ev = stream_turn(sid, msg)
        summarize_turn(f"filler {i}", ev)

    graph_mid = get(f"/api/graph/{PROJECT}")
    mid_edges = {edge_key(e) for e in graph_mid["edges"]}
    print(f"\n-- after fillers: {len(graph_mid['nodes'])} nodes / {len(graph_mid['edges'])} edges --")

    t_claim = time.time()
    ev_c = stream_turn(sid, CONTRADICTION)
    summarize_turn("CONTRADICTION", ev_c)
    carto_contradicts = [
        e
        for d in ev_c
        if d.get("type") == "graph_diff"
        for e in d.get("edges", [])
        if e.get("relation") == "contradicts"
    ]
    print(f"  cartographer same-turn contradicts: {len(carto_contradicts)}")

    print("\n== poll verifier ==")
    verifier_line = None
    new_verifier_edge = None
    visible_at = None
    for i in range(30):
        g = get(f"/api/graph/{PROJECT}")
        fresh = [e for e in g["edges"] if edge_key(e) not in mid_edges]
        v_contra = [
            e
            for e in fresh
            if e.get("relation") == "contradicts" and e.get("created_by_agent") == "verifier"
        ]
        pending = [n for n in g["nodes"] if n.get("status") == "verification_pending"]
        print(
            f"  +{i*3:02d}s pending={len(pending)} fresh_edges={len(fresh)} "
            f"verifier_contradicts={len(v_contra)}",
            flush=True,
        )
        if v_contra and visible_at is None:
            new_verifier_edge = v_contra
            visible_at = time.time()
        # also treat a verifier feed line as the signal
        if visible_at is None and not pending:
            # claim stamped verified — capture feed via a second contradiction poll window
            visible_at = visible_at or time.time()
            break
        if not pending and v_contra:
            break
        time.sleep(3)

    latency = None if visible_at is None else visible_at - t_claim
    print(f"\nclaim→visible latency: {latency:.1f}s" if latency else "\nclaim→visible: timeout")
    print(f"verifier-authored contradicts after fillers: {new_verifier_edge}")

    g = get(f"/api/graph/{PROJECT}")
    print("\nall contradicts now:")
    id_to_text = {n["id"]: n["text"][:80] for n in g["nodes"]}
    for e in g["edges"]:
        if e.get("relation") != "contradicts":
            continue
        print(
            f"  agent={e.get('created_by_agent')} "
            f"{id_to_text.get(e.get('source'), e.get('source'))} "
            f"|| {id_to_text.get(e.get('target'), e.get('target'))}"
        )

    ev_n = stream_turn(sid, FOLLOW)
    summarize_turn("NEXT (socratic should see tension)", ev_n)


if __name__ == "__main__":
    main()
