import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { useTranslation } from "react-i18next";

interface CompactionPieChartProps {
  totals: Record<string, number>;
  height?: number;
}

const LAYER_CONFIG: Record<string, { color: string; labelKey: string }> = {
  L1: { color: "#3b82f6", labelKey: "dashboard.compactionLayers.L1" },
  L2: { color: "#8b5cf6", labelKey: "dashboard.compactionLayers.L2" },
  L3: { color: "#f59e0b", labelKey: "dashboard.compactionLayers.L3" },
  L4: { color: "#10b981", labelKey: "dashboard.compactionLayers.L4" },
  L5: { color: "#ef4444", labelKey: "dashboard.compactionLayers.L5" },
};

export function CompactionPieChart({
  totals,
  height = 280,
}: CompactionPieChartProps) {
  const { t } = useTranslation();

  const data = Object.entries(totals)
    .filter(([_, count]) => count > 0)
    .map(([layer, count]) => ({
      name: layer,
      value: count,
      label: LAYER_CONFIG[layer] ? t(LAYER_CONFIG[layer].labelKey) : layer,
      color: LAYER_CONFIG[layer]?.color ?? "#94a3b8",
    }));

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}
      >
        {t("dashboard.noData")}
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={80}
          paddingAngle={2}
          dataKey="value"
          isAnimationActive={false}
          label={(entry) => {
            const e = entry as { name: string; value: number };
            return `${e.name}: ${e.value}`;
          }}
          labelLine={{ stroke: "currentColor", opacity: 0.3 }}
          style={{ fontSize: "10px" }}
        >
          {data.map((entry, index) => (
            <Cell key={index} fill={entry.color} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--color-popover)",
            border: "1px solid var(--color-border)",
            borderRadius: "6px",
            fontSize: "11px",
            padding: "6px 10px",
            color: "var(--color-popover-foreground)",
          }}
          formatter={(value, _name, item) => {
            // recharts 3.x 的 value 是 ValueType | undefined
            const numValue =
              typeof value === "number" ? value : Number(value ?? 0);

            // item.payload 里带我们自定义的 label
            const payload = (item as { payload?: { label?: string } } | undefined)
              ?.payload;
            const label = payload?.label ?? String(_name ?? "");

            return [numValue, label];
          }}
        />
        <Legend
          wrapperStyle={{ fontSize: "11px", paddingTop: "4px" }}
          iconSize={8}
          formatter={(value) =>
            LAYER_CONFIG[value] ? t(LAYER_CONFIG[value].labelKey) : value
          }
        />
      </PieChart>
    </ResponsiveContainer>
  );
}