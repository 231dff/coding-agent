import { useQuery } from "@tanstack/react-query";
import { Loader2, Zap, Database, Trash2, Coins } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchContextMetrics } from "@/api/contextMetrics";

interface ContextUsageBarProps {
  sessionId: string;
}

/** 计算进度条颜色 */
function barColor(pct: number): string {
  if (pct > 85) return "bg-red-500";
  if (pct > 60) return "bg-amber-500";
  return "bg-green-500";
}

/** 环形进度：SVG 实现 */
function Ring({ value, max = 1, label, sublabel }: {
  value: number;
  max?: number;
  label: string;
  sublabel: string;
}) {
  const pct = Math.min(1, value / max);
  const R = 28;
  const C = 2 * Math.PI * R;
  const dash = C * pct;

  const strokeColor = pct > 0.85 ? "#ef4444" : pct > 0.6 ? "#f59e0b" : "#22c55e";

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative">
        <svg width="72" height="72" viewBox="0 0 72 72">
          {/* 背景环 */}
          <circle
            cx="36" cy="36" r={R}
            fill="none"
            stroke="currentColor"
            strokeWidth="6"
            className="text-muted"
          />
          {/* 进度环 */}
          <circle
            cx="36" cy="36" r={R}
            fill="none"
            stroke={strokeColor}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${C}`}
            transform="rotate(-90 36 36)"
            style={{ transition: "stroke-dasharray 0.3s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-medium">{(pct * 100).toFixed(0)}%</span>
        </div>
      </div>
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span className="text-[10px] text-muted-foreground/70">{sublabel}</span>
    </div>
  );
}

export function ContextUsageBar({ sessionId }: ContextUsageBarProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["context-metrics", sessionId],
    queryFn: () => fetchContextMetrics(sessionId),
    refetchInterval: 5000,
    enabled: !!sessionId,
  });

  if (!sessionId) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
        开始对话后显示上下文用量
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

  if (error || !data) {
    return (
      <div className="p-3 text-xs text-destructive">
        加载失败: {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }

  const tokenPct = (data.used_tokens / data.max_tokens) * 100;

  return (
    <div className="space-y-4 p-3 text-xs">
      {/* Token 用量进度条 */}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="flex items-center gap-1 font-medium">
            <Database className="h-3 w-3" />
            上下文用量
          </span>
          <span className="text-muted-foreground">
            {data.used_tokens.toLocaleString()} / {data.max_tokens.toLocaleString()}
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full transition-all", barColor(tokenPct))}
            style={{ width: `${Math.min(100, tokenPct)}%` }}
          />
        </div>
        <div className="mt-1 text-[10px] text-muted-foreground">
          {tokenPct.toFixed(1)}% 已使用
        </div>
      </div>

      {/* 环形指标 */}
      <div className="flex justify-around border-y py-3">
        <Ring
          value={data.cache_hit_rate}
          max={1}
          label="缓存命中"
          sublabel={`${(data.cache_hit_rate * 100).toFixed(0)}%`}
        />
        <Ring
          value={data.used_tokens}
          max={data.max_tokens}
          label="Token"
          sublabel={`${(data.used_tokens / 1000).toFixed(1)}k`}
        />
      </div>

      {/* 压缩事件 */}
      <div>
        <div className="mb-2 flex items-center gap-1 font-medium">
          <Zap className="h-3 w-3" />
          压缩事件
        </div>
        <div className="grid grid-cols-5 gap-1.5">
          {(["L1", "L2", "L3", "L4", "L5"] as const).map((layer) => (
            <div
              key={layer}
              className={cn(
                "rounded border py-1.5 text-center",
                data.compaction_events[layer] > 0
                  ? "border-accent/30 bg-accent/5"
                  : "border-border bg-muted/30"
              )}
            >
              <div className="text-[10px] font-medium text-muted-foreground">{layer}</div>
              <div className="text-sm font-semibold">{data.compaction_events[layer]}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 成本 */}
      <div className="flex items-center justify-between rounded border bg-muted/30 px-2.5 py-2">
        <span className="flex items-center gap-1 font-medium">
          <Coins className="h-3 w-3" />
          本次成本
        </span>
        <span className="font-mono">${data.total_cost_usd.toFixed(4)}</span>
      </div>

      {/* 卸载文件 */}
      {data.offloaded_files.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-center gap-1 font-medium">
            <Trash2 className="h-3 w-3" />
            已卸载文件 ({data.offloaded_files.length})
          </div>
          <div className="space-y-0.5">
            {data.offloaded_files.map((f) => (
              <div
                key={f}
                className="truncate rounded bg-muted/30 px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
                title={f}
              >
                {f}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}