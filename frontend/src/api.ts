import type {
  ReviewDecisionCreate,
  ReviewStatus,
  WorkflowReviewSummary,
  WorkflowRunCreate,
  WorkflowRunRead,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export function listReviews(
  status: ReviewStatus | "all",
  limit: number,
  offset: number,
): Promise<WorkflowReviewSummary[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status !== "all") params.set("status", status);
  return request(`/workflow/reviews?${params}`);
}

export function getWorkflowRun(id: string, verbose = false): Promise<WorkflowRunRead> {
  const params = verbose ? "?verbose=true" : "";
  return request(`/workflow/${id}${params}`);
}

export function submitReview(id: string, decision: ReviewDecisionCreate): Promise<WorkflowRunRead> {
  return request(`/workflow/${id}/review`, {
    method: "POST",
    body: JSON.stringify(decision),
  });
}

export function startWorkflowRun(payload: WorkflowRunCreate): Promise<WorkflowRunRead> {
  return request(`/workflow/run`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
