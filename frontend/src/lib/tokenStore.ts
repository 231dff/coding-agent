/**
 * Token 存储。集中管理 access token 的读写。
 *
 * 生产环境应改为 httpOnly cookie（由后端设置），
 * 避免 XSS 窃取。这里用 localStorage 是为了开发便利。
 */

const TOKEN_KEY = "coding-agent-token";

export const tokenStore = {
  get(): string {
    try {
      return localStorage.getItem(TOKEN_KEY) ?? "";
    } catch {
      return "";
    }
  },

  set(token: string): void {
    try {
      if (token) {
        localStorage.setItem(TOKEN_KEY, token);
      } else {
        localStorage.removeItem(TOKEN_KEY);
      }
    } catch (e) {
      console.warn("Token 存储失败:", e);
    }
  },

  clear(): void {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      // ignore
    }
  },
};

/**
 * 全局 fetch 包装。自动注入 Authorization header。
 */
export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  const token = tokenStore.get();
  const headers = new Headers(init?.headers);

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(input, { ...init, headers });
}