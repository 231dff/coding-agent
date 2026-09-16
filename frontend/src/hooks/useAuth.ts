import { create } from "zustand";
import { fetchAuthConfig, fetchMe } from "@/api/auth";
import { tokenStore } from "@/lib/tokenStore";
import type { AuthConfig, User } from "@/types/auth";

interface AuthState {
  config: AuthConfig | null;
  user: User | null;
  initialized: boolean;
  loading: boolean;
  error: Error | null;

  initialize: () => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

/** disabled 模式下直接构造的匿名 admin 用户 */
const ANONYMOUS_ADMIN: User = {
  id: "anonymous",
  name: "Anonymous",
  email: "",
  roles: ["admin"],
  picture: "",
};

export const useAuthStore = create<AuthState>((set, get) => ({
  config: null,
  user: null,
  initialized: false,
  loading: false,
  error: null,

  initialize: async () => {
    if (get().initialized) return;

    set({ loading: true, error: null });

    try {
      const config = await fetchAuthConfig();
      set({ config });

      // ========================================
      // 关键修复：disabled 模式直接给 admin 用户
      // 不再依赖 /api/auth/me（避免 header / token 问题）
      // ========================================
      if (config.mode === "disabled") {
        set({
          user: ANONYMOUS_ADMIN,
          initialized: true,
          loading: false,
        });
        return;
      }

      // 有 token 时验证
      const token = tokenStore.get();
      if (token) {
        try {
          const user = await fetchMe(token);
          set({ user });
        } catch {
          tokenStore.clear();
          set({ user: null });
        }
      }

      // 无 token 且允许匿名：尝试拉取匿名用户
      if (!get().user && !config.require_auth) {
        try {
          const user = await fetchMe("");
          set({ user });
        } catch (e) {
          console.warn("[auth] 匿名用户拉取失败:", e);
        }
      }

      set({ initialized: true, loading: false });
    } catch (e) {
      set({
        error: e instanceof Error ? e : new Error(String(e)),
        initialized: true,
        loading: false,
      });
    }
  },

  loginWithToken: async (token: string) => {
    set({ loading: true, error: null });
    try {
      const user = await fetchMe(token);
      tokenStore.set(token);
      set({ user, loading: false });
    } catch (e) {
      tokenStore.clear();
      set({
        error: e instanceof Error ? e : new Error(String(e)),
        loading: false,
      });
      throw e;
    }
  },

  logout: () => {
    tokenStore.clear();
    set({ user: null });
  },

  refreshUser: async () => {
    const config = get().config;
    if (config?.mode === "disabled") {
      set({ user: ANONYMOUS_ADMIN });
      return;
    }
    const token = tokenStore.get();
    try {
      const user = await fetchMe(token);
      set({ user });
    } catch {
      tokenStore.clear();
      set({ user: null });
    }
  },
}));

export function useAuth() {
  const config = useAuthStore((s) => s.config);
  const user = useAuthStore((s) => s.user);
  const initialized = useAuthStore((s) => s.initialized);
  const loading = useAuthStore((s) => s.loading);
  const error = useAuthStore((s) => s.error);
  const initialize = useAuthStore((s) => s.initialize);
  const loginWithToken = useAuthStore((s) => s.loginWithToken);
  const logout = useAuthStore((s) => s.logout);
  const refreshUser = useAuthStore((s) => s.refreshUser);

  return {
    config,
    user,
    initialized,
    loading,
    error,
    initialize,
    loginWithToken,
    logout,
    refreshUser,
  };
}