import { useState } from "react";
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued";
import { FileCode2, ChevronDown, ChevronRight } from "lucide-react";
import type { DiffArtifact } from "@/types/artifact";

interface DiffViewerProps {
  diff: DiffArtifact;
}

export function DiffViewer({ diff }: DiffViewerProps) {
  const [splitView, setSplitView] = useState(true);
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="rounded-md border bg-background">
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="rounded p-0.5 hover:bg-muted"
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </button>

        <FileCode2 className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="flex-1 truncate font-mono text-xs">{diff.file}</span>

        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {diff.toolName}
        </span>

        <button
          onClick={() => setSplitView((v) => !v)}
          className="rounded px-1.5 py-0.5 text-[10px] hover:bg-muted"
          title={splitView ? "切换为统一视图" : "切换为并排视图"}
        >
          {splitView ? "并排" : "统一"}
        </button>
      </div>

      {/* Diff 主体 */}
      {expanded && (
        <div className="overflow-auto text-xs">
          <ReactDiffViewer
            oldValue={diff.oldValue}
            newValue={diff.newValue}
            splitView={splitView}
            compareMethod={DiffMethod.WORDS}
            leftTitle="修改前"
            rightTitle="修改后"
            useDarkTheme={false}
            styles={{
              variables: {
                light: {
                  diffViewerBackground: "transparent",
                  diffViewerColor: "var(--color-foreground)",
                  addedBackground: "rgba(34, 197, 94, 0.1)",
                  addedColor: "rgb(21, 128, 61)",
                  removedBackground: "rgba(239, 68, 68, 0.1)",
                  removedColor: "rgb(185, 28, 28)",
                  wordAddedBackground: "rgba(34, 197, 94, 0.25)",
                  wordRemovedBackground: "rgba(239, 68, 68, 0.25)",
                  gutterBackground: "transparent",
                  gutterColor: "var(--color-muted-foreground)",
                },
              },
              contentText: {
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
              },
            }}
          />
        </div>
      )}
    </div>
  );
}