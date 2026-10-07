import type {
  AgentApprovalDecision,
  AgentRunCreate,
  AgentRunDetail,
  AgentRunRead,
  CampaignRead,
  CampaignSummary,
  DonorIngestResult,
  DonorUnrunRead,
  HeldLetterDecision,
  LoginRequest,
  ReviewDecisionCreate,
  ReviewStatus,
  RunStatus,
  Token,
  UserRead,
  WorkflowRunSummary,
  WorkflowRunBatchItem,
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
): Promise<WorkflowRunSummary[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status !== "all") params.set("status", status);
  return request(`/workflow/reviews?${params}`);
}

export function listRuns(
  status: RunStatus | "all",
  limit: number,
  offset: number,
): Promise<WorkflowRunSummary[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status !== "all") params.set("status", status);
  return request(`/workflow/runs?${params}`);
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

export function decideHeldLetter(id: string, decision: HeldLetterDecision): Promise<WorkflowRunRead> {
  return request(`/workflow/${id}/release`, {
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

export async function ingestDonorsCsv(file: File, campaignId?: string): Promise<DonorIngestResult> {
  const token = getToken();
  const formData = new FormData();
  formData.append("file", file);
  // No Content-Type header here -- the browser sets it (with the multipart
  // boundary) itself; forcing application/json like request() does would
  // break the upload.
  const query = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : "";
  const response = await fetch(`${BASE_URL}/donors/ingest${query}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (!response.ok) {
    const body = await response.text();
    if (response.status === 401) clearToken();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<DonorIngestResult>;
}

export function listUnrunDonors(): Promise<DonorUnrunRead[]> {
  return request("/donors/unrun");
}

export function startWorkflowRunBatch(donorIds: string[]): Promise<WorkflowRunBatchItem[]> {
  return request("/workflow/run/batch", {
    method: "POST",
    body: JSON.stringify({ donor_ids: donorIds }),
  });
}

export async function fetchWorkflowPdf(id: string): Promise<Blob> {
  const token = getToken();
  const response = await fetch(`${BASE_URL}/workflow/${id}/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    if (response.status === 401) clearToken();
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.blob();
}

export function listCampaigns(): Promise<CampaignRead[]> {
  return request("/campaigns");
}

export function createCampaign(name: string, appealCode?: string): Promise<CampaignRead> {
  return request("/campaigns", {
    method: "POST",
    body: JSON.stringify({ name, appeal_code: appealCode || null }),
  });
}

export function getCampaign(id: string): Promise<CampaignSummary> {
  return request(`/campaigns/${id}`);
}

export function listAgentRuns(campaignId: string): Promise<AgentRunRead[]> {
  return request(`/campaigns/${campaignId}/agent-runs`);
}

export function startAgentRun(campaignId: string, payload: AgentRunCreate): Promise<AgentRunRead> {
  return request(`/campaigns/${campaignId}/agent/run`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAgentRun(id: string): Promise<AgentRunDetail> {
  return request(`/agent-runs/${id}`);
}

export function decideAgentApproval(id: string, decision: AgentApprovalDecision): Promise<AgentRunRead> {
  return request(`/agent-runs/${id}/approval`, {
    method: "POST",
    body: JSON.stringify(decision),
  });
}
