import { describe, expect, it, beforeEach } from "vitest";
import { useNotificationStore } from "./notificationStore";

describe("notificationStore", () => {
  beforeEach(() => {
    useNotificationStore.getState().clear();
  });

  it("push 添加通知", () => {
    const id = useNotificationStore
      .getState()
      .push("success", "标题", { description: "描述" });

    const notifications = useNotificationStore.getState().notifications;
    expect(notifications).toHaveLength(1);
    expect(notifications[0].id).toBe(id);
    expect(notifications[0].type).toBe("success");
    expect(notifications[0].title).toBe("标题");
    expect(notifications[0].description).toBe("描述");
  });

  it("success/error/warning/info 是 push 的快捷方式", () => {
    const store = useNotificationStore.getState();
    store.success("s");
    store.error("e");
    store.warning("w");
    store.info("i");

    const types = useNotificationStore
      .getState()
      .notifications.map((n) => n.type);
    expect(types).toEqual(["success", "error", "warning", "info"]);
  });

  it("error 类型默认 6 秒，其他 4 秒", () => {
    const store = useNotificationStore.getState();
    store.success("s");
    store.error("e");

    const notifications = useNotificationStore.getState().notifications;
    expect(notifications[0].duration).toBe(4000);
    expect(notifications[1].duration).toBe(6000);
  });

  it("自定义 duration 覆盖默认值", () => {
    useNotificationStore.getState().push("success", "t", { duration: 1000 });
    expect(useNotificationStore.getState().notifications[0].duration).toBe(1000);
  });

  it("dismiss 移除指定通知", () => {
    const store = useNotificationStore.getState();
    const id1 = store.success("a");
    const id2 = store.success("b");
    store.dismiss(id1);

    const notifications = useNotificationStore.getState().notifications;
    expect(notifications).toHaveLength(1);
    expect(notifications[0].id).toBe(id2);
  });

  it("超过 5 条时挤掉最老的", () => {
    const store = useNotificationStore.getState();
    for (let i = 0; i < 7; i++) {
      store.success(`n${i}`);
    }

    const notifications = useNotificationStore.getState().notifications;
    expect(notifications).toHaveLength(5);
    expect(notifications[0].title).toBe("n2");
    expect(notifications[4].title).toBe("n6");
  });

  it("clear 清空所有", () => {
    const store = useNotificationStore.getState();
    store.success("a");
    store.success("b");
    store.clear();
    expect(useNotificationStore.getState().notifications).toHaveLength(0);
  });

  it("每个通知有唯一 id", () => {
    const store = useNotificationStore.getState();
    const ids = new Set<string>();
    for (let i = 0; i < 10; i++) {
      ids.add(store.success(`n${i}`));
    }
    expect(ids.size).toBe(10);
  });
});