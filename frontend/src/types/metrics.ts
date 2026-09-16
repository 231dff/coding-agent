/** 时序指标类型。与 api/metrics_timeseries.py 对应。 */

export type TimeRange = "1h" | "24h" | "7d" | "30d" | "all";

export interface MetricPoint {
  timestamp: number;
  llm_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  avg_latency_ms: number;
  tool_breakdown: Record<string, number>;
  compaction_layers: Record<string, number>;
}

export interface SummaryStats {
  total_llm_calls: number;
  total_tool_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cache_read_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  cache_hit_rate: number;
}

export interface TimeseriesResponse {
  range: TimeRange;
  bucket_seconds: number;
  points: MetricPoint[];
  summary: SummaryStats;
  tool_totals: Record<string, number>;
  compaction_totals: Record<string, number>;
}

/** 时间范围显示名称 */
export const RANGE_LABELS: Record<TimeRange, string> = {
  "1h": "1 小时",
  "24h": "24 小时",
  "7d": "7 天",
  "30d": "30 天",
  all: "全部",
};

/** 大数字格式化 */
export function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

/** 成本格式化 */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

/** 时间戳格式化（用于图表 X 轴） */
export function formatTimestamp(ts: number, range: TimeRange): string {
  const d = new Date(ts * 1000);

  if (range === "1h") {
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  if (range === "24h") {
    return `${String(d.getHours()).padStart(2, "0")}:00`;
  }
  // 7d / 30d / all
  return `${d.getMonth() + 1}/${d.getDate()}`;
}