import { useConversation } from "@/hooks/useConversation";
import { usePendingApproval } from "@/hooks/usePendingApproval";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";

export function ChatPanel() {
  const { messages, isStreaming, error, send, abort } = useConversation();
  const {
    isSubmitting: isApprovalSubmitting,
    error: approvalError,
    decide: decideApproval,
  } = usePendingApproval();

  /**
   * 处理审批决策。
   *
   * 来自 MessageBubble 的 onApprovalDecide 回调。
   */
  function handleApprovalDecide(
    messageId: string,
    approvalId: string,
    decision: "approve" | "reject" | "edit",
    editedArgs?: Record<string, unknown>
  ) {
    void decideApproval(messageId, approvalId, decision, editedArgs);
  }

  return (
    <div className="flex h-full flex-col">
      {error && (
        <div className="border-b border-destructive bg-destructive/10 px-4 py-2 text-sm text-destructive">
          错误: {error.message}
        </div>
      )}

      <MessageList
        messages={messages}
        onApprovalDecide={handleApprovalDecide}
        isApprovalSubmitting={isApprovalSubmitting}
        approvalError={approvalError}
      />

      <Composer onSend={send} onAbort={abort} isStreaming={isStreaming} />
    </div>
  );
}