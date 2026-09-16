import type { AuthConfig, User } from "@/types/auth";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const resp = await fetch(`${API_BASE}/api/auth/config`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  return resp.json();
}

/**
 * 拉取当前用户信息。
 *
 * token 为空时不发 Authorization header，后端会根据 AUTH_MODE
 * 返回匿名用户（disabled → admin，mock + 无 creds → viewer）。
 */
export async function fetchMe(token: string): Promise<User> {
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const resp = await fetch(`${API_BASE}/api/auth/me`, { headers });

  if (!resp.ok) {
    if (resp.status === 401) throw new Error("未认证");
    if (resp.status === 403) throw new Error("无权限");
    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  }
  return resp.json();
}