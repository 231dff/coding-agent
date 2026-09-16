export type NotificationType = "success" | "error" | "warning" | "info";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  description?: string;
  /** 毫秒。0 表示不自动关闭 */
  duration?: number;
  /** 可选的 action 按钮 */
  action?: {
    label: string;
    onClick: () => void;
  };
  createdAt: number;
}

/** 生成唯一 ID */
export function newNotificationId(): string {
  return `notif-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}