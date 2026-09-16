import { describe, expect, it, beforeEach } from "vitest";
import { useSessionsStore } from "./sessionsStore";

describe("sessionsStore", () => {
  beforeEach(() => {
    useSessionsStore.getState().clearAll();
  });

  it("createSession 创建新会话", () => {
    const id = useSessionsStore.getState().createSession("第一条消息");
    const sessions = useSessionsStore.getState().sessions;
    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe(id);
    expect(sessions[0].title).toBe("第一条消息");
    expect(sessions[0].status).toBe("idle");
    expect(sessions[0].archived).toBe(false);
    expect(sessions[0].pinned).toBe(false);
  });

  it("createSession 无消息时默认标题", () => {
    useSessionsStore.getState().createSession();
    expect(useSessionsStore.getState().sessions[0].title).toBe("新会话");
  });

  it("新创建的会话排在最前面", () => {
    const s1 = useSessionsStore.getState().createSession("A");
    const s2 = useSessionsStore.getState().createSession("B");
    const sessions = useSessionsStore.getState().sessions;
    expect(sessions[0].id).toBe(s2);
    expect(sessions[1].id).toBe(s1);
  });

  it("renameSession 修改标题", () => {
    const id = useSessionsStore.getState().createSession("old");
    useSessionsStore.getState().renameSession(id, "new");
    expect(useSessionsStore.getState().sessions[0].title).toBe("new");
  });

  it("deleteSession 移除", () => {
    const id = useSessionsStore.getState().createSession();
    useSessionsStore.getState().deleteSession(id);
    expect(useSessionsStore.getState().sessions).toHaveLength(0);
  });

  it("archiveSession 切换归档", () => {
    const id = useSessionsStore.getState().createSession();
    useSessionsStore.getState().archiveSession(id, true);
    expect(useSessionsStore.getState().sessions[0].archived).toBe(true);
    useSessionsStore.getState().archiveSession(id, false);
    expect(useSessionsStore.getState().sessions[0].archived).toBe(false);
  });

  it("togglePin 切换置顶", () => {
    const id = useSessionsStore.getState().createSession();
    useSessionsStore.getState().togglePin(id);
    expect(useSessionsStore.getState().sessions[0].pinned).toBe(true);
    useSessionsStore.getState().togglePin(id);
    expect(useSessionsStore.getState().sessions[0].pinned).toBe(false);
  });

  it("setSessionStatus 更新状态", () => {
    const id = useSessionsStore.getState().createSession();
    useSessionsStore.getState().setSessionStatus(id, "running");
    expect(useSessionsStore.getState().sessions[0].status).toBe("running");
  });

  it("touchSession 更新时间和消息数", () => {
    const id = useSessionsStore.getState().createSession();
    const oldUpdated = useSessionsStore.getState().sessions[0].updatedAt;

    // 等一毫秒确保时间戳变化
    const before = Date.now();
    useSessionsStore.getState().touchSession(id, 5);
    const session = useSessionsStore.getState().sessions[0];

    expect(session.updatedAt).toBeGreaterThanOrEqual(before);
    expect(session.messageCount).toBe(5);
    expect(session.updatedAt).toBeGreaterThanOrEqual(oldUpdated);
  });

  it("setSearchQuery + getFiltered 过滤", () => {
    useSessionsStore.getState().createSession("Hello World");
    useSessionsStore.getState().createSession("Another Session");
    useSessionsStore.getState().setSearchQuery("hello");

    const filtered = useSessionsStore.getState().getFiltered();
    expect(filtered).toHaveLength(1);
    expect(filtered[0].title).toBe("Hello World");
  });

  it("搜索大小写不敏感", () => {
    useSessionsStore.getState().createSession("Hello");
    useSessionsStore.getState().setSearchQuery("HELLO");
    expect(useSessionsStore.getState().getFiltered()).toHaveLength(1);
  });

  it("清空搜索返回全部", () => {
    useSessionsStore.getState().createSession("A");
    useSessionsStore.getState().createSession("B");
    useSessionsStore.getState().setSearchQuery("");
    expect(useSessionsStore.getState().getFiltered()).toHaveLength(2);
  });

  it("clearAll 清空所有", () => {
    useSessionsStore.getState().createSession();
    useSessionsStore.getState().createSession();
    useSessionsStore.getState().clearAll();
    expect(useSessionsStore.getState().sessions).toHaveLength(0);
    expect(useSessionsStore.getState().searchQuery).toBe("");
  });
});