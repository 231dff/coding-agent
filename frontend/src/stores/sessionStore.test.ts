import { describe, expect, it, beforeEach } from "vitest";
import { useSessionStore } from "./sessionStore";

describe("sessionStore", () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
    useSessionStore.getState().setSessionId("");
  });

  it("初始状态", () => {
    const state = useSessionStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.isStreaming).toBe(false);
    expect(state.error).toBeNull();
    expect(state.sessionId).toBe("");
  });

  it("appendUserMessage 添加用户消息", () => {
    const id = useSessionStore.getState().appendUserMessage("hello");
    const messages = useSessionStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe(id);
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toBe("hello");
    expect(messages[0].status).toBe("done");
  });

  it("startAssistantMessage 创建流式占位", () => {
    const id = useSessionStore.getState().startAssistantMessage();
    const messages = useSessionStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe(id);
    expect(messages[0].role).toBe("assistant");
    expect(messages[0].status).toBe("streaming");
    expect(messages[0].content).toBe("");
  });

  it("appendToken 累积 token", () => {
    const id = useSessionStore.getState().startAssistantMessage();
    const store = useSessionStore.getState();
    store.appendToken(id, "Hello");
    store.appendToken(id, " ");
    store.appendToken(id, "world");

    const msg = useSessionStore.getState().messages[0];
    expect(msg.content).toBe("Hello world");
  });

  it("appendToken 只作用于指定消息", () => {
    const store = useSessionStore.getState();
    const id1 = store.startAssistantMessage();
    const id2 = store.startAssistantMessage();
    store.appendToken(id1, "A");
    store.appendToken(id2, "B");

    const messages = useSessionStore.getState().messages;
    expect(messages[0].content).toBe("A");
    expect(messages[1].content).toBe("B");
  });

  it("startToolCall 添加工具调用", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    useSessionStore.getState().startToolCall(mid, {
      id: "call-1",
      name: "read_file",
      args: { path: "a.py" },
      status: "running",
      startTime: 1000,
    });

    const msg = useSessionStore.getState().messages[0];
    expect(msg.toolCalls).toHaveLength(1);
    expect(msg.toolCalls[0].id).toBe("call-1");
    expect(msg.toolCalls[0].status).toBe("running");
  });

  it("finishToolCall 标记完成并设置 endTime", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    const store = useSessionStore.getState();
    store.startToolCall(mid, {
      id: "call-1",
      name: "read_file",
      args: {},
      status: "running",
      startTime: 1000,
    });
    store.finishToolCall(mid, "call-1", "output");

    const tc = useSessionStore.getState().messages[0].toolCalls[0];
    expect(tc.status).toBe("done");
    expect(tc.output).toBe("output");
    expect(tc.endTime).toBeGreaterThan(1000);
  });

  it("failToolCall 标记失败", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    const store = useSessionStore.getState();
    store.startToolCall(mid, {
      id: "call-1",
      name: "execute",
      args: {},
      status: "running",
      startTime: 1000,
    });
    store.failToolCall(mid, "call-1", "command failed");

    const tc = useSessionStore.getState().messages[0].toolCalls[0];
    expect(tc.status).toBe("error");
    expect(tc.error).toBe("command failed");
    expect(tc.endTime).toBeDefined();
  });

  it("setPendingApproval 设置审批信息", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    useSessionStore.getState().setPendingApproval(mid, {
      approvalId: "appr-1",
      toolCallId: "call-1",
      toolName: "execute",
      args: { command: "ls" },
      reason: "需要确认",
      threadId: "t-1",
      checkpointId: "c-1",
      createdAt: 1000,
    });

    const msg = useSessionStore.getState().messages[0];
    expect(msg.pendingApproval?.approvalId).toBe("appr-1");
    expect(msg.pendingApproval?.toolName).toBe("execute");
  });

  it("clearPendingApproval 清除审批信息", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    const store = useSessionStore.getState();
    store.setPendingApproval(mid, {
      approvalId: "appr-1",
      toolCallId: "call-1",
      toolName: "execute",
      args: {},
      reason: "",
      threadId: "",
      checkpointId: "",
      createdAt: 0,
    });
    store.clearPendingApproval(mid);

    expect(useSessionStore.getState().messages[0].pendingApproval).toBeUndefined();
  });

  it("finishAssistantMessage 改为 done", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    useSessionStore.getState().finishAssistantMessage(mid);
    expect(useSessionStore.getState().messages[0].status).toBe("done");
  });

  it("reset 清空消息但保留 sessionId", () => {
    const store = useSessionStore.getState();
    store.setSessionId("sess-1");
    store.appendUserMessage("hi");
    store.reset();

    const state = useSessionStore.getState();
    expect(state.messages).toHaveLength(0);
    expect(state.error).toBeNull();
    expect(state.isStreaming).toBe(false);
    expect(state.sessionId).toBe("sess-1");
  });

  it("setSessionId 更新会话 ID", () => {
    useSessionStore.getState().setSessionId("sess-new");
    expect(useSessionStore.getState().sessionId).toBe("sess-new");
  });

  it("setError 设置错误", () => {
    const err = new Error("test");
    useSessionStore.getState().setError(err);
    expect(useSessionStore.getState().error).toBe(err);
  });
});
