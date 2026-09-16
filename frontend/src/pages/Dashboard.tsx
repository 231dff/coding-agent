import { useState } from "react";
import {
  Activity,
  Coins,
  Database,
  Loader2,
  RefreshCw,
  Clock,
  TrendingUp,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMetrics } from "@/hooks/useMetrics";
import { StatCard } from "@/components/dashboard/StatCard";
import { TimeRangePicker } from "@/components/dashboard/TimeRangePicker";
import { TimeseriesChart } from "@/components/dashboard/TimeseriesChart";
import { ToolStatsChart } from "@/components/dashboard/ToolStatsChart";
import { CompactionPieChart } from "@/components/dashboard/CompactionPieChart";
import { CostBreakdown } from "@/components/dashboard/CostBreakdown";
import { formatNumber, formatCost, type TimeRange } from "@/types/metrics";

interface DashboardProps {
  onBack?: () => void;
}

export function Dashboard({ onBack }: DashboardProps) {
  const { t } = useTranslation();
  const [range, setRange] = useState<TimeRange>("24h");
  const { data, isLoading, error, isFetching, refetch } = useMetrics(range);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex h-12 items-center gap-3 border-b px-4">
        {onBack && (
          <button
            onClick={onBack}
            className="rounded-md px-2 py-1 text-xs hover:bg-muted"
          >
            ← {t("dashboard.back")}
          </button>
        )}
        <span className="text-sm font-medium">{t("dashboard.title")}</span>

        <div className="ml-auto flex items-center gap-2">
          {isFetching && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          )}
          <button
            onClick={() => refetch()}
            className="rounded-md p-1.5 hover:bg-muted"
            title={t("dashboard.refresh")}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {t("app.loading")}
          </div>
        )}

        {error && (
          <div className="p-4 text-sm text-destructive">
            {t("dashboard.loadFailed")}:{" "}
            {error instanceof Error ? error.message : String(error)}
          </div>
        )}

        {data && (
          <div className="space-y-4 p-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
              <StatCard
                label={t("dashboard.stats.llmCalls")}
                value={formatNumber(data.summary.total_llm_calls)}
                sublabel={t("dashboard.stats.toolsCall", {
                  value: formatNumber(data.summary.total_tool_calls),
                })}
                icon={Activity}
                color="blue"
              />
              <StatCard
                label={t("dashboard.stats.inputTokens")}
                value={formatNumber(data.summary.total_input_tokens)}
                sublabel={t("dashboard.stats.cacheRead", {
                  value: formatNumber(data.summary.total_cache_read_tokens),
                })}
                icon={Database}
                color="green"
              />
              <StatCard
                label={t("dashboard.stats.outputTokens")}
                value={formatNumber(data.summary.total_output_tokens)}
                icon={TrendingUp}
                color="default"
              />
              <StatCard
                label={t("dashboard.stats.cacheHitRate")}
                value={`${(data.summary.cache_hit_rate * 100).toFixed(1)}%`}
                sublabel={
                  data.summary.cache_hit_rate > 0.7
                    ? t("dashboard.stats.excellent")
                    : data.summary.cache_hit_rate > 0.5
                      ? t("dashboard.stats.good")
                      : t("dashboard.stats.needsWork")
                }
                icon={Database}
                color={
                  data.summary.cache_hit_rate > 0.7
                    ? "green"
                    : data.summary.cache_hit_rate > 0.5
                      ? "amber"
                      : "red"
                }
              />
              <StatCard
                label={t("dashboard.stats.totalCost")}
                value={formatCost(data.summary.total_cost_usd)}
                sublabel={t("dashboard.stats.avgLatency", {
                  value: Math.round(data.summary.avg_latency_ms),
                })}
                icon={Coins}
                color="amber"
              />
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <ChartCard title={t("dashboard.charts.tokensTrend")}>
                <TimeseriesChart
                  points={data.points}
                  range={range}
                  metric="tokens"
                />
              </ChartCard>

              <ChartCard title={t("dashboard.charts.callsTrend")}>
                <TimeseriesChart
                  points={data.points}
                  range={range}
                  metric="calls"
                />
              </ChartCard>
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <ChartCard title={t("dashboard.charts.costTrend")}>
                <TimeseriesChart
                  points={data.points}
                  range={range}
                  metric="cost"
                  height={220}
                />
              </ChartCard>

              <ChartCard title={t("dashboard.charts.latencyTrend")}>
                <TimeseriesChart
                  points={data.points}
                  range={range}
                  metric="latency"
                  height={220}
                />
              </ChartCard>
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <ChartCard
                title={t("dashboard.charts.toolTop10")}
                className="lg:col-span-1"
              >
                <ToolStatsChart
                  totals={data.tool_totals}
                  height={300}
                  topN={10}
                />
              </ChartCard>

              <ChartCard title={t("dashboard.charts.compaction")}>
                <CompactionPieChart
                  totals={data.compaction_totals}
                  height={300}
                />
              </ChartCard>

              <ChartCard title={t("dashboard.charts.costBreakdown")}>
                <CostBreakdown
                  inputTokens={data.summary.total_input_tokens}
                  outputTokens={data.summary.total_output_tokens}
                  cacheReadTokens={data.summary.total_cache_read_tokens}
                  cacheWriteTokens={0}
                  totalCost={data.summary.total_cost_usd}
                />
              </ChartCard>
            </div>

            <div className="flex items-center justify-center gap-2 py-2 text-[10px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              {t("dashboard.footer", {
                seconds: data.bucket_seconds,
                count: data.points.length,
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface ChartCardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

function ChartCard({ title, children, className }: ChartCardProps) {
  return (
    <div className={`rounded-lg border bg-background ${className ?? ""}`}>
      <div className="border-b px-3 py-2">
        <h3 className="text-xs font-medium">{title}</h3>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}