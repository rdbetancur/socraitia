"""Schemas.

Two families live here on purpose:

  * `GraphDiff` and friends are what the Cartographer LLM must emit. They are
    kept deliberately flat and constraint-free because they are converted into
    a Vertex response schema, and that conversion supports only a subset of
    JSON Schema. Validation strictness is enforced by Pydantic on our side
    instead, with a single retry on malformed output.
  * `NodeOut` / `EdgeOut` are what Firestore stores and the frontend renders.

The LLM refers to nodes by TEXT, never by id. Ids are derived deterministically
from text (see graph/repo.py), which is what makes node merging and Pub/Sub
idempotency fall out for free instead of needing a resolution step.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NodeType = Literal["claim", "concept", "question", "evidence", "gap", "note"]
Relation = Literal[
    "supports", "contradicts", "refines", "questions", "answers", "connects_to"
]
NodeSource = Literal["user", "verifier", "ingestion", "note"]
NodeStatus = Literal["active", "verification_pending", "verified"]
TurnMode = Literal["dialogue", "note"]


# --- Cartographer output (LLM-facing) ---------------------------------------


class ExtractedNode(BaseModel):
    type: NodeType
    text: str
    provenance: str = ""


class ExtractedEdge(BaseModel):
    from_text: str
    to_text: str
    relation: Relation


class GraphDiff(BaseModel):
    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


# --- persisted / API-facing -------------------------------------------------


class EchoOut(BaseModel):
    """A cross-project connection hanging off a local node.

    The remote node lives in another project's subgraph, so it is not rendered
    as a force-graph peer — the UI shows a badge and the dossier names the
    other project. That is enough for the demo; a merged cross-project view
    is a later surface, not a Phase 1 requirement.
    """

    node_id: str
    text: str
    project_id: str
    project_title: str
    similarity: float = 0.0


class NodeOut(BaseModel):
    id: str
    type: NodeType
    text: str
    source: NodeSource = "user"
    status: NodeStatus = "active"
    session_id: str = ""
    degree: int = 0
    created_at: str = ""
    provenance: str = ""
    echoes: list[EchoOut] = Field(default_factory=list)


class EdgeOut(BaseModel):
    """An edge in three shapes, deliberately.

    Firestore persists `from`/`to` to match the documented schema, the frontend
    consumes `source`/`target` because that is what react-force-graph expects,
    and Python uses `from_id`/`to_id` because `from` is a keyword. The mapping
    is explicit in `to_firestore` / `to_api` rather than hidden in field aliases.
    """

    id: str
    from_id: str
    to_id: str
    relation: Relation
    weight: float = 1.0
    created_by_agent: str = "cartographer"
    created_at: str = ""
    remote_project_id: str = ""
    remote_project_title: str = ""
    remote_text: str = ""

    def to_firestore(self) -> dict:
        payload = {
            "from": self.from_id,
            "to": self.to_id,
            "relation": self.relation,
            "weight": self.weight,
            "created_by_agent": self.created_by_agent,
            "created_at": self.created_at,
        }
        if self.remote_project_id:
            payload["remote_project_id"] = self.remote_project_id
            payload["remote_project_title"] = self.remote_project_title
            payload["remote_text"] = self.remote_text
        return payload

    def to_api(self) -> dict:
        payload = {
            "id": self.id,
            "source": self.from_id,
            "target": self.to_id,
            "relation": self.relation,
            "weight": self.weight,
            "created_by_agent": self.created_by_agent,
            "created_at": self.created_at,
        }
        if self.remote_project_id:
            payload["remote_project_id"] = self.remote_project_id
            payload["remote_project_title"] = self.remote_project_title
            payload["remote_text"] = self.remote_text
        return payload


class AppliedDiff(BaseModel):
    """What actually changed in Firestore, as opposed to what the LLM proposed."""

    new_nodes: list[NodeOut] = Field(default_factory=list)
    merged_node_ids: list[str] = Field(default_factory=list)
    new_edges: list[EdgeOut] = Field(default_factory=list)
    dropped_edges: int = 0

    def summary(self) -> str:
        """The `+3 nodes (2 claim, 1 gap), +2 edges` half of a Cartographer log line."""
        if not self.new_nodes and not self.new_edges:
            return f"no new structure ({len(self.merged_node_ids)} merged into existing)"
        counts: dict[str, int] = {}
        for n in self.new_nodes:
            counts[n.type] = counts.get(n.type, 0) + 1
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        parts = [f"+{len(self.new_nodes)} nodes ({breakdown})" if self.new_nodes else "+0 nodes"]
        parts.append(f"+{len(self.new_edges)} edges")
        if self.merged_node_ids:
            parts.append(f"{len(self.merged_node_ids)} merged")
        if self.dropped_edges:
            parts.append(f"{self.dropped_edges} edges dropped (unresolved endpoint)")
        return ", ".join(parts)


class TurnRequest(BaseModel):
    project_id: str
    session_id: str | None = None
    message: str
    mode: TurnMode = "dialogue"
    focus_node_id: str | None = None


class ProjectCreate(BaseModel):
    title: str
    domain: str = ""


ScaffoldingLevel = Literal["low", "medium", "high"]
FeedbackVerdict = Literal["helped", "missed"]


class LearnerModel(BaseModel):
    """Structured Modeler output. Vertex-enforced via ADK output_schema."""

    reasoning_style: str = ""
    blind_spots: list[str] = Field(default_factory=list)
    effective_question_types: list[str] = Field(default_factory=list)
    scaffolding_level: ScaffoldingLevel = "medium"


class FeedbackRequest(BaseModel):
    project_id: str
    session_id: str
    exchange: int
    question: str
    verdict: FeedbackVerdict


class SessionEndRequest(BaseModel):
    project_id: str
    session_id: str
