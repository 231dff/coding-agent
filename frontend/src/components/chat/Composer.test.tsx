import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Composer } from "./Composer";
import { renderWithProviders } from "@/test/utils";
import { useAuthStore } from "@/hooks/useAuth";
import type { User } from "@/types/auth";


function setUser(user: User | null) {
  useAuthStore.setState({
    config: {
      mode: "disabled",
      require_auth: false,
      oidc_authority: "",
      oidc_client_id: "",
      oidc_redirect_uri: "",
      oidc_scope: "",
    },
    user,
    initialized: true,
    loading: false,
    error: null,
  });
}


const adminUser: User = {
  id: "u1",
  name: "Admin",
  email: "",
  roles: ["admin"],
  picture: "",
};

const viewerUser: User = {
  id: "u2",
  name: "Viewer",
  email: "",
  roles: ["viewer"],
  picture: "",
};


describe("Composer", () => {
  beforeEach(() => {
    setUser(adminUser);
  });

  it("输入框可输入", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Composer onSend={() => {}} onAbort={() => {}} isStreaming={false} />
    );

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "hello");
    expect(textarea).toHaveValue("hello");
  });

  it("点击发送按钮触发 onSend", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    renderWithProviders(
      <Composer onSend={onSend} onAbort={() => {}} isStreaming={false} />
    );

    await user.type(screen.getByRole("textbox"), "hello");
    await user.click(screen.getByTitle("发送"));

    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("Enter 发送，Shift+Enter 换行", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    renderWithProviders(
      <Composer onSend={onSend} onAbort={() => {}} isStreaming={false} />
    );

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello");

    onSend.mockClear();
    await user.type(textarea, "line1{Shift>}{Enter}{/Shift}line2");
    expect(onSend).not.toHaveBeenCalled();
    expect(textarea).toHaveValue("line1\nline2");
  });

  it("发送后清空输入框", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Composer onSend={() => {}} onAbort={() => {}} isStreaming={false} />
    );

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "hello");
    await user.keyboard("{Enter}");

    expect(textarea).toHaveValue("");
  });

  it("空输入不能发送", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    renderWithProviders(
      <Composer onSend={onSend} onAbort={() => {}} isStreaming={false} />
    );

    await user.click(screen.getByTitle("发送"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("纯空白不能发送", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    renderWithProviders(
      <Composer onSend={onSend} onAbort={() => {}} isStreaming={false} />
    );

    await user.type(screen.getByRole("textbox"), "   ");
    await user.keyboard("{Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("流式状态显示中断按钮", () => {
    renderWithProviders(
      <Composer onSend={() => {}} onAbort={() => {}} isStreaming={true} />
    );

    expect(screen.getByTitle("中断")).toBeInTheDocument();
    expect(screen.queryByTitle("发送")).not.toBeInTheDocument();
  });

  it("点击中断触发 onAbort", async () => {
    const user = userEvent.setup();
    const onAbort = vi.fn();

    renderWithProviders(
      <Composer onSend={() => {}} onAbort={onAbort} isStreaming={true} />
    );

    await user.click(screen.getByTitle("中断"));
    expect(onAbort).toHaveBeenCalledTimes(1);
  });

  it("viewer 角色显示只读提示", () => {
    setUser(viewerUser);
    renderWithProviders(
      <Composer onSend={() => {}} onAbort={() => {}} isStreaming={false} />
    );

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText(/只读/)).toBeInTheDocument();
  });

  it("流式时禁用发送", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();

    // 用 rerender 而非重新 render，避免出现两个 DOM 树
    const { rerender } = renderWithProviders(
      <Composer onSend={onSend} onAbort={() => {}} isStreaming={false} />
    );

    await user.type(screen.getByRole("textbox"), "hello");

    // 通过 rerender 更新 props
    rerender(
      <Composer onSend={onSend} onAbort={() => {}} isStreaming={true} />
    );

    expect(screen.queryByTitle("发送")).not.toBeInTheDocument();
    expect(screen.getByTitle("中断")).toBeInTheDocument();
  });
});