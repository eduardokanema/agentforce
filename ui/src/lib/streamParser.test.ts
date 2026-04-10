import { describe, expect, it } from "vitest";
import { LINE_CLASSES, parseStreamLine } from "./streamParser";

describe("parseStreamLine", () => {
  it("detects inject, command, pass, fail, warn, path, and default lines", () => {
    expect(parseStreamLine("[USER INSTRUCTION] do this")).toEqual({
      type: "inject",
      raw: "[USER INSTRUCTION] do this",
    });
    expect(parseStreamLine("$ npm test")).toEqual({
      type: "command",
      raw: "$ npm test",
    });
    expect(parseStreamLine("PASSED 5 tests")).toEqual({
      type: "pass",
      raw: "PASSED 5 tests",
    });
    expect(parseStreamLine("FAILED with ERROR")).toEqual({
      type: "fail",
      raw: "FAILED with ERROR",
    });
    expect(parseStreamLine("WARN: caution")).toEqual({
      type: "warn",
      raw: "WARN: caution",
    });
    expect(
      parseStreamLine(
        "see /Users/eduardo/Projects/agentforce/ui/src/lib/ansi.ts",
      ),
    ).toEqual({
      type: "path",
      raw: "see /Users/eduardo/Projects/agentforce/ui/src/lib/ansi.ts",
    });
    expect(parseStreamLine("plain text")).toEqual({
      type: "default",
      raw: "plain text",
    });
  });

  it("exposes the requested line classes", () => {
    expect(LINE_CLASSES).toMatchObject({
      inject: "bg-amber-bg/60 px-2 rounded-sm text-amber font-bold",
      command: "text-cyan opacity-90",
      pass: "text-green",
      fail: "text-red",
      warn: "text-amber",
      path: "text-dim",
      default: "",
    });
  });
});
