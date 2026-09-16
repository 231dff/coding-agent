import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { StreamingMarkdown } from "./StreamingMarkdown";
import { ToolCallCard } from "./ToolCallCard";
import { ApprovalPrompt } from "./ApprovalPrompt";
import type { Message } from "@/types/conversation";

interface MessageBubbleProps {
  message: Message;
  /** 审批决策回调（仅 assistant 消息带 pendingApproval 时用） */
  onApprovalDecide?: (
    messageId: string,
    approvalId: string,
    decision: "approve" | "reject" | "edit",
    editedArgs?: Record<string, unknown>
  ) => void;
  /** 提交中状态 */
  isApprovalSubmitting?: boolean;
  /** 提交错误 */
  approvalError?: Error | null;
}

export function MessageBubble({
  message,
  onApprovalDecide,
  isApprovalSubmitting = false,
  approvalError = null,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const approval = message.pendingApproval;

  return (
    <div className={cn("flex gap-3 px-4 py-3", isUser && "justify-end")}>
      {!isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent">
          <Bot className="h-4 w-4" />
        </div>
      )}

      <div
        className={cn(
          "min-w-0 max-w-[80%]",
          isUser && "flex flex-col items-end"
        )}
      >
        {/* 用户消息 */}
        {isUser && (
          <div className="whitespace-pre-wrap break-words rounded-lg bg-muted px-3 py-2 text-sm">
            {message.content}
          </div>
        )}

        {/* 助手消息 */}
        {!isUser && (
          <div className="space-y-2">
            {/* 工具调用卡片 + 审批卡片 */}
            {message.toolCalls.length > 0 && (
              <div className="space-y-1.5">
                {message.toolCalls.map((tc) => {
                  // 如果这个工具调用正在等待审批，渲染审批卡片而非工具卡片
                  if (
                    approval &&
                    approval.toolCallId === tc.id &&
                    onApprovalDecide
                  ) {
                    return (
                      <ApprovalPrompt
                        key={tc.id}
                        toolName={tc.name}
                        args={tc.args}
                        reason={approval.reason}
                        createdAt={approval.createdAt}
                        isSubmitting={isApprovalSubmitting}
                        error={approvalError}
                        onDecide={(decision, editedArgs) =>
                          onApprovalDecide(
                            message.id,
                            approval.approvalId,
                            decision,
                            editedArgs
                          )
                        }
                      />
                    );
                  }
                  return <ToolCallCard key={tc.id} toolCall={tc} />;
                })}
              </div>
            )}

            {/* 文本内容 */}
            {message.content && (
              <StreamingMarkdown
                content={message.content}
                isStreaming={message.status === "streaming"}
              />
            )}

            {/* 流式光标 */}
            {message.status === "streaming" &&
              !message.content &&
              !approval && (
                <span className="inline-block h-4 w-1.5 animate-pulse bg-accent" />
              )}

            {/* 错误 */}
            {message.error && (
              <div className="rounded-md border border-destructive bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {message.error}
              </div>
            )}
          </div>
        )}
      </div>

      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}