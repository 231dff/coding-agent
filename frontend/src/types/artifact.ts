/**
 * 产物模型。
 *
 * 从消息历史中提取，供右侧 ArtifactPanel 展示。
 * 每次工具调用可能产生 0 或 1 个产物。
 */

export interface DiffArtifact {
    kind: "diff";
    id: string;
    file: string;
    oldValue: string;
    newValue: string;
    toolCallId: string;
    toolName: string;
    timestamp: number;
    language?: string;
  }
  
  export interface TerminalArtifact {
    kind: "terminal";
    id: string;
    command: string;
    output: string;
    status: "running" | "done" | "error";
    exitCode?: number;
    toolCallId: string;
    timestamp: number;
  }
  
  export interface FileArtifact {
    kind: "file";
    id: string;
    path: string;
    toolCallId: string;
    timestamp: number;
  }
  
  export type Artifact = DiffArtifact | TerminalArtifact | FileArtifact;
  
  /** 从文件扩展名推断语言 */
  export function inferLanguage(filePath: string): string | undefined {
    const ext = filePath.split(".").pop()?.toLowerCase();
    const map: Record<string, string> = {
      py: "python",
      ts: "typescript",
      tsx: "tsx",
      js: "javascript",
      jsx: "jsx",
      json: "json",
      md: "markdown",
      yaml: "yaml",
      yml: "yaml",
      toml: "toml",
      css: "css",
      html: "html",
      sh: "bash",
    };
    return ext ? map[ext] : undefined;
  }