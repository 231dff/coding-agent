import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalPrompt } from "./ApprovalPrompt";
import { renderWithProviders } from "@/test/utils";
import { useAuthStore } from "@/hooks/useAuth";

function setupAuth(roles: readonly ("admin" | "developer" | "viewer")[]) {
  useAuthStore.setState({
    config: {
      mode: "disabled",
      require_auth: false,
      oidc_authority: "",
      oidc_client_id: "",
      oidc_redirect_uri: "",
      oidc_scope: "",
    },
    user: {
      id: "u1",
      name: "Test User",
      email: "",
      roles: [...roles],
      picture: "",
    },
    initialized: true,
    loading: false,
    error: null,
  });
}

function setup(overrides = {}) {
  const props = {
    toolName: "execute",
    args: { command: "ls -la" },
    reason: "需要确认",
    createdAt: Date.now(),
    isSubmitting: false,
    error: null,
    onDecide: vi.fn(),
    ...overrides,
  };
  return { ...renderWithProviders(<ApprovalPrompt {...props} />), props };
}

describe("ApprovalPrompt", () => {
  beforeEach(() => {
    setupAuth(["developer"]);
  });

  it("显示标题", () => {
    setup();
    expect(screen.getByText("需要人工审批")).toBeInTheDocument();
  });

  it("显示工具名", () => {
    setup();
    expect(screen.getByText("execute")).toBeInTheDocument();
  });

  it("显示理由", () => {
    setup();
    expect(screen.getByText("需要确认")).toBeInTheDocument();
  });

  it("显示参数 JSON", () => {
    setup();
    expect(screen.getByText(/"command": "ls -la"/)).toBeInTheDocument();
  });

  it("显示倒计时", () => {
    setup();
    expect(screen.getByText(/^\d{2}:\d{2}$/)).toBeInTheDocument();
  });

  it("有批准/编辑/拒绝按钮", () => {
    setup();
    expect(screen.getByRole("button", { name: /批准/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^编辑$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /拒绝/ })).toBeInTheDocument();
  });

  it("点击批准触发 onDecide('approve')", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await user.click(screen.getByRole("button", { name: /批准/ }));
    expect(props.onDecide).toHaveBeenCalledWith("approve");
  });

  it("点击拒绝触发 onDecide('reject')", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await user.click(screen.getByRole("button", { name: /拒绝/ }));
    expect(props.onDecide).toHaveBeenCalledWith("reject");
  });

  it("按 Enter 批准", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await user.keyboard("{Enter}");
    expect(props.onDecide).toHaveBeenCalledWith("approve");
  });

  it("按 Esc 拒绝", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await user.keyboard("{Escape}");
    expect(props.onDecide).toHaveBeenCalledWith("reject");
  });

  it("点击编辑进入编辑模式", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("button", { name: /^编辑$/ }));
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByText("编辑参数（JSON）")).toBeInTheDocument();
  });

  it("编辑模式提交修改", async () => {
    const user = userEvent.setup();
    const { props } = setup();

    await user.click(screen.getByRole("button", { name: /^编辑$/ }));
    const textarea = screen.getByRole("textbox");
    await user.clear(textarea);
    await user.type(textarea, '{{"command": "pwd"}');

    await user.click(screen.getByRole("button", { name: /提交修改并批准/ }));
    expect(props.onDecide).toHaveBeenCalledWith("edit", { command: "pwd" });
  });

  it("非法 JSON 显示错误", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("button", { name: /^编辑$/ }));
    const textarea = screen.getByRole("textbox");
    await user.clear(textarea);
    await user.type(textarea, "not-json");

    await user.click(screen.getByRole("button", { name: /提交修改并批准/ }));
    expect(screen.getByText(/JSON 解析失败/)).toBeInTheDocument();
  });

  it("数组不被接受", () => {
    setup();

    // 进入编辑模式
    fireEvent.click(screen.getByRole("button", { name: /^编辑$/ }));

    // 用 fireEvent.change 直接设置值，避免 userEvent 对 "[" 的特殊解析
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "[1,2,3]" } });

    fireEvent.click(screen.getByRole("button", { name: /提交修改并批准/ }));
    expect(screen.getByText("必须是一个 JSON 对象")).toBeInTheDocument();
  });

  it("编辑模式撤销恢复原始参数", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("button", { name: /^编辑$/ }));
    const textarea = screen.getByRole("textbox");
    await user.clear(textarea);
    await user.type(textarea, "modified");

    await user.click(screen.getByRole("button", { name: /撤销/ }));
    expect(screen.getByText(/"command": "ls -la"/)).toBeInTheDocument();
  });

  it("编辑模式 Esc 取消", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("button", { name: /^编辑$/ }));
    expect(screen.getByRole("textbox")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("viewer 角色看不到操作按钮", () => {
    setupAuth(["viewer"]);
    setup();

    expect(screen.queryByRole("button", { name: /批准/ })).not.toBeInTheDocument();
    expect(screen.getByText(/当前角色无审批权限/)).toBeInTheDocument();
  });

  it("isSubmitting 时按钮禁用", () => {
    setup({ isSubmitting: true });
    expect(screen.getByRole("button", { name: /批准/ })).toBeDisabled();
    expect(screen.getByText("提交中...")).toBeInTheDocument();
  });

  it("显示错误提示", () => {
    setup({ error: new Error("提交失败") });
    expect(screen.getByText("提交失败")).toBeInTheDocument();
  });
});