/**
 * Colour is reserved exclusively for meaning.
 *
 * Nothing in this interface is coloured decoratively: a hue on screen always
 * encodes a node type or a relation type, which is why the canvas is
 * near-black and the chrome is greyscale. If a colour appears, it is data.
 */

export const NODE_COLORS: Record<string, string> = {
  claim: "#58A6FF",
  concept: "#D29922",
  question: "#3FB950",
  evidence: "#A5D6FF",
  gap: "#DB6D28",
  note: "#B1A7A0",
};

export const NODE_LABELS: Record<string, string> = {
  claim: "CLAIM",
  concept: "CONCEPT",
  question: "QUESTION",
  evidence: "EVIDENCE",
  gap: "ARGUMENT GAP",
  note: "NOTE",
};

export const RELATION_COLORS: Record<string, string> = {
  supports: "#27476B",
  contradicts: "#F85149",
  refines: "#3B5E7A",
  questions: "#2D6046",
  answers: "#5A5B2A",
  connects_to: "#7EE787",
};

/** Agent labels in the activity feed. Muted so the graph stays the protagonist. */
export const AGENT_COLORS: Record<string, string> = {
  SOCRATIC: "#8B949E",
  CARTOGRAPHER: "#58A6FF",
  VERIFIER: "#F85149",
  MODELER: "#D29922",
  INGESTION: "#3FB950",
  EMBED: "#6E7681",
  CONTEXT: "#6E7681",
  ECHO: "#7EE787",
  SYSTEM: "#6E7681",
};

export const PULSE_MS = 2600;
