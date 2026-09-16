import { useEffect, useMemo, useRef, useState } from "react";
import {
  Search,
  MessageSquarePlus,
  LayoutDashboard,
  Settings,
  Moon,
  Sun,
  Monitor,
  Languages,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useTheme";
import { useLanguage } from "@/hooks/useLanguage";

interface Command {
  id: string;
  label: string;
  description?: string;
  icon: React.ComponentType<{ className?: string }>;
  keywords?: string[];
  handler: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onCreateSession: () => void;
  onOpenDashboard: () => void;
  onOpenSettings: () => void;
}

export function CommandPalette({
  open,
  onClose,
  onCreateSession,
  onOpenDashboard,
  onOpenSettings,
}: CommandPaletteProps) {
  const { t } = useTranslation();
  const { setMode } = useTheme();
  const { setLanguage, current: currentLang } = useLanguage();

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 命令列表
  const commands: Command[] = useMemo(
    () => [
      {
        id: "new-session",
        label: t("palette.newSession"),
        icon: MessageSquarePlus,
        keywords: ["new", "session", "新建"],
        handler: () => {
          onCreateSession();
          onClose();
        },
      },
      {
        id: "dashboard",
        label: t("palette.openDashboard"),
        icon: LayoutDashboard,
        keywords: ["dashboard", "metrics", "仪表盘"],
        handler: () => {
          onOpenDashboard();
          onClose();
        },
      },
      {
        id: "settings",
        label: t("palette.openSettings"),
        icon: Settings,
        keywords: ["settings", "设置"],
        handler: () => {
          onOpenSettings();
          onClose();
        },
      },
      {
        id: "theme-light",
        label: t("palette.themeLight"),
        icon: Sun,
        keywords: ["light", "theme", "浅色"],
        handler: () => {
          setMode("light");
          onClose();
        },
      },
      {
        id: "theme-dark",
        label: t("palette.themeDark"),
        icon: Moon,
        keywords: ["dark", "theme", "深色"],
        handler: () => {
          setMode("dark");
          onClose();
        },
      },
      {
        id: "theme-system",
        label: t("palette.themeSystem"),
        icon: Monitor,
        keywords: ["system", "theme", "系统"],
        handler: () => {
          setMode("system");
          onClose();
        },
      },
      {
        id: "lang-zh",
        label: t("palette.langZh"),
        icon: Languages,
        keywords: ["chinese", "zh", "中文"],
        handler: () => {
          void setLanguage("zh");
          onClose();
        },
      },
      {
        id: "lang-en",
        label: t("palette.langEn"),
        icon: Languages,
        keywords: ["english", "en"],
        handler: () => {
          void setLanguage("en");
          onClose();
        },
      },
    ],
    [t, onCreateSession, onOpenDashboard, onOpenSettings, setMode, setLanguage, onClose]
  );

  // 过滤
  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter((cmd) => {
      if (cmd.label.toLowerCase().includes(q)) return true;
      if (cmd.keywords?.some((k) => k.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [commands, query]);

  // 打开时聚焦 + 重置
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      // 等 DOM 渲染完再 focus
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // 选中项变化时滚动到可见
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector(
      `[data-index="${selectedIndex}"]`
    ) as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex, open]);

  // 键盘导航
  useEffect(() => {
    if (!open) return;

    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const cmd = filtered[selectedIndex];
        if (cmd) cmd.handler();
        return;
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, filtered, selectedIndex, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center bg-black/40 pt-[15vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border bg-popover shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 搜索框 */}
        <div className="flex items-center gap-2 border-b px-3 py-2.5">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder={t("palette.placeholder")}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* 命令列表 */}
        <div ref={listRef} className="max-h-80 overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              {t("palette.noResults")}
            </div>
          ) : (
            filtered.map((cmd, index) => {
              const Icon = cmd.icon;
              const active = index === selectedIndex;
              // 当前语言对应的命令高亮
              const isActiveLang =
                cmd.id === `lang-${currentLang}`;
              return (
                <button
                  key={cmd.id}
                  data-index={index}
                  onClick={() => cmd.handler()}
                  onMouseEnter={() => setSelectedIndex(index)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                    active
                      ? "bg-accent/15 text-accent"
                      : "hover:bg-muted"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1 truncate">{cmd.label}</span>
                  {isActiveLang && (
                    <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[10px] text-accent">
                      current
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* 底部提示 */}
        <div className="flex items-center gap-3 border-t px-3 py-1.5 text-[10px] text-muted-foreground">
          <span>↑↓ {t("palette.navigate")}</span>
          <span>↵ {t("palette.select")}</span>
          <span>Esc {t("palette.close")}</span>
        </div>
      </div>
    </div>
  );
}