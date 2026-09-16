import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SessionItem } from "./SessionItem";
import { renderWithProviders } from "@/test/utils";
import type { SessionMeta } from "@/types/session";


function makeSession(overrides: Partial<SessionMeta> = {}): SessionMeta {
  return {
    id: "s-1",
    title: "Test Session",
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messageCount: 3,
    status: "idle",
    archived: false,
    pinned: false,
    ...overrides,
  };
}


function setup(session: SessionMeta = makeSession()) {
  const props = {
    session,
    isActive: false,
    onSelect: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onTogglePin: vi.fn(),
    onToggleArchive: vi.fn(),
  };
  return { ...renderWithProviders(<SessionItem {...props} />), props };
}


/**
 * 打开菜单。
 *
 * 定位策略：menu 按钮是 SessionItem 里唯一一个包含
 * lucide-ellipsis-vertical 图标的按钮。用它的祖先关系定位，
 * 而不是依赖按钮顺序。
 */
async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  // 找 menu 按钮：它包含 svg.lucide-ellipsis-vertical
  const menuButton = document.querySelector("button svg.lucide-ellipsis-vertical")
    ?.closest("button");
  if (!menuButton) throw new Error("未找到菜单按钮");
  await user.click(menuButton);
}


describe("SessionItem", () => {
  it("显示标题", () => {
    setup();
    expect(screen.getByText("Test Session")).toBeInTheDocument();
  });

  it("显示消息数", () => {
    setup();
    // 中文 i18n 下是 "3 条"
    expect(screen.getByText(/3 条/)).toBeInTheDocument();
  });

  it("置顶会话显示 Pin 图标", () => {
    setup(makeSession({ pinned: true }));
    const item = screen.getByText("Test Session").parentElement;
    expect(item?.querySelector("svg")).toBeTruthy();
  });

  it("点击触发 onSelect", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await user.click(screen.getByText("Test Session"));
    expect(props.onSelect).toHaveBeenCalledTimes(1);
  });

  it("点击菜单按钮展开菜单", async () => {
    const user = userEvent.setup();
    setup();
    await openMenu(user);

    expect(screen.getByText("重命名")).toBeInTheDocument();
    expect(screen.getByText("置顶")).toBeInTheDocument();
    expect(screen.getByText("归档")).toBeInTheDocument();
    expect(screen.getByText("删除")).toBeInTheDocument();
  });

  it("点击重命名进入编辑模式", async () => {
    const user = userEvent.setup();
    setup();
    await openMenu(user);
    await user.click(screen.getByText("重命名"));

    expect(screen.getByDisplayValue("Test Session")).toBeInTheDocument();
  });

  it("编辑模式回车提交重命名", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await openMenu(user);
    await user.click(screen.getByText("重命名"));

    const input = screen.getByDisplayValue("Test Session");
    await user.clear(input);
    await user.type(input, "New Title{Enter}");

    expect(props.onRename).toHaveBeenCalledWith("New Title");
  });

  it("编辑模式 Esc 取消", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await openMenu(user);
    await user.click(screen.getByText("重命名"));

    const input = screen.getByDisplayValue("Test Session");
    await user.clear(input);
    await user.type(input, "Discarded{Escape}");

    expect(props.onRename).not.toHaveBeenCalled();
    expect(screen.getByText("Test Session")).toBeInTheDocument();
  });

  it("空标题不提交", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await openMenu(user);
    await user.click(screen.getByText("重命名"));

    const input = screen.getByDisplayValue("Test Session");
    await user.clear(input);
    await user.keyboard("{Enter}");

    expect(props.onRename).not.toHaveBeenCalled();
  });

  it("点击置顶触发回调", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await openMenu(user);
    await user.click(screen.getByText("置顶"));

    expect(props.onTogglePin).toHaveBeenCalledTimes(1);
  });

  it("归档的会话显示取消归档", async () => {
    const user = userEvent.setup();
    setup(makeSession({ archived: true }));

    await openMenu(user);
    expect(screen.getByText("取消归档")).toBeInTheDocument();
  });

  it("删除需二次确认", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await openMenu(user);
    await user.click(screen.getByText("删除"));

    expect(screen.getByText("确认删除？")).toBeInTheDocument();
    expect(props.onDelete).not.toHaveBeenCalled();

    // 用 within 定位到菜单，避免误点其他"删除"文本
    const menu = screen.getByText("确认删除？").parentElement?.parentElement;
    const confirmBtn = within(menu!).getByText("删除");
    await user.click(confirmBtn);
    expect(props.onDelete).toHaveBeenCalledTimes(1);
  });

  it("二次确认点取消取消删除", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await openMenu(user);
    await user.click(screen.getByText("删除"));

    // 菜单里有确认/取消两个按钮
    const menu = screen.getByText("确认删除？").parentElement?.parentElement;
    await user.click(within(menu!).getByText("取消"));

    expect(props.onDelete).not.toHaveBeenCalled();
  });

  it("running 状态显示 spinner", () => {
    setup(makeSession({ status: "running" }));
    expect(document.querySelector(".animate-spin")).toBeTruthy();
  });

  it("error 状态显示错误图标", () => {
    const { container } = setup(makeSession({ status: "error" }));
    expect(container.querySelector(".text-red-500")).toBeTruthy();
  });

  it("活跃会话有高亮样式", () => {
    renderWithProviders(
      <SessionItem
        session={makeSession()}
        isActive
        onSelect={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
        onTogglePin={() => {}}
        onToggleArchive={() => {}}
      />
    );

    const wrapper = screen.getByText("Test Session").closest("div.group");
    expect(wrapper).toHaveClass("bg-accent/15");
  });
});