import { useMemo } from "react";
import { Inbox, Archive } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SessionItem } from "./SessionItem";
import {
  groupSession,
  type SessionGroup,
  type SessionMeta,
} from "@/types/session";

interface SessionListProps {
  sessions: SessionMeta[];
  currentSessionId: string;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onTogglePin: (id: string) => void;
  onToggleArchive: (id: string, archived: boolean) => void;
}

const GROUP_ORDER: SessionGroup[] = ["today", "this_week", "earlier", "archived"];

const GROUP_LABEL_KEYS: Record<SessionGroup, string> = {
  today: "sidebar.groups.today",
  this_week: "sidebar.groups.thisWeek",
  earlier: "sidebar.groups.earlier",
  archived: "sidebar.groups.archived",
};

export function SessionList({
  sessions,
  currentSessionId,
  onSelect,
  onRename,
  onDelete,
  onTogglePin,
  onToggleArchive,
}: SessionListProps) {
  const { t } = useTranslation();

  const grouped = useMemo(() => {
    const result: Record<SessionGroup, SessionMeta[]> = {
      today: [],
      this_week: [],
      earlier: [],
      archived: [],
    };

    for (const s of sessions) {
      result[groupSession(s)].push(s);
    }

    for (const key of Object.keys(result) as SessionGroup[]) {
      result[key].sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        return b.updatedAt - a.updatedAt;
      });
    }

    return result;
  }, [sessions]);

  const totalVisible = sessions.filter((s) => !s.archived).length;

  if (totalVisible === 0 && grouped.archived.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-muted-foreground">
        <Inbox className="h-8 w-8 opacity-40" />
        <span className="text-xs">{t("sidebar.noSessions")}</span>
        <span className="text-[10px] opacity-70">{t("sidebar.noSessionsHint")}</span>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-2">
      {GROUP_ORDER.map((group) => {
        const items = grouped[group];
        if (items.length === 0) return null;

        return (
          <div key={group}>
            <div className="mb-1 flex items-center gap-1 px-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {group === "archived" && <Archive className="h-2.5 w-2.5" />}
              {t(GROUP_LABEL_KEYS[group])}
              <span className="text-muted-foreground/60">
                ({items.length})
              </span>
            </div>
            <div className="space-y-0.5">
              {items.map((s) => (
                <SessionItem
                  key={s.id}
                  session={s}
                  isActive={s.id === currentSessionId}
                  onSelect={() => onSelect(s.id)}
                  onRename={(title) => onRename(s.id, title)}
                  onDelete={() => onDelete(s.id)}
                  onTogglePin={() => onTogglePin(s.id)}
                  onToggleArchive={() => onToggleArchive(s.id, !s.archived)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}