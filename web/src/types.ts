// Mirrors src/triage/card/schema.py, which is the single source of truth.
// When the card schema changes, this file changes in the same commit.

export const TAXONOMY = [
  "code_error",
  "config_error",
  "upstream_data",
  "resource_exhaustion",
  "dependency_error",
  "external_service",
  "platform_error",
] as const;

export type RootCauseCategory = (typeof TAXONOMY)[number];

export interface Citation {
  source: string;
  chunk_id: string;
  quote: string;
}

export interface EvidenceStep {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  result_digest: string;
  chunk_ids: string[];
  error: string | null;
  latency_ms: number | null;
}

export interface RunMetadata {
  model: string;
  mode: string;
  steps_used: number;
  max_steps: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  config_fingerprint: Record<string, unknown>;
  created_at: string;
}

export interface TriageCard {
  schema_version: string;
  incident: { dag_id: string; task_id: string; run_id: string; try_number: number };
  root_cause: { category: RootCauseCategory; hypothesis: string; confidence: number };
  suggested_fix: string;
  citations: Citation[];
  evidence_trail: EvidenceStep[];
  security_flags: string[];
  insufficient_evidence: boolean;
  parse_error: string | null;
  run: RunMetadata;
}

/** The list-view projection: enough to render a row, no incident content. */
export interface CardSummary {
  card_id: string;
  created_at: string;
  incident: string;
  dag_id: string;
  task_id: string;
  category: RootCauseCategory;
  confidence: number;
  hypothesis: string;
  security_flags: string[];
  insufficient_evidence: boolean;
  parse_error: boolean;
  citations: number;
  steps_used: number;
  latency_ms: number;
  cost_usd: number;
  model: string;
}

export interface CardDetail {
  card_id: string;
  created_at: string;
  card: TriageCard;
}

export interface GateCheck {
  metric: string;
  bound: number;
  kind: "min" | "max";
  value: number | null;
  passed: boolean;
  skipped: boolean;
}

export interface EvalReport {
  available: boolean;
  created_at?: string;
  config_fingerprint?: Record<string, unknown>;
  metrics?: Record<string, number | null>;
  gate?: { enforced: boolean; passed: boolean; reason: string; checks: GateCheck[] };
  cases?: { case_id: string; expected: string; predicted: string; correct: boolean }[];
}

export interface FeedbackRequest {
  verdict: "up" | "down";
  root_cause?: string;
  expected_fix?: string;
  notes?: string;
}
