import { Coins, TrendingDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatCost, formatNumber } from "@/types/metrics";

interface CostBreakdownProps {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  totalCost: number;
}

const PRICING = {
  input: 1.6,
  output: 6.4,
  cacheRead: 0.16,
  cacheWrite: 2.0,
};

export function CostBreakdown({
  inputTokens,
  outputTokens,
  cacheReadTokens,
  cacheWriteTokens,
  totalCost,
}: CostBreakdownProps) {
  const { t } = useTranslation();

  const inputCost = (inputTokens * PRICING.input) / 1_000_000;
  const outputCost = (outputTokens * PRICING.output) / 1_000_000;
  const cacheReadCost = (cacheReadTokens * PRICING.cacheRead) / 1_000_000;
  const cacheWriteCost = (cacheWriteTokens * PRICING.cacheWrite) / 1_000_000;

  const cacheSavings =
    (cacheReadTokens * (PRICING.input - PRICING.cacheRead)) / 1_000_000;

  const rows = [
    { label: t("dashboard.metrics.input"), tokens: inputTokens, cost: inputCost, color: "bg-blue-500" },
    { label: t("dashboard.metrics.output"), tokens: outputTokens, cost: outputCost, color: "bg-green-500" },
    { label: t("dashboard.metrics.cacheRead"), tokens: cacheReadTokens, cost: cacheReadCost, color: "bg-amber-500" },
    { label: t("dashboard.metrics.cacheWrite"), tokens: cacheWriteTokens, cost: cacheWriteCost, color: "bg-purple-500" },
  ];

  const total = inputCost + outputCost + cacheReadCost + cacheWriteCost;

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Coins className="h-4 w-4 text-amber-500" />
          <span className="text-sm font-medium">
            {t("dashboard.metrics.totalCost")}
          </span>
        </div>
        <span className="font-mono text-lg font-semibold">
          {formatCost(totalCost)}
        </span>
      </div>

      <div className="space-y-2">
        {rows.map((row) => {
          const pct = total > 0 ? (row.cost / total) * 100 : 0;
          return (
            <div key={row.label} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${row.color}`} />
                  {row.label}
                </span>
                <span className="text-muted-foreground">
                  {formatNumber(row.tokens)} tokens ·{" "}
                  <span className="font-mono">{formatCost(row.cost)}</span>
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full ${row.color} transition-all`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {cacheSavings > 0 && (
        <div className="flex items-center justify-between rounded-md border border-green-200 bg-green-50/50 px-3 py-2 text-xs dark:border-green-900 dark:bg-green-950/30">
          <span className="flex items-center gap-1.5 text-green-700 dark:text-green-400">
            <TrendingDown className="h-3.5 w-3.5" />
            {t("dashboard.metrics.cacheSavings")}
          </span>
          <span className="font-mono font-medium text-green-700 dark:text-green-400">
            {formatCost(cacheSavings)}
          </span>
        </div>
      )}
    </div>
  );
}