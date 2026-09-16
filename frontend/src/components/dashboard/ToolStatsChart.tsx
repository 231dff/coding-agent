import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    Cell,
  } from "recharts";
  
  interface ToolStatsChartProps {
    totals: Record<string, number>;
    height?: number;
    topN?: number;
  }
  
  /** 根据索引生成渐变色 */
  const BAR_COLORS = [
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
    "#f59e0b",
    "#10b981",
    "#06b6d4",
    "#6366f1",
    "#f97316",
    "#14b8a6",
    "#a855f7",
  ];
  
  export function ToolStatsChart({
    totals,
    height = 280,
    topN = 10,
  }: ToolStatsChartProps) {
    const data = Object.entries(totals)
      .sort((a, b) => b[1] - a[1])
      .slice(0, topN)
      .map(([name, count]) => ({ name, count }));
  
    if (data.length === 0) {
      return (
        <div
          className="flex items-center justify-center text-xs text-muted-foreground"
          style={{ height }}
        >
          无工具调用数据
        </div>
      );
    }
  
    // 根据最长名称动态调整左侧宽度
    const maxNameLen = Math.max(...data.map((d) => d.name.length));
    const yWidth = Math.min(140, Math.max(80, maxNameLen * 7));
  
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 24, left: 0, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" horizontal={false} />
          <XAxis
            type="number"
            stroke="currentColor"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            className="text-muted-foreground"
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            stroke="currentColor"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            className="text-muted-foreground"
            width={yWidth}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--color-background)",
              border: "1px solid var(--color-border)",
              borderRadius: "6px",
              fontSize: "11px",
              padding: "6px 10px",
            }}
            formatter={(v) => [Number(v ?? 0), "调用次数"]}
            cursor={{ fill: "var(--color-muted)", opacity: 0.4 }}
          />
          <Bar dataKey="count" radius={[0, 3, 3, 0]}>
            {data.map((_, index) => (
              <Cell key={index} fill={BAR_COLORS[index % BAR_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }