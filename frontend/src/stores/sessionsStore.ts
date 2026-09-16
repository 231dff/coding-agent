import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { SessionMeta } from "@/types/session";
import { deriveTitle } from "@/types/session";

interface SessionsState {
  /** 所有会话（不含消息内容） */
  sessions: SessionMeta[];
  /** 搜索关键词 */
  searchQuery: string;

  // ---- actions ----

  /** 创建一个新会话，返回 ID */
  createSession: (firstMessage?: string) => string;

  /** 更新会话的活跃时间 */
  touchSession: (id: string, messageCount?: number) => void;

  /** 重命名 */
  renameSession: (id: string, title: string) => void;

  /** 删除 */
  deleteSession: (id: string) => void;

  /** 切换归档 */
  archiveSession: (id: string, archived: boolean) => void;

  /** 切换置顶 */
  togglePin: (id: string) => void;

  /** 设置搜索关键词 */
  setSearchQuery: (query: string) => void;

  /** 设置会话状态（running / idle / error） */
  setSessionStatus: (id: string, status: SessionMeta["status"]) => void;

  /** 清空所有（调试用） */
  clearAll: () => void;

  // ---- selectors ----

  /** 按搜索词过滤后的会话 */
  getFiltered: () => SessionMeta[];
}

export const useSessionsStore = create<SessionsState>()(
  persist(
    (set, get) => ({
      sessions: [],
      searchQuery: "",

      createSession: (firstMessage = "") => {
        const id = `sess-${Date.now().toString(36)}-${Math.random()
          .toString(36)
          .slice(2, 6)}`;
        const now = Date.now();
        const session: SessionMeta = {
          id,
          title: firstMessage ? deriveTitle(firstMessage) : "新会话",
          createdAt: now,
          updatedAt: now,
          messageCount: 0,
          status: "idle",
          archived: false,
          pinned: false,
        };
        set((state) => ({ sessions: [session, ...state.sessions] }));
        return id;
      },

      touchSession: (id, messageCount) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id
              ? {
                  ...s,
                  updatedAt: Date.now(),
                  messageCount: messageCount ?? s.messageCount,
                }
              : s
          ),
        })),

      renameSession: (id, title) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, title, updatedAt: Date.now() } : s
          ),
        })),

      deleteSession: (id) =>
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== id),
        })),

      archiveSession: (id, archived) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, archived } : s
          ),
        })),

      togglePin: (id) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, pinned: !s.pinned } : s
          ),
        })),

      setSearchQuery: (query) => set({ searchQuery: query }),

      setSessionStatus: (id, status) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, status } : s
          ),
        })),

      clearAll: () => set({ sessions: [], searchQuery: "" }),

      getFiltered: () => {
        const { sessions, searchQuery } = get();
        if (!searchQuery.trim()) return sessions;
        const q = searchQuery.toLowerCase();
        return sessions.filter(
          (s) =>
            s.title.toLowerCase().includes(q) ||
            s.id.toLowerCase().includes(q)
        );
      },
    }),
    {
      name: "coding-agent-sessions",
      partialize: (state) => ({ sessions: state.sessions }),
    }
  )
);