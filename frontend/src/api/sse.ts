import type { StreamEvent } from "./types";

/**
 * 从 fetch Response 解析 SSE 流。
 *
 * SSE 格式：
 *   event: token\n
 *   data: {"content":"hi"}\n
 *   \n
 *
 * 关键处理：
 * 1. 用 TextDecoder({ stream: true }) 处理跨 chunk 的多字节字符
 * 2. 用 \n\n 分割事件块，最后一块可能不完整，保留到下次
 * 3. 每个事件块内按行解析，提取 event: 和 data: 字段
 */
export async function* parseSSEStream(
  response: Response
): AsyncGenerator<StreamEvent> {
  if (!response.body) {
    throw new Error("响应没有 body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        // 处理残留的 buffer
        if (buffer.trim()) {
          const event = parseEventBlock(buffer);
          if (event) yield event;
        }
        break;
      }

      // stream: true 保留不完整的多字节字符
      buffer += decoder.decode(value, { stream: true });

      // 按空行分割事件块
      const blocks = buffer.split("\n\n");
      // 最后一块可能不完整，保留
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const event = parseEventBlock(block);
        if (event) yield event;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseEventBlock(block: string): StreamEvent | null {
  const lines = block.split("\n");
  let eventType = "";
  let dataStr = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      // data 可能跨多行，用换行拼接
      const chunk = line.slice(5).trimStart();
      dataStr = dataStr ? `${dataStr}\n${chunk}` : chunk;
    }
  }

  if (!eventType || !dataStr) return null;

  try {
    const data = JSON.parse(dataStr);
    return { type: eventType, ...data } as StreamEvent;
  } catch {
    // 解析失败，忽略该事件（不中断整个流）
    console.warn("SSE 事件解析失败:", eventType, dataStr.slice(0, 100));
    return null;
  }
}