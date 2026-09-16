/** 后端 API 类型定义。与 api/schemas.py 严格对应。 */

// ---------- 请求 ----------

export interface ChatRequest {
    message: string;
    session_id?: string;
    thread_id?: string;
  }
  
  export interface ApproveRequest {
    session_id: string;
    approval_id: string;
    decision: "approve" | "reject" | "edit";
    edited_args?: Record<string, unknown>;
  }
  
  // ---------- 会话 ----------
  
  export interface Session {
    session_id: string;
    index_ready: boolean;
    prefix_stable: boolean;
  }
  
  // ---------- 审批 ----------
  
  export interface ApprovalRecord {
    id: string;
    session_id: string;
    tool_call_id: string;
    tool_name: string;
    args: Record<string, unknown>;
    decision: string;
    edited_args: Record<string, unknown> | null;
    decided_at: number;
    decided_by: string;
  }
  
  export interface ApprovalListResponse {
    records: ApprovalRecord[];
  }
  
  export interface PendingApproval {
    id: string;
    session_id: string;
    tool_call_id: string;
    tool_name: string;
    args: Record<string, unknown>;
    reason: string;
    thread_id: string;
    checkpoint_id: string;
    created_at: number;
  }
  
  export interface PendingApprovalListResponse {
    pending: PendingApproval[];
  }
  
  // ---------- SSE 事件 ----------
  
  export interface TokenEvent {
    type: "token";
    content: string;
    session_id: string;
  }
  
  export interface ToolStartEvent {
    type: "tool_start";
    tool_call_id: string;
    tool_name: string;
    args: Record<string, unknown>;
    timestamp: number;
  }
  
  export interface ToolEndEvent {
    type: "tool_end";
    tool_call_id: string;
    tool_name: string;
    output: string;
    timestamp: number;
  }
  
  export interface ErrorEvent {
    type: "error";
    source: "server" | "tool";
    message: string;
    tool_name?: string;
  }
  
  export interface ApprovalRequiredEvent {
    type: "approval_required";
    session_id: string;
    approval_id: string;
    tool_call_id: string;
    tool_name: string;
    args: Record<string, unknown>;
    reason: string;
    thread_id: string;
    checkpoint_id: string;
    timestamp: number;
  }
  
  export interface DoneEvent {
    type: "done";
    session_id: string;
  }
  
  export type StreamEvent =
    | TokenEvent
    | ToolStartEvent
    | ToolEndEvent
    | ErrorEvent
    | ApprovalRequiredEvent
    | DoneEvent;
  
  // ---------- 指标 ----------
  
  export interface Metrics {
    index: string;
    prefix_stable: boolean;
  }