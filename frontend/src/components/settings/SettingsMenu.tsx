import { useState, useRef, useEffect } from "react";
import { Settings, Palette, Languages, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ThemeToggle } from "./ThemeToggle";
import { LanguageToggle } from "./LanguageToggle";
import { cn } from "@/lib/utils";

interface SettingsMenuProps {
  /** 触发按钮的样式 */
  variant?: "icon" | "button";
}

export function SettingsMenu({ variant = "icon" }: SettingsMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1.5 rounded-md transition-colors",
          variant === "icon"
            ? "p-1.5 hover:bg-muted"
            : "border px-2.5 py-1.5 text-xs hover:bg-muted"
        )}
        title={t("settings.title")}
      >
        <Settings className="h-3.5 w-3.5" />
        {variant === "button" && <span>{t("settings.title")}</span>}
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 w-72 rounded-md border bg-popover p-3 shadow-md">
          {/* 头部 */}
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-medium">{t("settings.title")}</span>
            <button
              onClick={() => setOpen(false)}
              className="rounded p-0.5 hover:bg-muted"
            >
              <X className="h-3 w-3" />
            </button>
          </div>

          {/* 主题 */}
          <div className="mb-3">
            <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <Palette className="h-3 w-3" />
              {t("settings.theme")}
            </div>
            <ThemeToggle />
          </div>

          {/* 语言 */}
          <div>
            <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <Languages className="h-3 w-3" />
              {t("settings.language")}
            </div>
            <LanguageToggle />
          </div>
        </div>
      )}
    </div>
  );
}