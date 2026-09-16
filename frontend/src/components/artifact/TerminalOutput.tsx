import { useEffect, useMemo, useRef } from "react";
import { AnsiUp } from "ansi_up";
import {
  Terminal,
  CheckCircle2,
  XCircle,
  Loader2,
  Copy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { TerminalArtifact } from "@/types/artifact";

interface TerminalOutputProps {
  entries: TerminalArtifact[];
}

/**
 * ANSI 转换器单例。
 *
 * 放在组件外创建，避免每次渲染都 new 一个。
 * ansi_up 是无状态的（每次调用 ansi_to_html 不保留上下文），
 * 单例可安全复用。
 *
 * use_classes = false：输出内联 style，而不是 class="ansi-red-fg"。
 * 这样不依赖外部 CSS 文件，样式自带。
 */
const ansiUp = new AnsiUp();
ansiUp.use_classes = false;

/**
 * 单个终端条目。
 *
 * 展示：命令头 + 输出体。
 * 命令头包含：图标、命令、状态图标、复制按钮。
 * 输出体：ANSI 转 HTML，用 dangerouslySetInnerHTML 注入。
 *
 * 安全说明：
 * ansi_up 默认会转义 HTML 特殊字符（<、>、&），
 * 只有它自己生成的 <span style="..."> 是真实的 HTML。
 * 因此 dangerouslySetInnerHTML 在这里是安全的。
 */
function TerminalEntry({ entry }: { entry: TerminalArtifact }) {
  const outputRef = useRef<HTMLPreElement>(null);

  // ANSI 转义码 → HTML
  const html = useMemo(() => {
    const text = entry.output || "(无输出)";
    try {
      return ansiUp.ansi_to_html(text);
    } catch {
      // 转换失败时，降级为纯文本（转义 HTML 特殊字符）
      return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }
  }, [entry.output]);

  // 自动滚到底部（仅对正在运行或很长的输出）
  useEffect(() => {
    const el = outputRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entry.output]);

  const statusIcon = {
    running: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />,
    done: <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />,
    error: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  }[entry.status];

  function handleCopy() {
    void navigator.clipboard.writeText(entry.output);
  }

  return (
    <div className="rounded-md border bg-[#1e1e1e] text-xs">
      {/* 命令头 */}
      <div className="flex items-center gap-2 border-b border-white/10 bg-black/40 px-3 py-1.5 text-gray-300">
        <Terminal className="h-3.5 w-3.5 text-gray-500" />
        <span className="flex-1 truncate font-mono">
          <span className="text-green-400">$</span> {entry.command}
        </span>
        {statusIcon}
        <button
          onClick={handleCopy}
          className="rounded p-0.5 text-gray-500 hover:bg-white/10 hover:text-gray-300"
          title="复制输出"
        >
          <Copy className="h-3 w-3" />
        </button>
      </div>

      {/* 输出 */}
      <pre
        ref={outputRef}
        className={cn(
          "max-h-96 overflow-auto whitespace-pre-wrap break-words px-3 py-2",
          "font-mono text-[11px] leading-relaxed text-gray-200"
        )}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

export function TerminalOutput({ entries }: TerminalOutputProps) {
  if (entries.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
        暂无终端输出
      </div>
    );
  }

  return (
    <div className="space-y-2 p-3">
      {entries.map((entry) => (
        <TerminalEntry key={entry.id} entry={entry} />
      ))}
    </div>
  );
}