import { useQuery } from "@tanstack/react-query";
import { X, Loader2, Copy } from "lucide-react";
import { fetchFileContent } from "@/api/files";

interface FilePreviewProps {
  path: string;
  onClose: () => void;
}

export function FilePreview({ path, onClose }: FilePreviewProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["file-content", path],
    queryFn: () => fetchFileContent(path),
    enabled: !!path,
  });

  return (
    <div className="flex h-full flex-col">
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
        <span className="flex-1 truncate font-mono text-xs">{path}</span>
        {data && (
          <button
            onClick={() => void navigator.clipboard.writeText(data.content)}
            className="rounded p-0.5 hover:bg-muted"
            title="复制"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          onClick={onClose}
          className="rounded p-0.5 hover:bg-muted"
          title="关闭"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="flex items-center justify-center p-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中...
          </div>
        )}
        {error && (
          <div className="p-3 text-xs text-destructive">
            加载失败: {error instanceof Error ? error.message : String(error)}
          </div>
        )}
        {data && (
          <pre className="whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed">
            {data.content}
          </pre>
        )}
      </div>
    </div>
  );
}