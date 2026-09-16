import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen, act, fireEvent } from "@testing-library/react";
import { Toast } from "./Toast";
import { renderWithProviders } from "@/test/utils";
import type { Notification } from "@/types/notification";


function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n-1",
    type: "success",
    title: "成功",
    duration: 0, // 0 = 不自动关闭
    createdAt: Date.now(),
    ...overrides,
  };
}


describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("显示标题", () => {
    renderWithProviders(
      <Toast notification={makeNotification()} onDismiss={() => {}} />
    );
    expect(screen.getByText("成功")).toBeInTheDocument();
  });

  it("显示描述", () => {
    renderWithProviders(
      <Toast
        notification={makeNotification({ description: "详细说明" })}
        onDismiss={() => {}}
      />
    );
    expect(screen.getByText("详细说明")).toBeInTheDocument();
  });

  it("有关闭按钮", () => {
    renderWithProviders(
      <Toast notification={makeNotification()} onDismiss={() => {}} />
    );
    expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();
  });

  it("点击关闭按钮触发 onDismiss（有延迟）", () => {
    const onDismiss = vi.fn();

    renderWithProviders(
      <Toast notification={makeNotification()} onDismiss={onDismiss} />
    );

    // fireEvent 是同步的，不涉及 setTimeout，不会被 fake timers 卡住
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));

    // 动画 200ms 后才真正调用 onDismiss
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(250);
    });

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("duration > 0 时自动关闭", () => {
    const onDismiss = vi.fn();

    renderWithProviders(
      <Toast
        notification={makeNotification({ duration: 1000 })}
        onDismiss={onDismiss}
      />
    );

    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1300);
    });

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("duration 为 0 不自动关闭", () => {
    const onDismiss = vi.fn();

    renderWithProviders(
      <Toast
        notification={makeNotification({ duration: 0 })}
        onDismiss={onDismiss}
      />
    );

    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("有 action 时渲染按钮", () => {
    const onClick = vi.fn();
    renderWithProviders(
      <Toast
        notification={makeNotification({
          action: { label: "查看", onClick },
        })}
        onDismiss={() => {}}
      />
    );
    expect(screen.getByRole("button", { name: "查看" })).toBeInTheDocument();
  });

  it("点击 action 触发回调", () => {
    const onClick = vi.fn();
    const onDismiss = vi.fn();

    renderWithProviders(
      <Toast
        notification={makeNotification({
          action: { label: "查看", onClick },
        })}
        onDismiss={onDismiss}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "查看" }));

    expect(onClick).toHaveBeenCalledTimes(1);

    // action 点击后也会触发 dismiss（动画延迟）
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(onDismiss).toHaveBeenCalled();
  });

  it("role=alert 用于无障碍", () => {
    renderWithProviders(
      <Toast notification={makeNotification()} onDismiss={() => {}} />
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});