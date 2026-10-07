import type {
  ChatEvent,
  ChatTurn,
  DocumentInfo,
  GradeItem,
  GradeResponse,
  Health,
  UploadEvent,
} from "./types";

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "/api";
// Defaults matching the backend; the server enforces its configured values and the
// upload screen shows the live ones from /health.
export const MAX_UPLOAD_MB = 50;
export const MAX_PAGES = 100;

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join(", ");
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(message, res.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError("Cannot reach the AskMyPDF server. Is the backend running?");
  }
  if (!res.ok) throw await errorFrom(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  listDocuments: () => request<DocumentInfo[]>("/documents"),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  fileUrl: (id: string) => `${API_URL}/documents/${id}/file`,
  grade: (items: GradeItem[], docId?: string) =>
    request<GradeResponse>("/quiz/grade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: docId, items }),
    }),
};

/** Incremental parser for `data: {...}\n\n` Server-Sent Event frames. */
export function createSSEParser<T>(onEvent: (event: T) => void) {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk.replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!data) continue;
      try {
        onEvent(JSON.parse(data) as T);
      } catch {
        console.warn("Malformed SSE frame", data);
      }
    }
  };
}

export async function streamChat(
  body: { doc_id: string; extra_doc_ids?: string[]; message: string; history: ChatTurn[] },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Cannot reach the AskMyPDF server. Is the backend running?");
  }
  if (!res.ok || !res.body) throw await errorFrom(res);

  const parse = createSSEParser<ChatEvent>(onEvent);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    parse(value);
  }
}

/**
 * Upload via XHR so we get real byte progress, then read the streamed ingestion
 * stages (parsing -> chunking -> embedding) from the same response.
 */
export function uploadPdf(
  file: File,
  handlers: { onUploadProgress: (fraction: number) => void; onEvent: (event: UploadEvent) => void },
): { promise: Promise<{ document: DocumentInfo; reused: boolean }>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<{ document: DocumentInfo; reused: boolean }>((resolve, reject) => {
    let seen = 0;
    let result: { document: DocumentInfo; reused: boolean } | null = null;
    let failure: string | null = null;
    const parse = createSSEParser<UploadEvent>((event) => {
      if (event.type === "complete") result = { document: event.document, reused: event.reused };
      if (event.type === "error") failure = event.message;
      handlers.onEvent(event);
    });
    const consume = () => {
      const text = xhr.responseText;
      if (xhr.status < 400 && text.length > seen) {
        parse(text.slice(seen));
        seen = text.length;
      }
    };

    xhr.open("POST", `${API_URL}/upload?stream=true`);
    xhr.upload.onprogress = (e) => e.lengthComputable && handlers.onUploadProgress(e.loaded / e.total);
    xhr.onprogress = consume;
    xhr.onload = () => {
      if (xhr.status >= 400) {
        let message = `Upload failed (${xhr.status})`;
        try {
          message = JSON.parse(xhr.responseText).detail ?? message;
        } catch {
          /* ignore */
        }
        return reject(new ApiError(message, xhr.status));
      }
      consume();
      if (result) resolve(result);
      else reject(new ApiError(failure ?? "Processing failed. Please try another PDF."));
    };
    xhr.onerror = () => reject(new ApiError("Network error during upload. Is the backend running?"));
    xhr.onabort = () => reject(new ApiError("Upload cancelled."));

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}
