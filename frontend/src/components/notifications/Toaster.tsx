import { createPortal } from "react-dom";
import { useNotificationStore } from "@/stores/notificationStore";
import { Toast } from "./Toast";

/**
 * Toast 容器。挂到 body 上，避免被父容器的 overflow 裁切。
 *
 * 位置：右上角，垂直堆叠。
 */
export function Toaster() {
  const notifications = useNotificationStore((s) => s.notifications);
  const dismiss = useNotificationStore((s) => s.dismiss);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="pointer-events-none fixed right-4 top-14 z-[100] flex flex-col gap-2"
      aria-live="polite"
      aria-atomic="true"
    >
      {notifications.map((n) => (
        <Toast
          key={n.id}
          notification={n}
          onDismiss={() => dismiss(n.id)}
        />
      ))}
    </div>,
    document.body
  );
}