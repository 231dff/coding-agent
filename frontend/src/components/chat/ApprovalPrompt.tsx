import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  X,
  Pencil,
  Clock,
  RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PermissionGate } from "@/components/auth/PermissionGate";

interface ApprovalPromptProps {
  toolName: string;
  args: Record<string, unknown>;
  reason: string;
  createdAt: number;
  /** 超时时间（秒），默认 1800（30 分钟） */
  timeoutSeconds?: number;
  isSubmitting: boolean;
  error?: Error | null;
  onDecide: (
    decision: "approve" | "reject" | "edit",
    editedArgs?: Record<string, unknown>
  ) => void;
}

/** 把秒数格式化为 mm:ss 或 h:mm:ss */
function formatRemaining(seconds: number): string {
  if (seconds <= 0) return "已超时";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function ApprovalPrompt({
  toolName,
  args,
  reason,
  createdAt,
  timeoutSeconds = 1800,
  isSubmitting,
  error,
  onDecide,
}: ApprovalPromptProps) {
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [editedText, setEditedText] = useState(() =>
    JSON.stringify(args, null, 2)
  );
  const [parseError, setParseError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number>(() => {
    const elapsed = (Date.now() - createdAt) / 1000;
    return Math.max(0, timeoutSeconds - elapsed);
  });

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 倒计时
  useEffect(() => {
    const timer = setInterval(() => {
      const elapsed = (Date.now() - createdAt) / 1000;
      setRemaining(Math.max(0, timeoutSeconds - elapsed));
    }, 1000);
    return () => clearInterval(timer);
  }, [createdAt, timeoutSeconds]);

  // 编辑模式下自动聚焦
  useEffect(() => {
    if (mode === "edit" && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [mode]);

  // 键盘快捷键
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (mode === "view") {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (!isSubmitting) onDecide("approve");
        } else if (e.key === "Escape") {
          e.preventDefault();
          if (!isSubmitting) onDecide("reject");
        }
      } else {
        // 编辑模式：Cmd/Ctrl+Enter 提交，Esc 返回
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          submitEdited();
        } else if (e.key === "Escape") {
          e.preventDefault();
          setMode("view");
          setParseError(null);
          setEditedText(JSON.stringify(args, null, 2));
        }
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [mode, isSubmitting, args, editedText]);

  const isUrgent = remaining < 120; // 剩不到 2 分钟标红

  function submitEdited() {
    try {
      const parsed = JSON.parse(editedText);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setParseError("必须是一个 JSON 对象");
        return;
      }
      setParseError(null);
      onDecide("edit", parsed as Record<string, unknown>);
    } catch (e) {
      setParseError(
        `JSON 解析失败: ${e instanceof Error ? e.message : String(e)}`
      );
    }
  }

  const previewArgs = useMemo(
    () => JSON.stringify(args, null, 2),
    [args]
  );

  return (
    <div className="rounded-lg border-2 border-amber-400 bg-amber-50 dark:border-amber-600 dark:bg-amber-950/40">
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b border-amber-300/50 px-3 py-2 dark:border-amber-700/50">
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <span className="flex-1 text-sm font-medium text-amber-900 dark:text-amber-100">
          需要人工审批
        </span>
        <span
          className={cn(
            "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
            isUrgent
              ? "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"
              : "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300"
          )}
        >
          <Clock className="h-3 w-3" />
          {formatRemaining(remaining)}
        </span>
      </div>

      {/* 主体 */}
      <div className="space-y-3 p-3">
        {/* 工具名和理由 */}
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs text-amber-700 dark:text-amber-300">
              工具
            </span>
            <code className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs text-amber-900 dark:bg-amber-900/50 dark:text-amber-100">
              {toolName}
            </code>
          </div>
          <div className="text-xs text-amber-800 dark:text-amber-200">
            {reason}
          </div>
        </div>

        {/* 参数显示 / 编辑 */}
        {mode === "view" ? (
          <div>
            <div className="mb-1 text-[11px] font-medium text-amber-700 dark:text-amber-300">
              参数
            </div>
            <pre className="max-h-60 overflow-auto rounded border border-amber-200 bg-white p-2 font-mono text-[11px] leading-relaxed dark:border-amber-800 dark:bg-black/30">
              {previewArgs}
            </pre>
          </div>
        ) : (
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] font-medium text-amber-700 dark:text-amber-300">
                编辑参数（JSON）
              </span>
              <button
                onClick={() => {
                  setMode("view");
                  setParseError(null);
                  setEditedText(JSON.stringify(args, null, 2));
                }}
                className="flex items-center gap-1 text-[11px] text-amber-700 hover:underline dark:text-amber-300"
              >
                <RotateCcw className="h-3 w-3" />
                撤销
              </button>
            </div>
            <textarea
              ref={textareaRef}
              value={editedText}
              onChange={(e) => {
                setEditedText(e.target.value);
                setParseError(null);
              }}
              className={cn(
                "w-full resize-y rounded border bg-white p-2 font-mono text-[11px] leading-relaxed",
                "min-h-[120px] max-h-[400px]",
                "dark:bg-black/30",
                parseError
                  ? "border-red-400 focus:border-red-500"
                  : "border-amber-200 focus:border-amber-400 dark:border-amber-800"
              )}
              spellCheck={false}
            />
            {parseError && (
              <div className="mt-1 text-[11px] text-red-600 dark:text-red-400">
                {parseError}
              </div>
            )}
            <div className="mt-1 text-[10px] text-amber-600 dark:text-amber-400">
              提示: Cmd/Ctrl+Enter 提交，Esc 取消
            </div>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/50 dark:text-red-300">
            {error.message}
          </div>
        )}

        {/* 按钮组：权限门控 */}
        <PermissionGate
          minRole="developer"
          fallback={
            <div className="flex items-center gap-2 rounded border border-amber-300 bg-amber-100/50 px-2.5 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span>当前角色无审批权限，请等待开发者处理</span>
            </div>
          }
        >
          <div className="flex items-center gap-2">
            {mode === "view" ? (
              <>
                <button
                  onClick={() => onDecide("approve")}
                  disabled={isSubmitting}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    "bg-green-600 text-white hover:bg-green-700",
                    "disabled:cursor-not-allowed disabled:opacity-50"
                  )}
                >
                  <Check className="h-3.5 w-3.5" />
                  批准
                  <span className="text-[10px] opacity-70">(Enter)</span>
                </button>

                <button
                  onClick={() => setMode("edit")}
                  disabled={isSubmitting}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                    "border-amber-400 text-amber-800 hover:bg-amber-100",
                    "dark:border-amber-700 dark:text-amber-200 dark:hover:bg-amber-900/50",
                    "disabled:cursor-not-allowed disabled:opacity-50"
                  )}
                >
                  <Pencil className="h-3.5 w-3.5" />
                  编辑
                </button>

                <button
                  onClick={() => onDecide("reject")}
                  disabled={isSubmitting}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                    "border-red-400 text-red-700 hover:bg-red-50",
                    "dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/50",
                    "disabled:cursor-not-allowed disabled:opacity-50"
                  )}
                >
                  <X className="h-3.5 w-3.5" />
                  拒绝
                  <span className="text-[10px] opacity-70">(Esc)</span>
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={submitEdited}
                  disabled={isSubmitting || !!parseError}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    "bg-green-600 text-white hover:bg-green-700",
                    "disabled:cursor-not-allowed disabled:opacity-50"
                  )}
                >
                  <Check className="h-3.5 w-3.5" />
                  提交修改并批准
                  <span className="text-[10px] opacity-70">(⌘/Ctrl+Enter)</span>
                </button>
                <button
                  onClick={() => setMode("view")}
                  disabled={isSubmitting}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                    "border-border hover:bg-muted",
                    "disabled:cursor-not-allowed disabled:opacity-50"
                  )}
                >
                  取消
                </button>
              </>
            )}

            {isSubmitting && (
              <span className="text-[11px] text-amber-700 dark:text-amber-300">
                提交中...
              </span>
            )}
          </div>
        </PermissionGate>
      </div>
    </div>
  );
}