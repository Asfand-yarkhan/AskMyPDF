import { describe, expect, it } from "vitest";
import { linkifyCitations, parseCiteHref } from "@/lib/utils";

describe("linkifyCitations", () => {
  it("turns page tags into cite links", () => {
    expect(linkifyCitations("CGPA is 3.52 [p. 5].")).toBe("CGPA is 3.52 [p. 5](cite:0:5).");
  });

  it("splits page lists and keeps ranges", () => {
    expect(linkifyCitations("[pp. 3, 7]")).toBe("[p. 3](cite:0:3) [p. 7](cite:0:7)");
    expect(linkifyCitations("[p. 3-4]")).toBe("[p. 3-4](cite:0:3)");
  });

  it("normalizes exotic dashes and brackets from some models", () => {
    expect(linkifyCitations("【p. 1‑3】")).toBe("[p. 1–3](cite:0:1)");
    expect(linkifyCitations("【p. 9】")).toBe("[p. 9](cite:0:9)");
  });

  it("handles multi-document tags", () => {
    expect(linkifyCitations("[Doc 2, p. 4]")).toBe("[D2 · p. 4](cite:2:4)");
    expect(linkifyCitations("[doc 1 p. 10]")).toBe("[D1 · p. 10](cite:1:10)");
  });

  it("leaves normal links and brackets alone", () => {
    const text = "See [the docs](https://example.com) and [note].";
    expect(linkifyCitations(text)).toBe(text);
  });
});

describe("parseCiteHref", () => {
  it("parses new and legacy formats", () => {
    expect(parseCiteHref("cite:2:7")).toEqual({ doc: 2, page: 7 });
    expect(parseCiteHref("cite:7")).toEqual({ doc: 0, page: 7 });
    expect(parseCiteHref("https://x")).toBeNull();
  });
});
