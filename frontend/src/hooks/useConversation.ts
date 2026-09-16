import { useCallback, useRef } from "react";
import { useAgentStream } from "./useAgentStream";
import { useSessionStore } from "@/stores/sessionStore";
import { useSessionsStore } from "@/stores/sessionsStore";
import { useNotificationStore } from "@/stores/notificationStore";
import type { StreamEvent } from "@/api/types";
import i18n from "@/i18n";

export function useConversation() {
  const messages = useSessionStore((s) => s.messages);
  const isStreaming = useSessionStore((s) => s.isStreaming);
  const error = useSessionStore((s) => s.error);

  const currentAssistantIdRef = useRef<string | null>(null);

  const handleEvent = useCallback((event: StreamEvent) => {
    const store = useSessionStore.getState();
    const notify = useNotificationStore.getState();
    const mid = currentAssistantIdRef.current;

    switch (event.type) {
      case "token": {
        if (!mid) return;
        store.appendToken(mid, event.content);
        break;
      }

      case "tool_start": {
        if (!mid) return;
        store.startToolCall(mid, {
          id: event.tool_call_id,
          name: event.tool_name,
          args: event.args,
          status: "running",
          startTime: event.timestamp * 1000,
        });
        break;
      }

      case "tool_end": {
        if (!mid) return;
        store.finishToolCall(mid, event.tool_call_id, event.output);
        break;
      }

      case "approval_required": {
        if (!mid) return;
        store.setPendingApproval(mid, {
          approvalId: event.approval_id,
          toolCallId: event.tool_call_id,
          toolName: event.tool_name,
          args: event.args,
          reason: event.reason,
          threadId: event.thread_id,
          checkpointId: event.checkpoint_id,
          createdAt: event.timestamp * 1000,
        });
        store.startToolCall(mid, {
          id: event.tool_call_id,
          name: event.tool_name,
          args: event.args,
          status: "pending_approval",
          startTime: event.timestamp * 1000,
        });

        // 通知：需要审批
        notify.push("warning", i18n.t("notifications.approvalRequired"), {
          description: i18n.t("notifications.approvalRequiredDesc", {
            tool: event.tool_name,
          }),
          duration: 8000,
        });
        break;
      }

      case "error": {
        if (event.source === "tool" && event.tool_name) {
          if (mid) {
            const msg = store.messages.find((m) => m.id === mid);
            const lastRunning = msg?.toolCalls
              .filter(
                (tc) =>
                  tc.name === event.tool_name &&
                  (tc.status === "running" ||
                    tc.status === "pending_approval")
              )
              .pop();
            if (lastRunning) {
              store.failToolCall(mid, lastRunning.id, event.message);
            }
          }
          notify.error(i18n.t("notifications.taskFailed"), event.message);
        } else {
          store.setError(new Error(event.message));
          if (mid) store.finishAssistantMessage(mid);
          notify.error(
            i18n.t("notifications.taskFailed"),
            event.message
          );
        }
        break;
      }

      case "done": {
        if (mid) {
          const wasStreaming = store.messages.find((m) => m.id === mid);
          store.finishAssistantMessage(mid);
          currentAssistantIdRef.current = null;

          // 更新会话状态
          const sessionsStore = useSessionsStore.getState();
          const sid = store.sessionId;
          if (sid) {
            sessionsStore.setSessionStatus(sid, "idle");
            sessionsStore.touchSession(sid, store.messages.length);
          }

          // 任务完成通知：只在有实质内容时弹
          const hasContent =
            wasStreaming &&
            (wasStreaming.content.length > 0 ||
              wasStreaming.toolCalls.length > 0);
          if (hasContent) {
            notify.success(i18n.t("notifications.taskCompleted"));
          }
        }
        break;
      }
    }
  }, []);

  const stream = useAgentStream({
    onEvent: handleEvent,
    onError: (err) => {
      const store = useSessionStore.getState();
      const notify = useNotificationStore.getState();
      store.setError(err);
      if (currentAssistantIdRef.current) {
        store.finishAssistantMessage(currentAssistantIdRef.current);
        currentAssistantIdRef.current = null;
      }
      notify.error(i18n.t("notifications.networkError"), err.message);

      const sid = store.sessionId;
      if (sid) {
        useSessionsStore.getState().setSessionStatus(sid, "error");
      }
    },
  });

  const send = useCallback(
    (content: string) => {
      const store = useSessionStore.getState();
      const sessionsStore = useSessionsStore.getState();

      store.setError(null);
      store.appendUserMessage(content);

      let sid = store.sessionId;
      if (!sid) {
        sid = sessionsStore.createSession(content);
        store.setSessionId(sid);
      } else {
        const meta = sessionsStore.sessions.find((s) => s.id === sid);
        if (meta && meta.title === "新会话") {
          sessionsStore.renameSession(sid, content.slice(0, 30));
        }
        sessionsStore.setSessionStatus(sid, "running");
        sessionsStore.touchSession(sid);
      }

      const assistantId = store.startAssistantMessage();
      currentAssistantIdRef.current = assistantId;

      void stream.send(content, sid);
    },
    [stream]
  );

  const reset = useCallback(() => {
    currentAssistantIdRef.current = null;
    useSessionStore.getState().reset();
  }, []);

  return {
    messages,
    isStreaming,
    error,
    send,
    abort: stream.abort,
    reset,
  };
}