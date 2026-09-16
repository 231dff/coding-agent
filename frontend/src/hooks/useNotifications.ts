import { useNotificationStore } from "@/stores/notificationStore";

/**
 * 通知 hook。便捷调用。
 *
 * 用法：
 *   const notify = useNotifications();
 *   notify.success("已保存", "修改已应用");
 *   notify.error("加载失败", err.message);
 */
export function useNotifications() {
  const store = useNotificationStore();

  return {
    push: store.push,
    success: store.success,
    error: store.error,
    warning: store.warning,
    info: store.info,
    dismiss: store.dismiss,
    clear: store.clear,
  };
}