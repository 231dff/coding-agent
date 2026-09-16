import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";
import "highlight.js/styles/github-dark.css";

interface StreamingMarkdownProps {
  content: string;
  isStreaming: boolean;
  className?: string;
}

/**
 * 流式 Markdown 渲染。
 *
 * 关键处理：
 * 1. 未闭合的代码块：流式过程中，``` 数量是奇数时，末尾自动补一个 ```
 *    否则 ReactMarkdown 会把剩余内容当作代码块处理，渲染错乱。
 * 2. 用 memo 避免稳定内容重新解析。
 */
export const StreamingMarkdown = memo(function StreamingMarkdown({
  content,
  isStreaming,
  className,
}: StreamingMarkdownProps) {
  const safeContent = useMemo(() => {
    if (!isStreaming) return content;

    // 统计未转义的 ``` 数量
    const fenceMatches = content.match(/^```/gm);
    const fenceCount = fenceMatches ? fenceMatches.length : 0;

    // 奇数个 → 缺少闭合，补上
    if (fenceCount % 2 === 1) {
      return content + "\n```";
    }
    return content;
  }, [content, isStreaming]);

  return (
    <div
      className={cn(
        "prose prose-sm dark:prose-invert max-w-none",
        "prose-pre:bg-muted prose-pre:text-foreground",
        "prose-code:before:content-none prose-code:after:content-none",
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // 代码块：添加语言标签和复制按钮占位
          pre: ({ children, ...props }) => (
            <pre
              {...props}
              className="relative overflow-x-auto rounded-md bg-muted p-3 text-xs leading-relaxed"
            >
              {children}
            </pre>
          ),
          // 链接：新窗口打开
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {safeContent}
      </ReactMarkdown>

      {/* 流式光标 */}
      {isStreaming && (
        <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-text-bottom" />
      )}
    </div>
  );
});