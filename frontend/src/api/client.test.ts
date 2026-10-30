import { describe, expect, it } from "vitest";
import { api, createSSEParser, parseErrorBody } from "@/api/client";

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

describe("parseErrorBody", () => {
  it("keeps the code of errors the UI acts on", () => {
    const err = parseErrorBody(403, { detail: { code: "trial_exhausted", message: "Create an account." } });
    expect(err.code).toBe("trial_exhausted");
    expect(err.message).toBe("Create an account.");
    expect(err.status).toBe(403);
  });

  it("handles plain, validation and empty error bodies", () => {
    expect(parseErrorBody(404, { detail: "Not found" }).message).toBe("Not found");
    expect(parseErrorBody(422, { detail: [{ msg: "a" }, { msg: "b" }] }).message).toBe("a, b");
    expect(parseErrorBody(500, null).message).toBe("Request failed (500)");
  });
});

describe("api.fileUrl", () => {
  it("adds the signed token when the document has one", () => {
    expect(api.fileUrl({ doc_id: "abc123", file_token: "1700.x/y" })).toBe("/api/documents/abc123/file?token=1700.x%2Fy");
    expect(api.fileUrl({ doc_id: "abc123" })).toBe("/api/documents/abc123/file");
  });
});
