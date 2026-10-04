// Mirrors backend/src/app/schemas/workflow.py. Decimal fields (confidence)
// serialize as JSON strings, not numbers -- Pydantic's default for Decimal.

export type ReviewStatus = "awaiting_review" | "needs_review";
export type RunStatus = "pending" | "running" | "awaiting_review" | "completed" | "needs_review" | "failed" | "discarded";

export interface WorkflowRunSummary {
  id: string;
  donor_id: string;
  donor_name: string;
  donor_external_id: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  status: string;
  current_agent: string | null;
  confidence: string | null;
  pending_review: PendingReview | null;
  created_at: string;
}

export interface PendingReview {
  reason: string;
  stage: "address" | "recommendation" | "compliance";
  under_review: Record<string, unknown>;
  donor_profile: Record<string, unknown> | null;
}

export interface ReviewHistoryEntry {
  stage: string | null;
  action: string | null;
  reviewer: string | null;
  notes: string | null;
  created_at: string;
}

export interface AuditLogEntry {
  step: string;
  output: Record<string, unknown> | null;
  confidence: string | null;
  reasoning: string | null;
  source_refs: unknown[] | null;
  tool_calls: unknown[] | null;
  model: string | null;
  latency_ms: number | null;
  created_at: string;
}

export interface WorkflowRunRead {
  id: string;
  donor_id: string;
  donor_external_id: string | null;
  campaign_id: string | null;
  status: string;
  current_agent: string | null;
  result: Record<string, unknown> | null;
  confidence: string | null;
  pending_review: PendingReview | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  audit_log: AuditLogEntry[];
  review_history: ReviewHistoryEntry[];
}

export interface ReviewDecisionCreate {
  action: "approve" | "reject" | "modify";
  // Binds the decision to the pause it was made for; the API refuses a mismatch.
  stage: "address" | "recommendation" | "compliance";
  updated_address?: string;
  updated_ask_amount?: number;
  reviewer?: string;
  notes?: string;
}

export interface HeldLetterDecision {
  action: "release" | "discard";
  notes: string;
}

export interface WorkflowRunCreate {
  donor_id: string;
  campaign_id?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface Token {
  access_token: string;
  token_type: string;
}

export interface UserRead {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "reviewer";
  is_active: boolean;
  created_at: string;
}

export interface DonorIngestRowError {
  row_number: number;
  reason: string;
  external_id: string | null;
}

export interface DonorIngestResult {
  import_id: string;
  filename: string;
  rows_inserted: number;
  rows_updated: number;
  rows_rejected: number;
  rejected: DonorIngestRowError[];
}

export interface DonorUnrunRead {
  id: string;
  external_id: string | null;
  first_name: string;
  last_name: string;
  city: string | null;
  state: string | null;
  created_at: string;
}

export interface WorkflowRunBatchItem {
  donor_id: string;
  status: "enqueued" | "error";
  workflow_run_id: string | null;
  error: string | null;
}
