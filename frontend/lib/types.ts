export type NodeType =
  | "claim"
  | "concept"
  | "question"
  | "evidence"
  | "gap"
  | "note";

export type Relation =
  | "supports"
  | "contradicts"
  | "refines"
  | "questions"
  | "answers"
  | "connects_to";

export type TurnMode = "dialogue" | "note";

export interface Echo {
  node_id: string;
  text: string;
  project_id: string;
  project_title: string;
  similarity: number;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  text: string;
  source: string;
  status: string;
  session_id: string;
  degree: number;
  created_at: string;
  provenance?: string;
  echoes?: Echo[];
  /** Set client-side when a node arrives in a live diff, to drive the pulse. */
  bornAt?: number;
  x?: number;
  y?: number;
}

export interface GraphLink {
  id: string;
  source: string | GraphNode;
  target: string | GraphNode;
  relation: Relation;
  weight: number;
  created_by_agent: string;
  created_at: string;
  bornAt?: number;
  remote_project_id?: string;
  remote_project_title?: string;
  remote_text?: string;
}

export interface ProjectMeta {
  id: string;
  title: string;
  domain: string;
  created_at: string;
}

export interface LearnerModel {
  reasoning_style?: string;
  blind_spots?: string[];
  effective_question_types?: string[];
  scaffolding_level?: "low" | "medium" | "high";
  session_count?: number;
  updated_at?: string;
}

export interface Bootstrap {
  project_id: string;
  project_title: string;
  project_domain: string;
  session_id: string;
  uid: string;
  projects: ProjectMeta[];
  learner_model?: LearnerModel;
  models: { socratic: string; cartographer: string; location: string };
  nodes: GraphNode[];
  edges: GraphLink[];
}

export type TurnEvent =
  | { type: "agent"; at: string; agent: string; line: string }
  | { type: "token"; at: string; text: string }
  | { type: "graph_diff"; at: string; nodes: GraphNode[]; edges: GraphLink[] }
  | { type: "echoes"; at: string; echoes: Echo[]; nodes: GraphNode[] }
  | { type: "node_status"; at: string; nodes: GraphNode[] }
  | { type: "learner"; at: string; learner_model: LearnerModel }
  | {
      type: "done";
      at: string;
      session_id: string;
      exchange: number;
      question: string;
      mode?: TurnMode;
      elapsed_ms: number;
    }
  | { type: "error"; at: string; message: string };

export type FeedbackVerdict = "helped" | "missed";

export interface Message {
  role: "user" | "partner";
  text: string;
  streaming?: boolean;
  kind?: TurnMode;
  exchange?: number;
  feedback?: FeedbackVerdict;
}

export interface FeedLine {
  agent: string;
  line: string;
  at: string;
}

export interface Dossier {
  node: GraphNode;
  incoming: { relation: Relation; node: GraphNode }[];
  outgoing: { relation: Relation; node: GraphNode }[];
  echoes: Echo[];
}
