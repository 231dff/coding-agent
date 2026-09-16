import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useAgentStream } from "./useAgentStream";
import { mockSseResponse, sseEvent } from "@/test/utils";
import type { StreamEvent } from "@/api/types";

describe("useAgentStream", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("初始状态", () => {
    const { result } = renderHook(() => useAgentStream());

    expect(result.current.events).toEqual([]);
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("send 后累积事件", async () => {
    const events: StreamEvent[] = [];
    const onEvent = vi.fn((e) => events.push(e));

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      mockSseResponse([
        sseEvent("token", { content: "hello", session_id: "s" }),
        sseEvent("done", { session_id: "s" }),
      ])
    );

    const { result } = renderHook(() => useAgentStream({ onEvent }));

    await act(async () => {
      await result.current.send("test");
    });

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events[0].type).toBe("token");
    expect(result.current.events[1].type).toBe("done");
    expect(onEvent).toHaveBeenCalledTimes(2);
  });

  it("触发 onDone 回调", async () => {
    const onDone = vi.fn();

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      mockSseResponse([
        sseEvent("done", { session_id: "s" }),
      ])
    );

    const { result } = renderHook(() => useAgentStream({ onDone }));

    await act(async () => {
      await result.current.send("test");
    });

    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("HTTP 错误设置 error", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response("Server Error", { status: 500 })
    );

    const onError = vi.fn();
    const { result } = renderHook(() => useAgentStream({ onError }));

    await act(async () => {
      await result.current.send("test");
    });

    expect(result.current.error).toBeTruthy();
    expect(result.current.error?.message).toContain("500");
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("abort 中断流", async () => {
    // 模拟一个慢速流
    let resolveStream: () => void = () => {};
    const streamPromise = new Promise<void>((resolve) => {
      resolveStream = resolve;
    });

    vi.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        async start(controller) {
          controller.enqueue(
            encoder.encode(sseEvent("token", { content: "a", session_id: "s" }))
          );
          // 等待中断
          await streamPromise;
          controller.close();
        },
      });

      // 监听 abort 信号
      (init?.signal as AbortSignal)?.addEventListener("abort", () => {
        resolveStream();
      });

      return new Response(stream);
    });

    const { result } = renderHook(() => useAgentStream());

    let sendPromise: Promise<void>;
    act(() => {
      sendPromise = result.current.send("test");
    });

    // 等第一个事件到达
    await waitFor(() => {
      expect(result.current.events.length).toBeGreaterThan(0);
    });

    act(() => {
      result.current.abort();
    });

    await act(async () => {
      await sendPromise!;
    });

    expect(result.current.isStreaming).toBe(false);
  });

  it("clear 清空事件和错误", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      mockSseResponse([sseEvent("token", { content: "a", session_id: "s" })])
    );

    const { result } = renderHook(() => useAgentStream());

    await act(async () => {
      await result.current.send("test");
    });

    expect(result.current.events.length).toBeGreaterThan(0);

    act(() => {
      result.current.clear();
    });

    expect(result.current.events).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it("卸载时中断流", () => {
    const abortSpy = vi.fn();
    const originalAbort = AbortController.prototype.abort;
    AbortController.prototype.abort = abortSpy;

    vi.spyOn(global, "fetch").mockResolvedValue(
      mockSseResponse([sseEvent("token", { content: "a", session_id: "s" })])
    );

    const { result, unmount } = renderHook(() => useAgentStream());

    act(() => {
      void result.current.send("test");
    });

    unmount();

    // 至少调用一次 abort
    expect(abortSpy).toHaveBeenCalled();

    AbortController.prototype.abort = originalAbort;
  });
});