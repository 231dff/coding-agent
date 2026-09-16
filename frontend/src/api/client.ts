import { authFetch } from "./tokenStore";
import type {
  ApproveRequest,
  ApprovalListResponse,
  ChatRequest,
  Metrics,
  PendingApprovalListResponse,
  Session,
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { timeout?: number }
): Promise<T> {
  const { timeout = 30_000, ...rest } = init ?? {};

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const resp = await authFetch(`${API_BASE}${path}`, {
      ...rest,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...rest.headers,
      },
    });

    if (!resp.ok) {
      const detail = await resp.text().catch(() => resp.statusText);
      throw new ApiError(resp.status, detail);
    }

    if (resp.status === 204) return undefined as T;
    return (await resp.json()) as T;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(`请求超时（${timeout}ms）: ${path}`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export function listSessions(): Promise<Session[]> {
  return request<Session[]>("/api/sessions");
}

export function closeSession(sessionId: string): Promise<{ ok: boolean }> {
  return request(`/api/sessions/${sessionId}`, { method: "DELETE" });
}

export function getMetrics(sessionId: string): Promise<Metrics> {
  return request<Metrics>(
    `/api/metrics?session_id=${encodeURIComponent(sessionId)}`
  );
}

export function approveTool(
  req: ApproveRequest
): Promise<{ ok: boolean; decision: string }> {
  return request("/api/chat/approve", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function listApprovals(
  sessionId = "",
  limit = 100
): Promise<ApprovalListResponse> {
  return request<ApprovalListResponse>(
    `/api/approvals?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`
  );
}

export function listPendingApprovals(
  sessionId: string
): Promise<PendingApprovalListResponse> {
  return request<PendingApprovalListResponse>(
    `/api/approvals/pending?session_id=${encodeURIComponent(sessionId)}`
  );
}

/**
 * 流式对话。需要用 authFetch 保证 Authorization header 注入。
 */
export function chatStreamRaw(
    req: ChatRequest,
    signal?: AbortSignal
  ): Promise<Response> {
    return authFetch(`${API_BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      signal,
    });
  }