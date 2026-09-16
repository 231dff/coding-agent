import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommandPalette } from "./CommandPalette";
import { renderWithProviders } from "@/test/utils";

function renderPalette(overrides = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    onCreateSession: vi.fn(),
    onOpenDashboard: vi.fn(),
    onOpenSettings: vi.fn(),
    ...overrides,
  };
  return {
    ...renderWithProviders(<CommandPalette {...props} />),
    props,
  };
}

describe("CommandPalette", () => {
  it("open=false 时不渲染", () => {
    renderWithProviders(
      <CommandPalette
        open={false}
        onClose={() => {}}
        onCreateSession={() => {}}
        onOpenDashboard={() => {}}
        onOpenSettings={() => {}}
      />
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("open=true 时显示搜索框和命令列表", () => {
    renderPalette();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByText(/新建会话/)).toBeInTheDocument();
    expect(screen.getByText(/打开仪表盘/)).toBeInTheDocument();
  });

  it("输入过滤命令", async () => {
    const user = userEvent.setup();
    renderPalette();

    await user.type(screen.getByRole("textbox"), "dark");
    expect(screen.getByText(/切换到深色主题/)).toBeInTheDocument();
    expect(screen.queryByText(/新建会话/)).not.toBeInTheDocument();
  });

  it("无匹配时显示提示", async () => {
    const user = userEvent.setup();
    renderPalette();

    await user.type(screen.getByRole("textbox"), "zzzzzzz");
    expect(screen.getByText(/无匹配命令/)).toBeInTheDocument();
  });

  it("点击命令触发 handler 并关闭", async () => {
    const user = userEvent.setup();
    const { props } = renderPalette();

    await user.click(screen.getByText(/新建会话/));
    expect(props.onCreateSession).toHaveBeenCalledTimes(1);
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("Esc 关闭", async () => {
    const user = userEvent.setup();
    const { props } = renderPalette();

    await user.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("点击背景关闭", async () => {
    const user = userEvent.setup();
    const { props } = renderPalette();

    const backdrop = document.querySelector(".bg-black\\/40");
    expect(backdrop).toBeTruthy();
    await user.click(backdrop as Element);
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("ArrowDown 移动选中项", async () => {
    const user = userEvent.setup();
    renderPalette();

    const input = screen.getByRole("textbox");
    await user.click(input);

    const buttons = screen
      .getAllByRole("button")
      .filter((b) => b.dataset.index !== undefined);

    expect(buttons[0]).toHaveClass("bg-accent/15");

    await user.keyboard("{ArrowDown}");
    expect(buttons[1]).toHaveClass("bg-accent/15");
  });

  it("Enter 执行选中命令", async () => {
    const user = userEvent.setup();
    const { props } = renderPalette();

    await user.click(screen.getByRole("textbox"));
    await user.keyboard("{Enter}");
    expect(props.onCreateSession).toHaveBeenCalledTimes(1);
  });

  it("语言切换命令生效", async () => {
    const user = userEvent.setup();
    renderPalette();

    await user.type(screen.getByRole("textbox"), "english");
    const button = screen.getByText(/Switch to English/);
    await user.click(button);
  });
});