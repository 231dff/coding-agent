import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import i18n from "@/i18n";


// ============================================================
// 全局 mock —— 必须放在顶层，保证在测试文件 import 之前生效
// ============================================================

// 1. matchMedia —— 强制覆盖
Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// 2. ResizeObserver
if (typeof global.ResizeObserver === "undefined") {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// 3. IntersectionObserver
if (typeof global.IntersectionObserver === "undefined") {
  global.IntersectionObserver = class IntersectionObserver {
    root = null;
    rootMargin = "";
    thresholds = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
}

// 4. scrollTo / scrollIntoView
Element.prototype.scrollTo = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

// 5. navigator.platform
if (!navigator.platform) {
  Object.defineProperty(navigator, "platform", {
    writable: true,
    configurable: true,
    value: "Linux x86_64",
  });
}

// 6. getBoundingClientRect
Element.prototype.getBoundingClientRect = vi.fn(() => ({
  width: 800,
  height: 100,
  top: 0,
  left: 0,
  right: 800,
  bottom: 100,
  x: 0,
  y: 0,
  toJSON: () => {},
}));

// 注意：不要手动定义 navigator.clipboard，user-event v14 会自己挂载


// ============================================================
// 每个测试后的清理
// ============================================================
afterEach(() => {
  cleanup();
  localStorage.clear();
});


// ============================================================
// i18n 初始化
// ============================================================
beforeAll(async () => {
  localStorage.setItem("coding-agent-language", "zh");
  await i18n.changeLanguage("zh");
  i18n.options.debug = false;
});