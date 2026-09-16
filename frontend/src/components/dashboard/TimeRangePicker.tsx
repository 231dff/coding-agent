import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { TimeRange } from "@/types/metrics";

interface TimeRangePickerProps {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
  disabled?: boolean;
}

const RANGES: TimeRange[] = ["1h", "24h", "7d", "30d", "all"];

export function TimeRangePicker({
  value,
  onChange,
  disabled,
}: TimeRangePickerProps) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
      {RANGES.map((range) => (
        <button
          key={range}
          onClick={() => onChange(range)}
          disabled={disabled}
          className={cn(
            "rounded px-2.5 py-1 text-xs transition-colors",
            value === range
              ? "bg-accent text-white"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
            disabled && "cursor-not-allowed opacity-50"
          )}
        >
          {t(`dashboard.range.${range}`)}
        </button>
      ))}
    </div>
  );
}