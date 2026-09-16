import { create } from "zustand";
import {
  createAssistantMessage,
  createUserMessage,
  type Message,
  type PendingApprovalInfo,
  type ToolCall,
} from "@/types/conversation";

interface SessionState {
  messages: Message[];
  isStreaming: boolean;
  error: Error | null;
  sessionId: string;

  reset: () => void;
  setSessionId: (id: string) => void;

  appendUserMessage: (content: string) => string;
  startAssistantMessage: () => string;
  appendToken: (messageId: string, token: string) => void;

  startToolCall: (messageId: string, toolCall: ToolCall) => void;
  finishToolCall: (messageId: string, toolCallId: string, output: string) => void;
  failToolCall: (messageId: string, toolCallId: string, error: string) => void;

  setPendingApproval: (messageId: string, info: PendingApprovalInfo) => void;
  clearPendingApproval: (messageId: string) => void;

  finishAssistantMessage: (messageId: string) => void;
  setError: (error: Error | null) => void;
  setStreaming: (streaming: boolean) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  messages: [],
  isStreaming: false,
  error: null,
  sessionId: "",

  // reset 只清空消息，不清空 sessionId（由 useSessions 控制）
  reset: () =>
    set({
      messages: [],
      isStreaming: false,
      error: null,
    }),

  setSessionId: (id) => set({ sessionId: id }),

  appendUserMessage: (content) => {
    const msg = createUserMessage(content);
    set((state) => ({ messages: [...state.messages, msg] }));
    return msg.id;
  },

  startAssistantMessage: () => {
    const msg = createAssistantMessage();
    set((state) => ({ messages: [...state.messages, msg] }));
    return msg.id;
  },

  appendToken: (messageId, token) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, content: m.content + token } : m
      ),
    })),

  startToolCall: (messageId, toolCall) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId
          ? { ...m, toolCalls: [...m.toolCalls, toolCall] }
          : m
      ),
    })),

  finishToolCall: (messageId, toolCallId, output) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              toolCalls: m.toolCalls.map((tc) =>
                tc.id === toolCallId
                  ? { ...tc, status: "done", output, endTime: Date.now() }
                  : tc
              ),
            }
          : m
      ),
    })),

  failToolCall: (messageId, toolCallId, error) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              toolCalls: m.toolCalls.map((tc) =>
                tc.id === toolCallId
                  ? { ...tc, status: "error", error, endTime: Date.now() }
                  : tc
              ),
            }
          : m
      ),
    })),

  setPendingApproval: (messageId, info) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, pendingApproval: info } : m
      ),
    })),

  clearPendingApproval: (messageId) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, pendingApproval: undefined } : m
      ),
    })),

  finishAssistantMessage: (messageId) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, status: "done" } : m
      ),
    })),

  setError: (error) => set({ error }),
  setStreaming: (streaming) => set({ isStreaming: streaming }),
}));