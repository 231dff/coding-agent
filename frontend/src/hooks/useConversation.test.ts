import { describe, expect, it, beforeEach } from "vitest";
import { useSessionStore } from "@/stores/sessionStore";

describe("sessionStore", () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
  });

  it("appendUserMessage 追加用户消息", () => {
    const id = useSessionStore.getState().appendUserMessage("hi");
    const msgs = useSessionStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].id).toBe(id);
    expect(msgs[0].role).toBe("user");
    expect(msgs[0].content).toBe("hi");
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

  it("startToolCall 和 finishToolCall 配对", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    const store = useSessionStore.getState();

    store.startToolCall(mid, {
      id: "call-1",
      name: "read_file",
      args: { path: "a.py" },
      status: "running",
      startTime: Date.now(),
    });

    let msg = useSessionStore.getState().messages[0];
    expect(msg.toolCalls).toHaveLength(1);
    expect(msg.toolCalls[0].status).toBe("running");

    store.finishToolCall(mid, "call-1", "file contents");
    msg = useSessionStore.getState().messages[0];
    expect(msg.toolCalls[0].status).toBe("done");
    expect(msg.toolCalls[0].output).toBe("file contents");
    expect(msg.toolCalls[0].endTime).toBeDefined();
  });

  it("failToolCall 标记失败", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    const store = useSessionStore.getState();
    store.startToolCall(mid, {
      id: "call-1",
      name: "execute",
      args: { command: "ls" },
      status: "running",
      startTime: Date.now(),
    });
    store.failToolCall(mid, "call-1", "command not found");
    const msg = useSessionStore.getState().messages[0];
    expect(msg.toolCalls[0].status).toBe("error");
    expect(msg.toolCalls[0].error).toBe("command not found");
  });

  it("finishAssistantMessage 修改状态为 done", () => {
    const mid = useSessionStore.getState().startAssistantMessage();
    useSessionStore.getState().finishAssistantMessage(mid);
    const msg = useSessionStore.getState().messages[0];
    expect(msg.status).toBe("done");
  });
});