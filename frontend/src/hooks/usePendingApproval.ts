import { useCallback, useState } from "react";
import { approveTool } from "@/api/client";
import { useSessionStore } from "@/stores/sessionStore";

interface PendingApprovalHookResult {
  isSubmitting: boolean;
  error: Error | null;
  decide: (
    messageId: string,
    approvalId: string,
    decision: "approve" | "reject" | "edit",
    editedArgs?: Record<string, unknown>
  ) => Promise<void>;
}

/**
 * 处理待审批请求的 Hook。
 *
 * 职责：
 * 1. 调用后端 /api/chat/approve
 * 2. 成功后清除消息上的 pendingApproval
 * 3. 管理提交状态和错误
 */
export function usePendingApproval(): PendingApprovalHookResult {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const decide = useCallback(
    async (
      messageId: string,
      approvalId: string,
      decision: "approve" | "reject" | "edit",
      editedArgs?: Record<string, unknown>
    ) => {
      setIsSubmitting(true);
      setError(null);

      const store = useSessionStore.getState();
      const sessionId = store.sessionId;

      try {
        await approveTool({
          session_id: sessionId,
          approval_id: approvalId,
          decision,
          edited_args: editedArgs,
        });

        // 成功后清除消息上的 pendingApproval
        store.clearPendingApproval(messageId);
      } catch (e) {
        const err = e instanceof Error ? e : new Error(String(e));
        setError(err);
        throw err;
      } finally {
        setIsSubmitting(false);
      }
    },
    []
  );

  return { isSubmitting, error, decide };
}