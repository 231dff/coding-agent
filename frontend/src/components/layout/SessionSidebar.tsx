import { useMemo } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSessions } from "@/hooks/useSessions";
import { useSessionsStore } from "@/stores/sessionsStore";
import { useSessionStore } from "@/stores/sessionStore";
import { SessionSearch } from "./SessionSearch";
import { SessionList } from "./SessionList";

export function SessionSidebar() {
  const { t } = useTranslation();
  const {
    searchQuery,
    setSearchQuery,
    switchSession,
    createSession,
    removeSession,
    renameSession,
    archiveSession,
    togglePin,
  } = useSessions();

  const sessions = useSessionsStore((s) => s.sessions);
  const activeId = useSessionStore((s) => s.sessionId);

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q)
    );
  }, [sessions, searchQuery]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b p-2">
        <button
          onClick={createSession}
          className="flex flex-1 items-center justify-center gap-1 rounded-md border border-dashed py-1.5 text-xs transition-colors hover:border-accent hover:bg-accent/5 hover:text-accent"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("sidebar.newSession")}
        </button>
      </div>

      <div className="border-b p-2">
        <SessionSearch value={searchQuery} onChange={setSearchQuery} />
      </div>

      <div className="flex-1 overflow-y-auto">
        <SessionList
          sessions={filtered}
          currentSessionId={activeId}
          onSelect={switchSession}
          onRename={renameSession}
          onDelete={removeSession}
          onTogglePin={togglePin}
          onToggleArchive={archiveSession}
        />
      </div>

      <div className="border-t px-3 py-1.5 text-[10px] text-muted-foreground">
        {t("sidebar.totalSessions", { count: sessions.length })}
      </div>
    </div>
  );
}