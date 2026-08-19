import type {
  LoginRequest,
  ReviewDecisionCreate,
  ReviewStatus,
  Token,
  UserRead,
  WorkflowReviewSummary,
  WorkflowRunCreate,
  WorkflowRunRead,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const TOKEN_STORAGE_KEY = "prf_access_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    if (response.status === 401) clearToken();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export async function login(credentials: LoginRequest): Promise<void> {
  const token = await request<Token>("/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
  setToken(token.access_token);
}

export function getCurrentUser(): Promise<UserRead> {
  return request("/auth/me");
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

export function pdfUrl(id: string): string {
  return `${BASE_URL}/workflow/${id}/pdf`;
}
