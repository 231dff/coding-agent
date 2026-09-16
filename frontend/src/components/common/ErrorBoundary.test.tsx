import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "./ErrorBoundary";
import { renderWithProviders } from "@/test/utils";

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("boom!");
  return <div>正常内容</div>;
}

describe("ErrorBoundary", () => {
  // React 的错误边界会打印错误到 console.error，测试时屏蔽
  const originalError = console.error;

  beforeEach(() => {
    console.error = vi.fn();
  });

  afterEach(() => {
    console.error = originalError;
  });

  it("正常时渲染子组件", () => {
    renderWithProviders(
      <ErrorBoundary>
        <div>正常</div>
      </ErrorBoundary>
    );
    expect(screen.getByText("正常")).toBeInTheDocument();
  });

  it("捕获错误显示默认回退", () => {
    renderWithProviders(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText("页面出现错误")).toBeInTheDocument();
    expect(screen.getByText("boom!")).toBeInTheDocument();
  });

  it("自定义 fallback", () => {
    renderWithProviders(
      <ErrorBoundary
        fallback={(error) => <div>自定义: {error.message}</div>}
      >
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText("自定义: boom!")).toBeInTheDocument();
  });

  it("onError 回调被调用", () => {
    const onError = vi.fn();
    renderWithProviders(
      <ErrorBoundary onError={onError}>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toBe("boom!");
  });

  it("点击重试按钮恢复", async () => {
    const user = userEvent.setup();
    let shouldThrow = true;

    function Toggle() {
      // 通过闭包控制重渲染后的行为
      if (shouldThrow) throw new Error("boom");
      return <div>已恢复</div>;
    }

    // 用 rerender 修改状态
    const { rerender } = renderWithProviders(
      <ErrorBoundary>
        <Toggle />
      </ErrorBoundary>
    );

    expect(screen.getByText("页面出现错误")).toBeInTheDocument();

    // 修改状态后再点击重试
    shouldThrow = false;
    await user.click(screen.getByRole("button", { name: /重试/ }));

    // 重试后边界重置，重新渲染子组件
    rerender(
      <ErrorBoundary>
        <div>已恢复</div>
      </ErrorBoundary>
    );

    expect(screen.getByText("已恢复")).toBeInTheDocument();
  });

  it("刷新页面按钮存在", () => {
    renderWithProviders(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByRole("button", { name: /刷新页面/ })).toBeInTheDocument();
  });
});