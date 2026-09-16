import { useEffect, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Notification, NotificationType } from "@/types/notification";

interface ToastProps {
  notification: Notification;
  onDismiss: () => void;
}

const CONFIG: Record<
  NotificationType,
  {
    icon: React.ComponentType<{ className?: string }>;
    color: string;
    bgColor: string;
    borderColor: string;
  }
> = {
  success: {
    icon: CheckCircle2,
    color: "text-green-600 dark:text-green-400",
    bgColor: "bg-green-50 dark:bg-green-950/50",
    borderColor: "border-green-200 dark:border-green-800",
  },
  error: {
    icon: XCircle,
    color: "text-red-600 dark:text-red-400",
    bgColor: "bg-red-50 dark:bg-red-950/50",
    borderColor: "border-red-200 dark:border-red-800",
  },
  warning: {
    icon: AlertTriangle,
    color: "text-amber-600 dark:text-amber-400",
    bgColor: "bg-amber-50 dark:bg-amber-950/50",
    borderColor: "border-amber-200 dark:border-amber-800",
  },
  info: {
    icon: Info,
    color: "text-blue-600 dark:text-blue-400",
    bgColor: "bg-blue-50 dark:bg-blue-950/50",
    borderColor: "border-blue-200 dark:border-blue-800",
  },
};

export function Toast({ notification, onDismiss }: ToastProps) {
  const [leaving, setLeaving] = useState(false);
  const { icon: Icon, color, bgColor, borderColor } = CONFIG[notification.type];

  // 自动关闭
  useEffect(() => {
    const duration = notification.duration ?? 0;
    if (duration <= 0) return;

    const timer = setTimeout(() => {
      setLeaving(true);
      // 动画结束后再真正移除
      setTimeout(onDismiss, 200);
    }, duration);

    return () => clearTimeout(timer);
  }, [notification.duration, onDismiss]);

  function handleClose() {
    setLeaving(true);
    setTimeout(onDismiss, 200);
  }

  return (
    <div
      role="alert"
      className={cn(
        "pointer-events-auto flex w-80 items-start gap-3 rounded-lg border p-3 shadow-lg transition-all",
        bgColor,
        borderColor,
        leaving
          ? "translate-x-full opacity-0"
          : "translate-x-0 opacity-100"
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", color)} />

      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{notification.title}</div>
        {notification.description && (
          <div className="mt-0.5 text-xs text-muted-foreground">
            {notification.description}
          </div>
        )}
        {notification.action && (
          <button
            onClick={() => {
              notification.action?.onClick();
              handleClose();
            }}
            className={cn(
              "mt-2 rounded-md border px-2 py-1 text-xs transition-colors",
              "hover:bg-background/60"
            )}
          >
            {notification.action.label}
          </button>
        )}
      </div>

      <button
        onClick={handleClose}
        className="shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:bg-background/60 hover:text-foreground"
        aria-label="关闭"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}