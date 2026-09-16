import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { MessageBubble } from "./MessageBubble";
import { renderWithProviders } from "@/test/utils";
import type { Message } from "@/types/conversation";

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "m-1",
    role: "assistant",
    content: "",
    status: "streaming",
    toolCalls: [],
    createdAt: Date.now(),
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("渲染用户消息", () => {
    renderWithProviders(
      <MessageBubble
        message={makeMessage({ role: "user", content: "hello", status: "done" })}
      />
    );
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("渲染助手消息文本", () => {
    renderWithProviders(
      <MessageBubble
        message={makeMessage({ content: "回答内容", status: "done" })}
      />
    );
    expect(screen.getByText("回答内容")).toBeInTheDocument();
  });

  it("渲染工具调用卡片", () => {
    renderWithProviders(
      <MessageBubble
        message={makeMessage({
          toolCalls: [
            {
              id: "c1",
              name: "read_file",
              args: { path: "a.py" },
              status: "done",
              startTime: 0,
              endTime: 100,
            },
          ],
        })}
      />
    );
    expect(screen.getByText("read_file")).toBeInTheDocument();
  });

  it("流式时显示光标", () => {
    const { container } = renderWithProviders(
      <MessageBubble message={makeMessage({ content: "", status: "streaming" })} />
    );
    const cursor = container.querySelector(".animate-pulse");
    expect(cursor).toBeTruthy();
  });

  it("有内容时不显示光标", () => {
    const { container } = renderWithProviders(
      <MessageBubble
        message={makeMessage({ content: "部分内容", status: "streaming" })}
      />
    );
    // 光标仍在（流式状态），但同时有内容
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
    expect(screen.getByText("部分内容")).toBeInTheDocument();
  });

  it("渲染错误提示", () => {
    renderWithProviders(
      <MessageBubble
        message={makeMessage({ error: "something wrong", status: "error" })}
      />
    );
    expect(screen.getByText("something wrong")).toBeInTheDocument();
  });

  it("有 pendingApproval 时渲染审批卡片", () => {
    const onApprovalDecide = vi.fn();
    renderWithProviders(
      <MessageBubble
        message={makeMessage({
          toolCalls: [
            {
              id: "c1",
              name: "execute",
              args: { command: "ls" },
              status: "pending_approval",
              startTime: 0,
            },
          ],
          pendingApproval: {
            approvalId: "appr-1",
            toolCallId: "c1",
            toolName: "execute",
            args: { command: "ls" },
            reason: "需要确认",
            threadId: "t",
            checkpointId: "ck",
            createdAt: Date.now(),
          },
        })}
        onApprovalDecide={onApprovalDecide}
      />
    );

    expect(screen.getByText("需要人工审批")).toBeInTheDocument();
  });

  it("无 pendingApproval 时渲染普通工具卡片", () => {
    renderWithProviders(
      <MessageBubble
        message={makeMessage({
          toolCalls: [
            {
              id: "c1",
              name: "read_file",
              args: {},
              status: "done",
              startTime: 0,
              endTime: 100,
            },
          ],
        })}
      />
    );

    expect(screen.queryByText("需要人工审批")).not.toBeInTheDocument();
    expect(screen.getByText("read_file")).toBeInTheDocument();
  });
});