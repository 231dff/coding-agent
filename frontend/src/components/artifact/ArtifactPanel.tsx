import { useState } from "react";
import {
  FileDiff,
  FolderTree,
  Terminal,
  Gauge,
  ShieldCheck,
  Inbox,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useArtifacts } from "@/hooks/useArtifacts";
import { useSessionStore } from "@/stores/sessionStore";
import { DiffViewer } from "./DiffViewer";
import { FileBrowser } from "./FileBrowser";
import { TerminalOutput } from "./TerminalOutput";
import { ContextUsageBar } from "./ContextUsageBar";
import { FilePreview } from "./FilePreview";
import { ApprovalHistory } from "./ApprovalHistory";

type TabId = "diff" | "files" | "terminal" | "context" | "approvals";

interface TabDef {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: TabDef[] = [
  { id: "diff", label: "Diff", icon: FileDiff },
  { id: "files", label: "文件", icon: FolderTree },
  { id: "terminal", label: "终端", icon: Terminal },
  { id: "context", label: "上下文", icon: Gauge },
  { id: "approvals", label: "审批", icon: ShieldCheck },
];

interface ArtifactPanelProps {
  sessionId?: string;
}

export function ArtifactPanel({ sessionId = "" }: ArtifactPanelProps) {
  const [tab, setTab] = useState<TabId>("diff");
  const [previewPath, setPreviewPath] = useState<string | null>(null);

  const { diffs, terminals } = useArtifacts();
  const messageCount = useSessionStore((s) => s.messages.length);
  const hasAny = messageCount > 0;

  const counts: Record<TabId, number> = {
    diff: diffs.length,
    files: 0,
    terminal: terminals.length,
    context: 0,
    approvals: 0,
  };

  return (
    <div className="flex h-full flex-col">
      {/* Tab 头 */}
      <div className="flex h-12 items-center gap-0.5 overflow-x-auto border-b px-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs transition-colors",
              tab === id
                ? "bg-muted font-medium"
                : "text-muted-foreground hover:bg-muted/50"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{label}</span>
            {counts[id] > 0 && (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] leading-none",
                  tab === id
                    ? "bg-accent/20 text-accent"
                    : "bg-muted text-muted-foreground"
                )}
              >
                {counts[id]}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 overflow-hidden">
        {previewPath && tab === "files" ? (
          <FilePreview path={previewPath} onClose={() => setPreviewPath(null)} />
        ) : (
          <div className="h-full overflow-auto">
            {tab === "diff" && (
              hasAny ? (
                diffs.length > 0 ? (
                  <div className="space-y-2 p-3">
                    {diffs.map((diff) => (
                      <DiffViewer key={diff.id} diff={diff} />
                    ))}
                  </div>
                ) : (
                  <EmptyState text="本次会话暂无文件修改" />
                )
              ) : (
                <EmptyState text="执行任务后，文件修改会显示在这里" />
              )
            )}

            {tab === "files" && (
              <FileBrowser
                onFileClick={(path) => setPreviewPath(path)}
                selectedPath={previewPath ?? undefined}
              />
            )}

            {tab === "terminal" && (
              hasAny ? (
                <TerminalOutput entries={terminals} />
              ) : (
                <EmptyState text="执行任务后，终端输出会显示在这里" />
              )
            )}

            {tab === "context" && <ContextUsageBar sessionId={sessionId} />}

            {tab === "approvals" && <ApprovalHistory sessionId={sessionId} />}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-muted-foreground">
      <Inbox className="h-8 w-8 opacity-40" />
      <span className="text-center text-xs">{text}</span>
    </div>
  );
}