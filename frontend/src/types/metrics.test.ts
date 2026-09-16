import { describe, expect, it } from "vitest";
import { formatNumber, formatCost, formatTimestamp } from "./metrics";

describe("formatNumber", () => {
  it("小于 1000 时直接显示", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(42)).toBe("42");
    expect(formatNumber(999)).toBe("999");
  });

  it("千级用 k 后缀", () => {
    expect(formatNumber(1000)).toBe("1.0k");
    expect(formatNumber(1500)).toBe("1.5k");
    expect(formatNumber(999_999)).toBe("1000.0k");
  });

  it("百万级用 M 后缀", () => {
    expect(formatNumber(1_000_000)).toBe("1.00M");
    expect(formatNumber(2_500_000)).toBe("2.50M");
  });

  it("小数四舍五入", () => {
    expect(formatNumber(999.6)).toBe("1000");
  });
});

describe("formatCost", () => {
  it("0 返回 $0.00", () => {
    expect(formatCost(0)).toBe("$0.00");
  });

  it("小于 0.01 用 4 位小数", () => {
    expect(formatCost(0.0012)).toBe("$0.0012");
    expect(formatCost(0.009)).toBe("$0.0090");
  });

  it("小于 1 用 3 位小数", () => {
    expect(formatCost(0.123)).toBe("$0.123");
    expect(formatCost(0.999)).toBe("$0.999");
  });

  it("大于 1 用 2 位小数", () => {
    expect(formatCost(1.234)).toBe("$1.23");
    expect(formatCost(10.999)).toBe("$11.00");
  });
});

describe("formatTimestamp", () => {
  it("1h 范围显示 HH:MM", () => {
    const ts = new Date("2026-01-15T14:30:00").getTime() / 1000;
    const result = formatTimestamp(ts, "1h");
    expect(result).toMatch(/^\d{2}:\d{2}$/);
  });

  it("24h 范围显示 HH:00", () => {
    const ts = new Date("2026-01-15T14:30:00").getTime() / 1000;
    const result = formatTimestamp(ts, "24h");
    expect(result).toMatch(/^\d{2}:00$/);
  });

  it("7d 范围显示 MM/DD", () => {
    const ts = new Date("2026-01-15T14:30:00").getTime() / 1000;
    const result = formatTimestamp(ts, "7d");
    expect(result).toMatch(/^\d{1,2}\/\d{1,2}$/);
  });
});