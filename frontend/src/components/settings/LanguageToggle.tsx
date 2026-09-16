import { Languages, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/hooks/useLanguage";
import { cn } from "@/lib/utils";

interface LanguageToggleProps {
  /** 显示模式：按钮组 | 下拉菜单 */
  variant?: "group" | "menu";
}

export function LanguageToggle({ variant = "group" }: LanguageToggleProps) {
  const { t } = useTranslation();
  const { current, available, labels, setLanguage } = useLanguage();

  if (variant === "group") {
    return (
      <div
        className="flex gap-1"
        role="radiogroup"
        aria-label={t("settings.language")}
      >
        {available.map((lang) => {
          const active = current === lang;
          return (
            <button
              key={lang}
              role="radio"
              aria-checked={active}
              onClick={() => void setLanguage(lang)}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-xs transition-colors",
                active
                  ? "bg-accent text-white"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {labels[lang]}
            </button>
          );
        })}
      </div>
    );
  }

  // menu 模式：下拉列表
  return (
    <div className="space-y-0.5">
      {available.map((lang) => {
        const active = current === lang;
        return (
          <button
            key={lang}
            onClick={() => void setLanguage(lang)}
            className={cn(
              "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors",
              active
                ? "bg-accent/10 text-accent"
                : "hover:bg-muted"
            )}
          >
            <Languages className="h-3 w-3" />
            <span className="flex-1">{labels[lang]}</span>
            {active && <Check className="h-3 w-3" />}
          </button>
        );
      })}
    </div>
  );
}