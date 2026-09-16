import { useCallback } from "react";
import { useSessionsStore } from "@/stores/sessionsStore";
import { useSessionStore } from "@/stores/sessionStore";

/**
 * 会话管理 Hook。
 *
 * 协调两个 store：
 * - sessionsStore：会话元数据列表（持久化）
 * - sessionStore：当前活跃会话的消息内容
 */
export function useSessions() {
  const sessions = useSessionsStore((s) => s.sessions);
  const searchQuery = useSessionsStore((s) => s.searchQuery);
  const setSearchQuery = useSessionsStore((s) => s.setSearchQuery);
  const createSessionMeta = useSessionsStore((s) => s.createSession);
  const renameSession = useSessionsStore((s) => s.renameSession);
  const deleteSession = useSessionsStore((s) => s.deleteSession);
  const archiveSession = useSessionsStore((s) => s.archiveSession);
  const togglePin = useSessionsStore((s) => s.togglePin);
  const setSessionStatus = useSessionsStore((s) => s.setSessionStatus);
  const touchSession = useSessionsStore((s) => s.touchSession);

  const currentSessionId = useSessionStore((s) => s.sessionId);
  const resetConversation = useSessionStore((s) => s.reset);
  const setCurrentSessionId = useSessionStore((s) => s.setSessionId);

  /**
   * 切换到指定会话。
   *
   * 当前实现：切换时清空消息（因为消息内容未持久化）。
   * 完整实现需要把每个会话的消息保存到 localStorage 或后端。
   */
  const switchSession = useCallback(
    (id: string) => {
      if (id === currentSessionId) return;

      // 保存当前会话消息到 localStorage（简化实现）
      if (currentSessionId) {
        const messages = useSessionStore.getState().messages;
        try {
          localStorage.setItem(
            `coding-agent-messages-${currentSessionId}`,
            JSON.stringify(messages)
          );
        } catch (e) {
          console.warn("保存会话消息失败:", e);
        }
      }

      // 加载目标会话消息
      resetConversation();
      setCurrentSessionId(id);

      try {
        const saved = localStorage.getItem(`coding-agent-messages-${id}`);
        if (saved) {
          const messages = JSON.parse(saved);
          useSessionStore.setState({ messages });
        }
      } catch (e) {
        console.warn("加载会话消息失败:", e);
      }
    },
    [currentSessionId, resetConversation, setCurrentSessionId]
  );

  /** 创建新会话并切换到它 */
  const createSession = useCallback(() => {
    // 先保存当前
    if (currentSessionId) {
      const messages = useSessionStore.getState().messages;
      try {
        localStorage.setItem(
          `coding-agent-messages-${currentSessionId}`,
          JSON.stringify(messages)
        );
      } catch (e) {
        console.warn("保存会话消息失败:", e);
      }
    }

    const id = createSessionMeta();
    resetConversation();
    setCurrentSessionId(id);
    return id;
  }, [currentSessionId, createSessionMeta, resetConversation, setCurrentSessionId]);

  /** 删除会话 */
  const removeSession = useCallback(
    (id: string) => {
      try {
        localStorage.removeItem(`coding-agent-messages-${id}`);
      } catch (e) {
        console.warn("清理会话消息失败:", e);
      }
      deleteSession(id);

      if (id === currentSessionId) {
        resetConversation();
        setCurrentSessionId("");
      }
    },
    [currentSessionId, deleteSession, resetConversation, setCurrentSessionId]
  );

  return {
    sessions,
    searchQuery,
    setSearchQuery,
    switchSession,
    createSession,
    removeSession,
    renameSession,
    archiveSession,
    togglePin,
    setSessionStatus,
    touchSession,
  };
}