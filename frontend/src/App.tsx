import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  MessageSquare,
  Search as SearchIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { WorkbenchLayout } from "@/components/layout/WorkbenchLayout";
import { SessionSidebar } from "@/components/layout/SessionSidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ArtifactPanel } from "@/components/artifact/ArtifactPanel";
import { Dashboard } from "@/pages/Dashboard";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { UserMenu } from "@/components/auth/UserMenu";
import { SettingsMenu } from "@/components/settings/SettingsMenu";
import { Toaster } from "@/components/notifications/Toaster";
import { OfflineBanner } from "@/components/common/OfflineBanner";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { CommandPalette } from "@/components/command/CommandPalette";
import { useSessionStore } from "@/stores/sessionStore";
import { useSessions } from "@/hooks/useSessions";
import { useAuth } from "@/hooks/useAuth";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { cn } from "@/lib/utils";

type View = "workbench" | "dashboard";

export default function App() {
  const { t } = useTranslation();
  const [view, setView] = useState<View>("workbench");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const sessionId = useSessionStore((s) => s.sessionId);
  const { initialize, initialized, config } = useAuth();
  const { createSession } = useSessions();

  // 认证初始化
  useEffect(() => {
    void initialize();
  }, [initialize]);

  // 全局快捷键
  useKeyboardShortcuts([
    {
      key: "k",
      meta: true,
      handler: () => setPaletteOpen(true),
    },
    {
      key: "n",
      meta: true,
      handler: () => {
        createSession();
        setView("workbench");
      },
    },
    {
      key: "1",
      meta: true,
      handler: () => setView("workbench"),
    },
    {
      key: "2",
      meta: true,
      handler: () => setView("dashboard"),
    },
  ]);

  if (!initialized && config?.mode !== "disabled") {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-muted-foreground">
          {t("app.loading")}
        </div>
      </div>
    );
  }

  return (
    <>
      <RequireAuth>
        <ErrorBoundary>
          <div className="flex h-full flex-col">
            {/* 离线提示 */}
            <OfflineBanner />

            {/* 顶部导航 */}
            <div className="flex h-10 items-center gap-1 border-b bg-background px-3">
              <span className="mr-3 text-xs font-semibold tracking-wide">
                {t("app.title")}
              </span>

              <NavButton
                active={view === "workbench"}
                onClick={() => setView("workbench")}
                icon={MessageSquare}
              >
                {t("nav.workbench")}
              </NavButton>

              <NavButton
                active={view === "dashboard"}
                onClick={() => setView("dashboard")}
                icon={LayoutDashboard}
              >
                {t("nav.dashboard")}
              </NavButton>

              <div className="ml-auto flex items-center gap-1">
                <button
                  onClick={() => setPaletteOpen(true)}
                  className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title="Cmd/Ctrl+K"
                >
                  <SearchIcon className="h-3 w-3" />
                  <span className="hidden sm:inline">Cmd+K</span>
                </button>
                <SettingsMenu />
                <UserMenu />
              </div>
            </div>

            {/* 主视图 */}
            <div className="flex-1 overflow-hidden">
              <ErrorBoundary>
                {view === "workbench" ? (
                  <WorkbenchLayout
                    sidebar={<SessionSidebar />}
                    main={<ChatPanel />}
                    artifact={<ArtifactPanel sessionId={sessionId} />}
                  />
                ) : (
                  <Dashboard onBack={() => setView("workbench")} />
                )}
              </ErrorBoundary>
            </div>
          </div>
        </ErrorBoundary>
      </RequireAuth>

      {/* 全局浮层 */}
      <Toaster />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onCreateSession={() => {
          createSession();
          setView("workbench");
        }}
        onOpenDashboard={() => setView("dashboard")}
        onOpenSettings={() => {
          // 打开设置菜单：当前通过点击 SettingsMenu 触发，
          // 这里可以扩展为独立设置页
        }}
      />
    </>
  );
}

interface NavButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}

function NavButton({ active, onClick, icon: Icon, children }: NavButtonProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors",
        active
          ? "bg-muted font-medium text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {children}
    </button>
  );
}