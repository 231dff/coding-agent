import { describe, expect, it } from "vitest";
import { inferLanguage } from "./artifact";

describe("inferLanguage", () => {
  it("常见语言识别", () => {
    expect(inferLanguage("a.py")).toBe("python");
    expect(inferLanguage("a.ts")).toBe("typescript");
    expect(inferLanguage("a.tsx")).toBe("tsx");
    expect(inferLanguage("a.js")).toBe("javascript");
    expect(inferLanguage("a.jsx")).toBe("jsx");
    expect(inferLanguage("a.json")).toBe("json");
    expect(inferLanguage("a.md")).toBe("markdown");
    expect(inferLanguage("a.yaml")).toBe("yaml");
    expect(inferLanguage("a.yml")).toBe("yaml");
    expect(inferLanguage("a.toml")).toBe("toml");
    expect(inferLanguage("a.css")).toBe("css");
    expect(inferLanguage("a.html")).toBe("html");
    expect(inferLanguage("a.sh")).toBe("bash");
  });

  it("大小写不敏感", () => {
    expect(inferLanguage("a.PY")).toBe("python");
    expect(inferLanguage("a.Ts")).toBe("typescript");
  });

  it("未知扩展名返回 undefined", () => {
    expect(inferLanguage("a.xyz")).toBeUndefined();
    expect(inferLanguage("a")).toBeUndefined();
  });

  it("多级扩展名取最后一个", () => {
    expect(inferLanguage("a.test.py")).toBe("python");
  });
});