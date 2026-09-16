import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { deriveTitle, groupSession, type SessionMeta } from "./session";

describe("deriveTitle", () => {
  it("短消息原样返回", () => {
    expect(deriveTitle("hello")).toBe("hello");
  });

  it("长消息截断到 30 字符 + 省略号", () => {
    const long = "a".repeat(50);
    const title = deriveTitle(long);
    expect(title).toBe("a".repeat(30) + "...");
    expect(title.length).toBe(33);
  });

  it("恰好 30 字符不截断", () => {
    const exact = "a".repeat(30);
    expect(deriveTitle(exact)).toBe(exact);
  });

  it("压缩连续空白", () => {
    expect(deriveTitle("hello    world")).toBe("hello world");
  });

  it("去除前后空白", () => {
    expect(deriveTitle("  hello  ")).toBe("hello");
  });
});

describe("groupSession", () => {
  const NOW = new Date("2026-01-15T12:00:00").getTime();
  const ONE_DAY = 24 * 60 * 60 * 1000;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeSession(updatedAt: number, archived = false): SessionMeta {
    return {
      id: "s",
      title: "t",
      createdAt: updatedAt,
      updatedAt,
      messageCount: 0,
      status: "idle",
      archived,
      pinned: false,
    };
  }

  it("今天", () => {
    expect(groupSession(makeSession(NOW - 1000))).toBe("today");
    expect(groupSession(makeSession(NOW - ONE_DAY + 1000))).toBe("today");
  });

  it("本周", () => {
    expect(groupSession(makeSession(NOW - ONE_DAY - 1000))).toBe("this_week");
    expect(groupSession(makeSession(NOW - 6 * ONE_DAY))).toBe("this_week");
  });

  it("更早", () => {
    expect(groupSession(makeSession(NOW - 8 * ONE_DAY))).toBe("earlier");
  });

  it("归档优先", () => {
    expect(groupSession(makeSession(NOW, true))).toBe("archived");
    expect(groupSession(makeSession(NOW - 100 * ONE_DAY, true))).toBe("archived");
  });
});