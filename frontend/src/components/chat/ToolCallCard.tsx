import { useState } from "react";
import {
  ChevronRight,
  Loader2,
  CheckCircle2,
  XCircle,
  FileEdit,
  Terminal,
  Search,
  FolderTree,
  FileText,
  Play,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolCall, ToolCallStatus } from "@/types/conversation";

interface ToolCallCardProps {
  toolCall: ToolCall;
}

const TOOL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  read_file: FileText,
  write_file: FileEdit,
  edit_file: FileEdit,
  tx_edit: FileEdit,
  tx_write: FileEdit,
  apply_patch: FileEdit,
  execute: Terminal,
  sandbox_read: FileText,
  sandbox_write: FileEdit,
  sandbox_grep: Search,
  grep_search: Search,
  glob_files: FolderTree,
  ls_dir: FolderTree,
  run_tests: Play,
  semantic_search: Search,
  repo_map: FolderTree,
  find_callers: Search,
  find_callees: Search,
  analyze_impact: Zap,
  load_skill: Zap,
};

function StatusIcon({ status }: { status: ToolCallStatus }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />;
    case "done":
      return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />;
    case "error":
      return <XCircle className="h-3.5 w-3.5 text-red-500" />;
    default:
      return null;
  }
}

function formatDuration(toolCall: ToolCall): string {
  if (!toolCall.endTime) return "";
  const ms = toolCall.endTime - toolCall.startTime;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [open, setOpen] = useState(false);
  const Icon = TOOL_ICONS[toolCall.name] ?? Zap;
  const duration = formatDuration(toolCall);

  return (
    <div
      className={cn(
        "rounded-md border bg-muted/30 text-xs",
        toolCall.status === "error" && "border-destructive/50"
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/50"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90"
          )}
        />
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="font-mono font-medium">{toolCall.name}</span>
        <StatusIcon status={toolCall.status} />
        {duration && (
          <span className="ml-auto text-muted-foreground">{duration}</span>
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t px-2.5 py-2">
          <div>
            <div className="mb-1 font-medium text-muted-foreground">参数</div>
            <pre
              data-testid="tool-args"
              className="max-h-48 overflow-auto rounded bg-background p-2 text-[11px]"
            >
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>

          {toolCall.output && (
            <div>
              <div className="mb-1 font-medium text-muted-foreground">输出</div>
              <pre
                data-testid="tool-output"
                className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-2 text-[11px]"
              >
                {toolCall.output.length > 5000
                  ? toolCall.output.slice(0, 5000) + "\n... (已截断)"
                  : toolCall.output}
              </pre>
            </div>
          )}

          {toolCall.error && (
            <div>
              <div className="mb-1 font-medium text-destructive">错误</div>
              <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-destructive/10 p-2 text-[11px] text-destructive">
                {toolCall.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}