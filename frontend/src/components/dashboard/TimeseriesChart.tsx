import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { useTranslation } from "react-i18next";
import {
  formatNumber,
  formatTimestamp,
  type MetricPoint,
  type TimeRange,
} from "@/types/metrics";

interface TimeseriesChartProps {
  points: MetricPoint[];
  range: TimeRange;
  metric: "tokens" | "calls" | "cost" | "latency";
  height?: number;
}

function buildSeries(points: MetricPoint[], metric: string) {
  return points.map((p) => {
    const base = { timestamp: p.timestamp };
    if (metric === "tokens") {
      return {
        ...base,
        input: p.input_tokens,
        output: p.output_tokens,
        cache: p.cache_read_tokens,
      };
    }
    if (metric === "calls") {
      return { ...base, llm: p.llm_calls, tool: p.tool_calls };
    }
    if (metric === "cost") {
      return { ...base, cost: p.cost_usd };
    }
    if (metric === "latency") {
      return { ...base, latency: p.avg_latency_ms };
    }
    return base;
  });
}

export function TimeseriesChart({
  points,
  range,
  metric,
  height = 240,
}: TimeseriesChartProps) {
  const { t } = useTranslation();

  if (points.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}
      >
        {t("dashboard.noData")}
      </div>
    );
  }

  const data = buildSeries(points, metric);

  const xAxisProps = {
    dataKey: "timestamp",
    tickFormatter: (v: number) => formatTimestamp(v, range),
    stroke: "currentColor",
    fontSize: 10,
    tickLine: false,
    axisLine: false,
    className: "text-muted-foreground",
    minTickGap: 30,
  };

  const yAxisProps = {
    stroke: "currentColor",
    fontSize: 10,
    tickLine: false,
    axisLine: false,
    className: "text-muted-foreground",
    tickFormatter: (v: number) => formatNumber(v),
    width: 45,
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
        <XAxis {...xAxisProps} />
        <YAxis {...yAxisProps} />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--color-popover)",
            border: "1px solid var(--color-border)",
            borderRadius: "6px",
            fontSize: "11px",
            padding: "6px 10px",
            color: "var(--color-popover-foreground)",
          }}
          labelFormatter={(label) => {
            // recharts 3.x 的 label 类型是 ReactNode
            const ts = typeof label === "number" ? label : Number(label ?? 0);
            if (!Number.isFinite(ts)) return String(label ?? "");
            return new Date(ts * 1000).toLocaleString();
          }}
          formatter={(value) => {
            // recharts 3.x 的 value 类型是 ValueType | undefined
            const num = typeof value === "number" ? value : Number(value ?? 0);
            return formatNumber(num);
          }}
        />
        <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "4px" }} iconSize={8} />

        {metric === "tokens" && (
          <>
            <Line
              type="monotone"
              dataKey="input"
              name={t("dashboard.metrics.input")}
              stroke="#3b82f6"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="output"
              name={t("dashboard.metrics.output")}
              stroke="#10b981"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="cache"
              name={t("dashboard.metrics.cacheRead")}
              stroke="#f59e0b"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="4 2"
              isAnimationActive={false}
            />
          </>
        )}

        {metric === "calls" && (
          <>
            <Line
              type="monotone"
              dataKey="llm"
              name={t("dashboard.metrics.llmCalls")}
              stroke="#3b82f6"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="tool"
              name={t("dashboard.metrics.toolCalls")}
              stroke="#8b5cf6"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </>
        )}

        {metric === "cost" && (
          <Line
            type="monotone"
            dataKey="cost"
            name={t("dashboard.metrics.cost")}
            stroke="#f59e0b"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        )}

        {metric === "latency" && (
          <Line
            type="monotone"
            dataKey="latency"
            name={t("dashboard.metrics.avgLatency")}
            stroke="#ef4444"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}