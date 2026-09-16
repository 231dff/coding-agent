/**
 * 会话数据类型。
 *
 * 与后端 SessionInfo 对应，但增加了前端特有的字段（title、updatedAt 等）。
 */

export interface SessionMeta {
    /** 唯一 ID */
    id: string;
    /** 显示标题，默认取首条用户消息的前 30 字 */
    title: string;
    /** 创建时间（ms 时间戳） */
    createdAt: number;
    /** 最后活跃时间（ms 时间戳） */
    updatedAt: number;
    /** 消息数量 */
    messageCount: number;
    /** 会话状态 */
    status: "idle" | "running" | "error";
    /** 是否归档 */
    archived: boolean;
    /** 是否置顶 */
    pinned: boolean;
  }
  
  export type SessionGroup = "today" | "this_week" | "earlier" | "archived";
  
  /** 按时间分组 */
  export function groupSession(session: SessionMeta): SessionGroup {
    if (session.archived) return "archived";
  
    const now = Date.now();
    const diff = now - session.updatedAt;
    const oneDay = 24 * 60 * 60 * 1000;
  
    if (diff < oneDay) return "today";
    if (diff < 7 * oneDay) return "this_week";
    return "earlier";
  }
  
  /** 分组显示名称 */
  export const GROUP_LABELS: Record<SessionGroup, string> = {
    today: "今天",
    this_week: "本周",
    earlier: "更早",
    archived: "已归档",
  };
  
  /** 从消息内容生成标题 */
  export function deriveTitle(firstMessage: string): string {
    const trimmed = firstMessage.trim().replace(/\s+/g, " ");
    if (trimmed.length <= 30) return trimmed;
    return trimmed.slice(0, 30) + "...";
  }