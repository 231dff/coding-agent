import { useMemo } from "react";
import { useSessionStore } from "@/stores/sessionStore";
import {
  inferLanguage,
  type Artifact,
  type DiffArtifact,
  type FileArtifact,
  type TerminalArtifact,
} from "@/types/artifact";
import type { ToolCall } from "@/types/conversation";

/** 编辑类工具名 */
const EDIT_TOOLS = new Set([
  "edit_file",
  "tx_edit",
  "write_file",
  "tx_write",
  "apply_patch",
]);

/** 终端类工具名 */
const TERMINAL_TOOLS = new Set([
  "execute",
  "run_tests",
  "sandbox_grep",
]);

/** 读取类工具名 */
const READ_TOOLS = new Set([
  "read_file",
  "sandbox_read",
]);

function extractFromToolCall(tc: ToolCall): Artifact | null {
  // 编辑工具 → Diff
  if (EDIT_TOOLS.has(tc.name)) {
    const { path, old_string, new_string, content } = tc.args as {
      path?: string;
      old_string?: string;
      new_string?: string;
      content?: string;
    };

    if (path && (old_string !== undefined || content !== undefined)) {
      return {
        kind: "diff",
        id: `diff-${tc.id}`,
        file: path,
        oldValue: old_string ?? "",
        newValue: new_string ?? content ?? "",
        toolCallId: tc.id,
        toolName: tc.name,
        timestamp: tc.startTime,
        language: inferLanguage(path),
      } satisfies DiffArtifact;
    }
  }

  // 终端工具 → Terminal
  if (TERMINAL_TOOLS.has(tc.name)) {
    const { command, pattern, path } = tc.args as {
      command?: string;
      pattern?: string;
      path?: string;
    };

    let displayCommand = command ?? "";
    if (!displayCommand && pattern) {
      displayCommand = `grep "${pattern}" ${path ?? "."}`;
    }

    return {
      kind: "terminal",
      id: `term-${tc.id}`,
      command: displayCommand,
      output: tc.output ?? tc.error ?? "",
      status: tc.status === "running" ? "running"
        : tc.status === "error" ? "error"
        : "done",
      toolCallId: tc.id,
      timestamp: tc.startTime,
    } satisfies TerminalArtifact;
  }

  // 读取工具 → File 引用
  if (READ_TOOLS.has(tc.name)) {
    const { path } = tc.args as { path?: string };
    if (path) {
      return {
        kind: "file",
        id: `file-${tc.id}`,
        path,
        toolCallId: tc.id,
        timestamp: tc.startTime,
      } satisfies FileArtifact;
    }
  }

  return null;
}

/**
 * 从当前会话的所有消息中提取产物列表。
 *
 * 按时间倒序排列（最新的在前），方便前端默认展示最近产物。
 */
export function useArtifacts(): {
  diffs: DiffArtifact[];
  terminals: TerminalArtifact[];
  files: FileArtifact[];
  all: Artifact[];
} {
  const messages = useSessionStore((s) => s.messages);

  return useMemo(() => {
    const diffs: DiffArtifact[] = [];
    const terminals: TerminalArtifact[] = [];
    const files: FileArtifact[] = [];

    for (const msg of messages) {
      for (const tc of msg.toolCalls) {
        const artifact = extractFromToolCall(tc);
        if (!artifact) continue;

        if (artifact.kind === "diff") diffs.push(artifact);
        else if (artifact.kind === "terminal") terminals.push(artifact);
        else if (artifact.kind === "file") files.push(artifact);
      }
    }

    // 最新的在前
    diffs.sort((a, b) => b.timestamp - a.timestamp);
    terminals.sort((a, b) => b.timestamp - a.timestamp);
    files.sort((a, b) => b.timestamp - a.timestamp);

    return {
      diffs,
      terminals,
      files,
      all: [...diffs, ...terminals, ...files].sort(
        (a, b) => b.timestamp - a.timestamp
      ),
    };
  }, [messages]);
}