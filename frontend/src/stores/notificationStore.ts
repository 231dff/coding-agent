import { create } from "zustand";
import {
  newNotificationId,
  type Notification,
  type NotificationType,
} from "@/types/notification";

interface NotificationState {
  notifications: Notification[];

  push: (
    type: NotificationType,
    title: string,
    options?: {
      description?: string;
      duration?: number;
      action?: Notification["action"];
    }
  ) => string;

  success: (title: string, description?: string) => string;
  error: (title: string, description?: string) => string;
  warning: (title: string, description?: string) => string;
  info: (title: string, description?: string) => string;

  dismiss: (id: string) => void;
  clear: () => void;
}

/** 同时最多显示多少个 toast */
const MAX_VISIBLE = 5;

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],

  push: (type, title, options = {}) => {
    const id = newNotificationId();
    const notification: Notification = {
      id,
      type,
      title,
      description: options.description,
      // 默认 4000ms；error 类默认 6000ms（用户需要更多时间读）
      duration: options.duration ?? (type === "error" ? 6000 : 4000),
      action: options.action,
      createdAt: Date.now(),
    };

    set((state) => {
      const next = [...state.notifications, notification];
      // 超过上限时丢弃最老的
      if (next.length > MAX_VISIBLE) {
        return { notifications: next.slice(next.length - MAX_VISIBLE) };
      }
      return { notifications: next };
    });

    return id;
  },

  success: (title, description) =>
    get().push("success", title, { description }),

  error: (title, description) =>
    get().push("error", title, { description }),

  warning: (title, description) =>
    get().push("warning", title, { description }),

  info: (title, description) =>
    get().push("info", title, { description }),

  dismiss: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),

  clear: () => set({ notifications: [] }),
}));