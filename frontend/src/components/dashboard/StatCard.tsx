import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string;
  sublabel?: string;
  icon: React.ComponentType<{ className?: string }>;
  trend?: {
    value: number;      // 百分比变化，如 0.15 表示 +15%
    direction: "up" | "down" | "neutral";
  };
  color?: "default" | "green" | "blue" | "amber" | "red";
}

const COLOR_MAP = {
  default: "text-foreground",
  green: "text-green-600 dark:text-green-400",
  blue: "text-blue-600 dark:text-blue-400",
  amber: "text-amber-600 dark:text-amber-400",
  red: "text-red-600 dark:text-red-400",
};

export function StatCard({
  label,
  value,
  sublabel,
  icon: Icon,
  trend,
  color = "default",
}: StatCardProps) {
  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </div>
          <div className={cn("text-2xl font-semibold", COLOR_MAP[color])}>
            {value}
          </div>
          {sublabel && (
            <div className="text-[11px] text-muted-foreground">{sublabel}</div>
          )}
          {trend && (
            <div
              className={cn(
                "text-[11px]",
                trend.direction === "up"
                  ? "text-green-600 dark:text-green-400"
                  : trend.direction === "down"
                    ? "text-red-600 dark:text-red-400"
                    : "text-muted-foreground"
              )}
            >
              {trend.direction === "up" ? "↑" : trend.direction === "down" ? "↓" : "·"}{" "}
              {(trend.value * 100).toFixed(1)}%
            </div>
          )}
        </div>
        <Icon className={cn("h-5 w-5 shrink-0 opacity-60", COLOR_MAP[color])} />
      </div>
    </div>
  );
}