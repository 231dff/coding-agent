import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FileText,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchTree, type FileEntry } from "@/api/files";

interface FileTreeNodeProps {
  entry: FileEntry;
  depth: number;
  onFileClick: (path: string) => void;
  selectedPath?: string;
}

function FileTreeNode({ entry, depth, onFileClick, selectedPath }: FileTreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const isDir = entry.type === "dir";

  const { data, isLoading } = useQuery({
    queryKey: ["tree", entry.path],
    queryFn: () => fetchTree(entry.path),
    enabled: isDir && expanded,
    staleTime: 30_000,
  });

  const isSelected = selectedPath === entry.path;

  return (
    <div>
      <button
        onClick={() => {
          if (isDir) {
            setExpanded((v) => !v);
          } else {
            onFileClick(entry.path);
          }
        }}
        className={cn(
          "flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-xs",
          "hover:bg-muted",
          isSelected && "bg-accent/10 text-accent"
        )}
        style={{ paddingLeft: `${depth * 12 + 6}px` }}
      >
        {isDir ? (
          <>
            {isLoading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : expanded ? (
              <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
            )}
            <Folder className="h-3 w-3 shrink-0 text-blue-500" />
          </>
        ) : (
          <>
            <span className="w-3" />
            <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
          </>
        )}
        <span className="truncate font-mono">{entry.name}</span>
      </button>

      {isDir && expanded && data && (
        <div>
          {data.entries.map((child) => (
            <FileTreeNode
              key={child.path}
              entry={child}
              depth={depth + 1}
              onFileClick={onFileClick}
              selectedPath={selectedPath}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface FileBrowserProps {
  onFileClick: (path: string) => void;
  selectedPath?: string;
}

export function FileBrowser({ onFileClick, selectedPath }: FileBrowserProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["tree", "."],
    queryFn: () => fetchTree("."),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-6 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        加载中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-xs text-destructive">
        加载失败: {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }

  if (!data || data.entries.length === 0) {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        (空目录)
      </div>
    );
  }

  return (
    <div className="py-1">
      {data.entries.map((entry) => (
        <FileTreeNode
          key={entry.path}
          entry={entry}
          depth={0}
          onFileClick={onFileClick}
          selectedPath={selectedPath}
        />
      ))}
    </div>
  );
}