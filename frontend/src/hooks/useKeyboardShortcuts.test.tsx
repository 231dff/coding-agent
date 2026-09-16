import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useKeyboardShortcuts, type Shortcut } from "./useKeyboardShortcuts";

describe("useKeyboardShortcuts", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "platform", {
      writable: true,
      configurable: true,
      value: "Linux x86_64",
    });
  });

  function fireKey(
    key: string,
    options: {
      ctrlKey?: boolean;
      shiftKey?: boolean;
      altKey?: boolean;
      target?: EventTarget;
    } = {}
  ) {
    const event = new KeyboardEvent("keydown", {
      key,
      ctrlKey: options.ctrlKey ?? false,
      shiftKey: options.shiftKey ?? false,
      altKey: options.altKey ?? false,
      bubbles: true,
      cancelable: true,
    });

    if (options.target) {
      options.target.dispatchEvent(event);
    } else {
      window.dispatchEvent(event);
    }

    return event;
  }

  it("单键触发", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "a", handler }]));

    fireKey("a");
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("Ctrl 组合键触发", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "k", meta: true, handler }]));

    fireKey("k", { ctrlKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("没有 Ctrl 时不触发 meta 快捷键", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "k", meta: true, handler }]));

    fireKey("k");
    expect(handler).not.toHaveBeenCalled();
  });

  it("键名大小写不敏感", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "k", meta: true, handler }]));

    fireKey("K", { ctrlKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("输入框内单键不触发（skipInInput 默认 true）", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "a", handler }]));

    const input = document.createElement("input");
    document.body.appendChild(input);

    fireKey("a", { target: input });
    expect(handler).not.toHaveBeenCalled();

    document.body.removeChild(input);
  });

  it("输入框内 meta 快捷键仍触发", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "k", meta: true, handler }]));

    const input = document.createElement("input");
    document.body.appendChild(input);

    fireKey("k", { ctrlKey: true, target: input });
    expect(handler).toHaveBeenCalledTimes(1);

    document.body.removeChild(input);
  });

  it("textarea 内不触发单键", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "a", handler }]));

    const ta = document.createElement("textarea");
    document.body.appendChild(ta);

    fireKey("a", { target: ta });
    expect(handler).not.toHaveBeenCalled();

    document.body.removeChild(ta);
  });

  it("contentEditable 内不触发单键", () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcuts([{ key: "a", handler }]));

    const div = document.createElement("div");
    // 用 setAttribute 而非属性赋值，jsdom 才会真正写入 attribute
    div.setAttribute("contenteditable", "true");
    div.tabIndex = 0;
    document.body.appendChild(div);

    fireKey("a", { target: div });
    expect(handler).not.toHaveBeenCalled();

    document.body.removeChild(div);
  });

  it("多个快捷键按顺序匹配，第一个命中就返回", () => {
    const h1 = vi.fn();
    const h2 = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([
        { key: "a", handler: h1 },
        { key: "a", handler: h2 },
      ])
    );

    fireKey("a");
    expect(h1).toHaveBeenCalledTimes(1);
    expect(h2).not.toHaveBeenCalled();
  });

  it("Shift 组合键", () => {
    const handler = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts([{ key: "a", shift: true, handler }])
    );

    fireKey("a", { shiftKey: true });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("卸载时移除监听", () => {
    const handler = vi.fn();
    const { unmount } = renderHook(() =>
      useKeyboardShortcuts([{ key: "a", handler }])
    );

    unmount();
    fireKey("a");
    expect(handler).not.toHaveBeenCalled();
  });

  it("回调更新时使用最新版本", () => {
    const h1 = vi.fn();
    const h2 = vi.fn();

    const { rerender } = renderHook(
      ({ shortcuts }: { shortcuts: Shortcut[] }) =>
        useKeyboardShortcuts(shortcuts),
      { initialProps: { shortcuts: [{ key: "a", handler: h1 }] } }
    );

    fireKey("a");
    expect(h1).toHaveBeenCalledTimes(1);

    rerender({ shortcuts: [{ key: "a", handler: h2 }] });

    fireKey("a");
    expect(h2).toHaveBeenCalledTimes(1);
    expect(h1).toHaveBeenCalledTimes(1);
  });
});