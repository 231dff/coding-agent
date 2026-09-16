import { useEffect } from "react";

export interface Shortcut {
  key: string;
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
  skipInInput?: boolean;
  handler: (e: KeyboardEvent) => void;
}

/**
 * 判断事件目标是否是"可编辑区域"。
 *
 * 兼容：
 * - 标准 HTML 元素（input / textarea / select）
 * - contentEditable（浏览器 + jsdom）
 * - webkitUserModify（部分框架）
 * - 向上遍历祖先节点
 */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!target) return false;

  // 用鸭子类型而非 instanceof，兼容 jsdom 的多种 EventTarget
  const el = target as HTMLElement;
  if (typeof el.tagName !== "string") return false;

  const tag = el.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") {
    return true;
  }

  // 标准属性（浏览器环境）
  if (el.isContentEditable) return true;

  // 属性检查（jsdom 环境）
  const attr = el.getAttribute?.("contenteditable");
  if (attr !== null && attr !== undefined && attr !== "false") {
    return true;
  }

  // webkit 私有属性
  if (el.style?.getPropertyValue("-webkit-user-modify") === "read-write") {
    return true;
  }

  // 向上遍历祖先
  let parent = el.parentElement;
  while (parent) {
    if (parent.isContentEditable) return true;
    const pAttr = parent.getAttribute?.("contenteditable");
    if (pAttr !== null && pAttr !== undefined && pAttr !== "false") {
      return true;
    }
    parent = parent.parentElement;
  }

  return false;
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]): void {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const isMac = navigator.platform.toLowerCase().includes("mac");
      const metaKey = isMac ? e.metaKey : e.ctrlKey;

      for (const s of shortcuts) {
        if (e.key.toLowerCase() !== s.key.toLowerCase()) continue;

        if (s.meta && !metaKey) continue;
        if (!s.meta && metaKey) continue;

        if (s.shift && !e.shiftKey) continue;
        if (!s.shift && e.shiftKey) continue;

        if (s.alt && !e.altKey) continue;
        if (!s.alt && e.altKey) continue;

        if (s.skipInInput !== false) {
          if (isEditableTarget(e.target) && !s.meta) continue;
        }

        e.preventDefault();
        s.handler(e);
        return;
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [shortcuts]);
}