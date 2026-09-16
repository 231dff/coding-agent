import { Sun, Moon, Monitor } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import type { ThemeMode } from "@/stores/themeStore";

const OPTIONS: Array<{
  mode: ThemeMode;
  icon: React.ComponentType<{ className?: string }>;
  labelKey: string;
}> = [
  { mode: "light", icon: Sun, labelKey: "settings.themeLight" },
  { mode: "dark", icon: Moon, labelKey: "settings.themeDark" },
  { mode: "system", icon: Monitor, labelKey: "settings.themeSystem" },
];

interface ThemeToggleProps {
  /** 布局：横排 | 竖排 */
  layout?: "horizontal" | "vertical";
}

export function ThemeToggle({ layout = "horizontal" }: ThemeToggleProps) {
  const { t } = useTranslation();
  const { mode, setMode } = useTheme();

  return (
    <div
      className={cn(
        "flex gap-1",
        layout === "horizontal" ? "flex-row" : "flex-col"
      )}
      role="radiogroup"
      aria-label={t("settings.theme")}
    >
      {OPTIONS.map(({ mode: m, icon: Icon, labelKey }) => {
        const active = mode === m;
        return (
          <button
            key={m}
            role="radio"
            aria-checked={active}
            onClick={() => setMode(m)}
            title={t(labelKey)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs transition-colors",
              active
                ? "bg-accent text-white"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{t(labelKey)}</span>
          </button>
        );
      })}
    </div>
  );
}