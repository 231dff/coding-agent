import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { MessageBubble } from "./MessageBubble";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import type { Message } from "@/types/conversation";
import { cn } from "@/lib/utils";

interface MessageListProps {
  messages: Message[];
  onApprovalDecide?: (
    messageId: string,
    approvalId: string,
    decision: "approve" | "reject" | "edit",
    editedArgs?: Record<string, unknown>
  ) => void;
  isApprovalSubmitting?: boolean;
  approvalError?: Error | null;
}

export function MessageList({
  messages,
  onApprovalDecide,
  isApprovalSubmitting = false,
  approvalError = null,
}: MessageListProps) {
  const { t } = useTranslation();
  const lastContentLength = messages[messages.length - 1]?.content.length ?? 0;
  const hasPendingApproval = messages.some((m) => m.pendingApproval);

  const { scrollRef, isAtBottom, scrollToBottom } = useAutoScroll(
    `${messages.length}-${lastContentLength}-${hasPendingApproval}`
  );

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 120,
    overscan: 5,
    measureElement: (el) => el.getBoundingClientRect().height,
  });

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="text-center">
          <p className="text-lg font-medium">{t("chat.welcome")}</p>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("chat.welcomeHint")}
          </p>
          <p className="mt-4 text-xs text-muted-foreground/70">
            {t("chat.tryExample")}
            <code className="ml-1 rounded bg-muted px-1.5 py-0.5">
              {t("chat.exampleTask")}
            </code>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={scrollRef} className="h-full overflow-y-auto">
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {virtualizer.getVirtualItems().map((vItem) => {
            const message = messages[vItem.index];
            return (
              <div
                key={message.id}
                data-index={vItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${vItem.start}px)`,
                }}
              >
                <MessageBubble
                  message={message}
                  onApprovalDecide={onApprovalDecide}
                  isApprovalSubmitting={isApprovalSubmitting}
                  approvalError={approvalError}
                />
              </div>
            );
          })}
        </div>
      </div>

      <button
        onClick={() => scrollToBottom()}
        className={cn(
          "absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border bg-background p-2 shadow-md transition-opacity",
          "hover:bg-muted",
          isAtBottom ? "pointer-events-none opacity-0" : "opacity-100"
        )}
        title={t("chat.backToBottom")}
      >
        <ArrowDown className="h-4 w-4" />
      </button>
    </div>
  );
}