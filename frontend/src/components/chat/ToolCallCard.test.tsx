import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToolCallCard } from "./ToolCallCard";
import { renderWithProviders } from "@/test/utils";
import type { ToolCall } from "@/types/conversation";


function makeToolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "call-1",
    name: "read_file",
    args: { path: "a.py" },
    status: "done",
    startTime: 1000,
    endTime: 1500,
    ...overrides,
  };
}


describe("ToolCallCard", () => {
  it("显示工具名", () => {
    renderWithProviders(<ToolCallCard toolCall={makeToolCall()} />);
    expect(screen.getByText("read_file")).toBeInTheDocument();
  });

  it("显示耗时", () => {
    renderWithProviders(<ToolCallCard toolCall={makeToolCall()} />);
    expect(screen.getByText("500ms")).toBeInTheDocument();
  });

  it("耗时超过 1 秒显示为秒", () => {
    renderWithProviders(
      <ToolCallCard
        toolCall={makeToolCall({ startTime: 0, endTime: 2500 })}
      />
    );
    expect(screen.getByText("2.50s")).toBeInTheDocument();
  });

  it("running 状态显示 spinner", () => {
    renderWithProviders(
      <ToolCallCard
        toolCall={makeToolCall({ status: "running", endTime: undefined })}
      />
    );
    const card = screen.getByRole("button");
    expect(card.querySelector(".animate-spin")).toBeTruthy();
  });

  it("默认折叠，点击展开显示参数和输出", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ToolCallCard
        toolCall={makeToolCall({ output: "file contents" })}
      />
    );

    expect(screen.queryByText("参数")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button"));

    expect(screen.getByText("参数")).toBeInTheDocument();
    expect(screen.getByText("输出")).toBeInTheDocument();
    expect(screen.getByText("file contents")).toBeInTheDocument();
  });

  it("展开后显示参数 JSON", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ToolCallCard
        toolCall={makeToolCall({ args: { path: "src/main.py", line: 42 } })}
      />
    );

    await user.click(screen.getByRole("button"));

    const argsPre = screen.getByTestId("tool-args");
    expect(argsPre.textContent).toContain("src/main.py");
    expect(argsPre.textContent).toContain("42");
  });

  it("error 状态显示错误", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ToolCallCard
        toolCall={makeToolCall({ status: "error", error: "file not found" })}
      />
    );

    await user.click(screen.getByRole("button"));
    expect(screen.getByText("file not found")).toBeInTheDocument();
  });

  it("长输出截断", async () => {
    const user = userEvent.setup();
    const longOutput = "x".repeat(10_000);
    renderWithProviders(
      <ToolCallCard toolCall={makeToolCall({ output: longOutput })} />
    );

    await user.click(screen.getByRole("button"));

    // 用 testid 精确定位到输出的 pre
    const outputPre = screen.getByTestId("tool-output");
    expect(outputPre.textContent).toContain("已截断");
    expect(outputPre.textContent?.length).toBeLessThan(6000);
  });

  it("pending_approval 状态正常渲染", () => {
    renderWithProviders(
      <ToolCallCard toolCall={makeToolCall({ status: "pending_approval" })} />
    );
    expect(screen.getByText("read_file")).toBeInTheDocument();
  });
});