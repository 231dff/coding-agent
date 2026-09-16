import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  X,
  Pencil,
  Download,
  Loader2,
  Filter,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { listApprovals } from "@/api/client";
import type { ApprovalRecord } from "@/api/types";

type FilterType = "all" | "approve" | "reject" | "edit";

interface ApprovalHistoryProps {
  sessionId: string;
}

/** 决策图标 */
function DecisionIcon({ decision }: { decision: string }) {
  switch (decision) {
    case "approve":
      return <Check className="h-3.5 w-3.5 text-green-600" />;
    case "reject":
      return <X className="h-3.5 w-3.5 text-red-600" />;
    case "edit":
      return <Pencil className="h-3.5 w-3.5 text-amber-600" />;
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground" />;
  }
}

function decisionLabel(decision: string): string {
  switch (decision) {
    case "approve":
      return "已批准";
    case "reject":
      return "已拒绝";
    case "edit":
      return "已编辑";
    default:
      return "待处理";
  }
}

function decisionColor(decision: string): string {
  switch (decision) {
    case "approve":
      return "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-800";
    case "reject":
      return "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800";
    case "edit":
      return "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  const now = Date.now();
  const diff = now - ts * 1000;

  // 1 分钟内：显示 "刚刚"
  if (diff < 60_000) return "刚刚";
  // 1 小时内：显示 "N 分钟前"
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  // 24 小时内：显示 "N 小时前"
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  // 更早：显示具体时间
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 导出一组审批记录为 CSV */
function exportCsv(records: ApprovalRecord[]): void {
  const headers = [
    "id",
    "session_id",
    "tool_name",
    "args",
    "decision",
    "edited_args",
    "decided_at",
    "decided_by",
  ];

  const escape = (v: unknown): string => {
    const s = v === null || v === undefined ? "" : String(v);
    // CSV 转义：包含逗号、引号、换行时用双引号包裹，内部引号双写
    if (s.includes(",") || s.includes('"') || s.includes("\n")) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  };

  const rows = records.map((r) =>
    [
      r.id,
      r.session_id,
      r.tool_name,
      JSON.stringify(r.args),
      r.decision,
      r.edited_args ? JSON.stringify(r.edited_args) : "",
      new Date(r.decided_at * 1000).toISOString(),
      r.decided_by,
    ]
      .map(escape)
      .join(",")
  );

  const csv = "\uFEFF" + [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `approvals-${Date.now()}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function ApprovalHistory({ sessionId }: ApprovalHistoryProps) {
  const [filter, setFilter] = useState<FilterType>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["approvals", sessionId],
    queryFn: () => listApprovals(sessionId, 200),
    refetchInterval: 10_000,
    enabled: !!sessionId,
  });

  const records = data?.records ?? [];

  const filtered = useMemo(() => {
    if (filter === "all") return records;
    return records.filter((r) => r.decision === filter);
  }, [records, filter]);

  const counts = useMemo(
    () => ({
      all: records.length,
      approve: records.filter((r) => r.decision === "approve").length,
      reject: records.filter((r) => r.decision === "reject").length,
      edit: records.filter((r) => r.decision === "edit").length,
    }),
    [records]
  );

  if (!sessionId) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-xs text-muted-foreground">
        开始对话后，审批记录会显示在这里
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-6 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        加载中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-xs text-destructive">
        加载失败: {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* 工具栏 */}
      <div className="flex items-center gap-1 border-b px-2 py-1.5">
        <Filter className="ml-1 h-3 w-3 text-muted-foreground" />
        {(["all", "approve", "reject", "edit"] as FilterType[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "rounded px-2 py-1 text-[11px] transition-colors",
              filter === f
                ? "bg-accent/15 font-medium text-accent"
                : "text-muted-foreground hover:bg-muted"
            )}
          >
            {f === "all" ? "全部" : decisionLabel(f)}
            <span className="ml-1 text-muted-foreground/70">
              {counts[f]}
            </span>
          </button>
        ))}

        <div className="ml-auto">
          <button
            onClick={() => exportCsv(filtered)}
            disabled={filtered.length === 0}
            className={cn(
              "flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors",
              "hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
            )}
            title="导出 CSV"
          >
            <Download className="h-3 w-3" />
            导出
          </button>
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center p-6 text-xs text-muted-foreground">
            {records.length === 0 ? "暂无审批记录" : "当前筛选下无记录"}
          </div>
        ) : (
          <div className="space-y-1.5 p-2">
            {filtered.map((r) => (
              <ApprovalRecordCard key={r.id} record={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ApprovalRecordCard({ record }: { record: ApprovalRecord }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-md border text-xs">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/50"
      >
        <DecisionIcon decision={record.decision} />
        <code className="font-mono font-medium">{record.tool_name}</code>
        <span
          className={cn(
            "rounded border px-1.5 py-0.5 text-[10px]",
            decisionColor(record.decision)
          )}
        >
          {decisionLabel(record.decision)}
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {formatTime(record.decided_at)}
        </span>
      </button>

      {expanded && (
        <div className="space-y-2 border-t px-2.5 py-2">
          <div>
            <div className="mb-1 text-[10px] font-medium text-muted-foreground">
              参数
            </div>
            <pre className="max-h-40 overflow-auto rounded bg-muted/50 p-2 font-mono text-[10px]">
              {JSON.stringify(record.args, null, 2)}
            </pre>
          </div>

          {record.edited_args && (
            <div>
              <div className="mb-1 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                编辑后的参数
              </div>
              <pre className="max-h-40 overflow-auto rounded bg-amber-50 p-2 font-mono text-[10px] dark:bg-amber-950/30">
                {JSON.stringify(record.edited_args, null, 2)}
              </pre>
            </div>
          )}

          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <span>操作人: {record.decided_by}</span>
            <span>ID: {record.id}</span>
          </div>
        </div>
      )}
    </div>
  );
}