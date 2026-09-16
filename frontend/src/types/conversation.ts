/**
 * 对话消息模型。
 *
 * 一条 Message 对应一次 user 或 assistant 的回合。
 * assistant 消息内部可以包含多个 ToolCall（工具调用卡片）。
 */

export type MessageRole = "user" | "assistant";
export type MessageStatus = "streaming" | "done" | "error";
export type ToolCallStatus = "running" | "done" | "error" | "pending_approval";

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  output?: string;
  status: ToolCallStatus;
  startTime: number;
  endTime?: number;
  error?: string;
}

/** 待审批请求（挂在 assistant 消息上） */
export interface PendingApprovalInfo {
  approvalId: string;
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
  reason: string;
  threadId: string;
  checkpointId: string;
  createdAt: number;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  toolCalls: ToolCall[];
  pendingApproval?: PendingApprovalInfo;
  createdAt: number;
  error?: string;
}

export function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function createUserMessage(content: string): Message {
  return {
    id: newId(),
    role: "user",
    content,
    status: "done",
    toolCalls: [],
    createdAt: Date.now(),
  };
}

export function createAssistantMessage(): Message {
  return {
    id: newId(),
    role: "assistant",
    content: "",
    status: "streaming",
    toolCalls: [],
    createdAt: Date.now(),
  };
}