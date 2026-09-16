import { useEffect, useRef, useState } from "react";

interface UseAutoScrollResult {
  /** 挂到滚动容器的 ref */
  scrollRef: React.RefObject<HTMLDivElement | null>;
  /** 是否已滚动到底部附近 */
  isAtBottom: boolean;
  /** 手动滚到底部 */
  scrollToBottom: (behavior?: ScrollBehavior) => void;
}

/**
 * 自动滚动 Hook。
 *
 * 行为：
 * - 新内容到达时，如果用户在底部附近 → 自动滚到底
 * - 用户主动上滑超过阈值 → 暂停自动滚动
 * - 用户滚回底部附近 → 恢复自动滚动
 */
export function useAutoScroll(
  dependency: unknown,
  threshold = 100
): UseAutoScrollResult {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [userScrolledUp, setUserScrolledUp] = useState(false);

  // 监听滚动事件
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    function handleScroll() {
      if (!el) return;
      const distanceToBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      const atBottom = distanceToBottom < threshold;
      setIsAtBottom(atBottom);
      setUserScrolledUp(!atBottom);
    }

    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [threshold]);

  // 新内容到达时自动滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (userScrolledUp) return;
    el.scrollTop = el.scrollHeight;
  }, [dependency, userScrolledUp]);

  function scrollToBottom(behavior: ScrollBehavior = "smooth") {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    setUserScrolledUp(false);
  }

  return { scrollRef, isAtBottom, scrollToBottom };
}