import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { useThemeStore } from "./themeStore";

describe("themeStore", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    localStorage.clear();
    // 重置 store 到默认
    useThemeStore.setState({ mode: "system", resolved: "light" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("setMode('dark') 加 .dark class", () => {
    useThemeStore.getState().setMode("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(useThemeStore.getState().resolved).toBe("dark");
  });

  it("setMode('light') 移除 .dark class", () => {
    document.documentElement.classList.add("dark");
    useThemeStore.getState().setMode("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(useThemeStore.getState().resolved).toBe("light");
  });

  it("setMode('system') 根据系统偏好决定", () => {
    // 默认 matchMedia 返回 false
    useThemeStore.getState().setMode("system");
    expect(useThemeStore.getState().resolved).toBe("light");
  });

  it("system 模式下系统偏好变化时 syncSystem 更新", () => {
    // 模拟系统变为深色
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        ({
          matches: true,
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) as unknown as MediaQueryList
    );

    useThemeStore.getState().setMode("system");
    useThemeStore.getState().syncSystem();

    expect(useThemeStore.getState().resolved).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("非 system 模式下 syncSystem 不改变", () => {
    useThemeStore.getState().setMode("light");

    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        ({
          matches: true,
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) as unknown as MediaQueryList
    );

    useThemeStore.getState().syncSystem();
    expect(useThemeStore.getState().resolved).toBe("light");
  });
});