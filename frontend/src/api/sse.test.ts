import { describe, expect, it, vi } from "vitest";
import { parseSSEStream } from "./sse";
import type { StreamEvent } from "./types";
import { mockSseResponse } from "@/test/utils";

async function collect(resp: Response): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const e of parseSSEStream(resp)) {
    events.push(e);
  }
  return events;
}

describe("parseSSEStream", () => {
  it("解析单个完整事件", async () => {
    const resp = mockSseResponse([
      'event: token\ndata: {"content":"hi","session_id":"s1"}\n\n',
    ]);
    const events = await collect(resp);
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: "token",
      content: "hi",
      session_id: "s1",
    });
  });

  it("处理跨 chunk 分割的事件", async () => {
    const resp = mockSseResponse([
      'event: token\ndata: {"content":"hel',
      'lo","session_id":"s1"}\n\n',
    ]);
    const events = await collect(resp);
    expect(events[0]).toMatchObject({ type: "token", content: "hello" });
  });

  it("处理同一 chunk 多个事件", async () => {
    const resp = mockSseResponse([
      'event: token\ndata: {"content":"a","session_id":"s"}\n\n' +
        'event: token\ndata: {"content":"b","session_id":"s"}\n\n',
    ]);
    const events = await collect(resp);
    expect(events).toHaveLength(2);
    expect((events[0] as { content: string }).content).toBe("a");
    expect((events[1] as { content: string }).content).toBe("b");
  });

  it("忽略格式错误的事件", async () => {
    const resp = mockSseResponse([
      "event: token\ndata: not-json\n\n",
      'event: done\ndata: {"session_id":"s"}\n\n',
    ]);

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const events = await collect(resp);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("done");
    expect(warnSpy).toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("处理多字节 UTF-8 字符跨 chunk", async () => {
    const encoder = new TextEncoder();
    const bytes = encoder.encode(
      'event: token\ndata: {"content":"你好","session_id":"s"}\n\n'
    );
    const split = Math.floor(bytes.length / 2);

    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    });

    const resp = new Response(stream);
    const events = await collect(resp);
    expect((events[0] as { content: string }).content).toBe("你好");
  });

  it("处理 tool_start 事件", async () => {
    const resp = mockSseResponse([
      'event: tool_start\ndata: {"tool_call_id":"c1","tool_name":"read_file","args":{"path":"a.py"},"timestamp":100}\n\n',
    ]);
    const events = await collect(resp);
    expect(events[0].type).toBe("tool_start");
    expect((events[0] as { tool_name: string }).tool_name).toBe("read_file");
  });

  it("处理 approval_required 事件", async () => {
    const resp = mockSseResponse([
      'event: approval_required\ndata: {"session_id":"s","approval_id":"a1","tool_call_id":"c1","tool_name":"execute","args":{},"reason":"需确认","thread_id":"t","checkpoint_id":"ck","timestamp":1}\n\n',
    ]);
    const events = await collect(resp);
    expect(events[0].type).toBe("approval_required");
    expect((events[0] as { approval_id: string }).approval_id).toBe("a1");
  });

  it("处理空 body", async () => {
    const resp = mockSseResponse([]);
    const events = await collect(resp);
    expect(events).toEqual([]);
  });

  it("没有 body 时抛错", async () => {
    const resp = new Response(null);
    await expect(async () => {
      for await (const _ of parseSSEStream(resp)) {
        // 不应到达
      }
    }).rejects.toThrow("响应没有 body");
  });
});