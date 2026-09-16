import { useState, useRef, useEffect } from "react";
import {
  MessageSquare,
  MoreVertical,
  Pin,
  PinOff,
  Pencil,
  Archive,
  ArchiveRestore,
  Trash2,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { SessionMeta } from "@/types/session";

interface SessionItemProps {
  session: SessionMeta;
  isActive: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
  onTogglePin: () => void;
  onToggleArchive: () => void;
}

function relativeTime(ts: number, t: (k: string, o?: Record<string, unknown>) => string): string {
  const diff = Date.now() - ts;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diff < minute) return t("time.justNow");
  if (diff < hour) return t("time.minutesAgo", { count: Math.floor(diff / minute) });
  if (diff < day) return t("time.hoursAgo", { count: Math.floor(diff / hour) });
  if (diff < 7 * day) return t("time.daysAgo", { count: Math.floor(diff / day) });

  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function SessionItem({
  session,
  isActive,
  onSelect,
  onRename,
  onDelete,
  onTogglePin,
  onToggleArchive,
}: SessionItemProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(session.title);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const menuRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setConfirmDelete(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function commitRename() {
    const title = draftTitle.trim();
    if (title && title !== session.title) {
      onRename(title);
    } else {
      setDraftTitle(session.title);
    }
    setEditing(false);
  }

  const statusIcon = {
    idle: <MessageSquare className="h-3.5 w-3.5 shrink-0" />,
    running: <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />,
    error: <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />,
  }[session.status];

  return (
    <div
      className={cn(
        "group relative flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
        isActive ? "bg-accent/15 text-accent" : "hover:bg-muted"
      )}
      onClick={() => {
        if (!editing && !menuOpen) onSelect();
      }}
    >
      {statusIcon}

      {editing ? (
        <input
          ref={inputRef}
          value={draftTitle}
          onChange={(e) => setDraftTitle(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") {
              setDraftTitle(session.title);
              setEditing(false);
            }
          }}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 rounded border border-accent bg-background px-1 py-0.5 text-xs outline-none"
        />
      ) : (
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            {session.pinned && (
              <Pin className="h-2.5 w-2.5 shrink-0 text-amber-500" />
            )}
            <span className="truncate font-medium">{session.title}</span>
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span>{relativeTime(session.updatedAt, t as never)}</span>
            {session.messageCount > 0 && (
              <>
                <span>·</span>
                <span>{t("sidebar.item.messages", { count: session.messageCount })}</span>
              </>
            )}
          </div>
        </div>
      )}

      <button
        onClick={(e) => {
          e.stopPropagation();
          setMenuOpen((v) => !v);
        }}
        className={cn(
          "rounded p-0.5 transition-opacity",
          "hover:bg-background/80",
          menuOpen || isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        )}
      >
        <MoreVertical className="h-3.5 w-3.5" />
      </button>

      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-1 top-8 z-20 w-36 rounded-md border bg-popover p-1 shadow-md"
          onClick={(e) => e.stopPropagation()}
        >
          <MenuItem
            icon={Pencil}
            label={t("sidebar.item.menu.rename")}
            onClick={() => {
              setMenuOpen(false);
              setEditing(true);
            }}
          />
          <MenuItem
            icon={session.pinned ? PinOff : Pin}
            label={session.pinned
              ? t("sidebar.item.menu.unpin")
              : t("sidebar.item.menu.pin")}
            onClick={() => {
              onTogglePin();
              setMenuOpen(false);
            }}
          />
          <MenuItem
            icon={session.archived ? ArchiveRestore : Archive}
            label={session.archived
              ? t("sidebar.item.menu.unarchive")
              : t("sidebar.item.menu.archive")}
            onClick={() => {
              onToggleArchive();
              setMenuOpen(false);
            }}
          />
          <div className="my-1 h-px bg-border" />
          {confirmDelete ? (
            <div className="space-y-1 p-1">
              <div className="text-[10px] text-muted-foreground">
                {t("sidebar.item.menu.confirmDelete")}
              </div>
              <div className="flex gap-1">
                <button
                  onClick={() => {
                    onDelete();
                    setMenuOpen(false);
                  }}
                  className="flex-1 rounded bg-destructive px-1.5 py-0.5 text-[10px] text-white hover:opacity-90"
                >
                  {t("sidebar.item.menu.delete")}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="flex-1 rounded border px-1.5 py-0.5 text-[10px] hover:bg-muted"
                >
                  {t("app.cancel")}
                </button>
              </div>
            </div>
          ) : (
            <MenuItem
              icon={Trash2}
              label={t("sidebar.item.menu.delete")}
              danger
              onClick={() => setConfirmDelete(true)}
            />
          )}
        </div>
      )}
    </div>
  );
}

interface MenuItemProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  danger?: boolean;
}

function MenuItem({ icon: Icon, label, onClick, danger }: MenuItemProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors",
        danger
          ? "text-destructive hover:bg-destructive/10"
          : "hover:bg-muted"
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}