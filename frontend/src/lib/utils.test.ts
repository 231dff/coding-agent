import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("合并类名", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("过滤 falsy 值", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });

  it("条件类名", () => {
    expect(cn("base", true && "active", false && "hidden")).toBe(
      "base active"
    );
  });

  it("Tailwind 冲突时后者覆盖前者", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("Tailwind 条件类正确覆盖", () => {
    expect(cn("p-2", { "p-4": true, "m-2": false })).toBe("p-4");
  });

  it("空输入返回空字符串", () => {
    expect(cn()).toBe("");
  });
});