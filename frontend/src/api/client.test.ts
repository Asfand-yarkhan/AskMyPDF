import { describe, expect, it } from "vitest";
import { createSSEParser } from "@/api/client";

describe("createSSEParser", () => {
  it("parses events split across arbitrary network chunks", () => {
    const events: unknown[] = [];
    const feed = createSSEParser((e) => events.push(e));
    feed('data: {"type":"tok');
    feed('en","content":"Hel"}\n\ndata: {"type":"token","content":"lo"}\n');
    expect(events).toEqual([{ type: "token", content: "Hel" }]);
    feed("\n");
    expect(events).toHaveLength(2);
  });

  it("handles CRLF line endings and skips malformed frames", () => {
    const events: unknown[] = [];
    const feed = createSSEParser((e) => events.push(e));
    feed('data: {"type":"done"}\r\n\r\ndata: not-json\n\n: comment\n\n');
    expect(events).toEqual([{ type: "done" }]);
  });

  it("keeps unicode intact", () => {
    const events: { content: string }[] = [];
    const feed = createSSEParser<{ content: string }>((e) => events.push(e));
    feed('data: {"content":"خلاصہ ✓"}\n\n');
    expect(events[0].content).toBe("خلاصہ ✓");
  });
});
