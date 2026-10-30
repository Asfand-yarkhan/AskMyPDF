import type {
  ChatEvent,
  ChatTurn,
  DocumentInfo,
  GradeItem,
  GradeResponse,
  Health,
  Me,
  UploadEvent,
} from "./types";

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "/api";
// Defaults matching the backend; the server enforces its configured values and the
// upload screen shows the live ones from /health.
export const MAX_UPLOAD_MB = 50;
export const MAX_PAGES = 100;

/** Codes the backend attaches to errors the UI should act on, not just show. */
export type ApiErrorCode = "trial_exhausted" | "signup_required" | "email_unverified" | "document_limit";

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code?: ApiErrorCode,
  ) {
    super(message);
  }
}

let tokenProvider: (() => Promise<string | null>) | null = null;

/** Registered by the auth module: every request carries the Firebase ID token. */
export function setTokenProvider(provider: () => Promise<string | null>) {
  tokenProvider = provider;
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = tokenProvider ? await tokenProvider() : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function parseErrorBody(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(detail, status);
  if (Array.isArray(detail)) return new ApiError(detail.map((d: { msg: string }) => d.msg).join(", "), status);
  if (detail && typeof detail === "object" && "message" in detail) {
    const { message, code } = detail as { message: string; code?: ApiErrorCode };
    return new ApiError(message, status, code);
  }
  return new ApiError(`Request failed (${status})`, status);
}

async function errorFrom(res: Response): Promise<ApiError> {
  try {
    return parseErrorBody(res.status, await res.json());
  } catch {
    return parseErrorBody(res.status, null); // non-JSON error body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers: { ...(await authHeaders()), ...init?.headers } });
  } catch {
    throw new ApiError("Cannot reach the AskMyPDF server. Is the backend running?");
  }
  if (!res.ok) throw await errorFrom(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  me: () => request<Me>("/me"),
  claim: (guestToken: string) =>
    request<{ moved: number }>("/me/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ guest_token: guestToken }),
    }),
  listDocuments: () => request<DocumentInfo[]>("/documents"),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  /** Opened in a new tab, which can't send headers: the signed token proves access. */
  fileUrl: (doc: Pick<DocumentInfo, "doc_id" | "file_token">) =>
    `${API_URL}/documents/${doc.doc_id}/file${doc.file_token ? `?token=${encodeURIComponent(doc.file_token)}` : ""}`,
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
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(await authHeaders()) },
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
  let aborted = false;
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
        let body: unknown = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* non-JSON error body */
        }
        return reject(parseErrorBody(xhr.status, body));
      }
      consume();
      if (result) resolve(result);
      else reject(new ApiError(failure ?? "Processing failed. Please try another PDF."));
    };
    xhr.onerror = () => reject(new ApiError("Network error during upload. Is the backend running?"));
    xhr.onabort = () => reject(new ApiError("Upload cancelled."));

    const form = new FormData();
    form.append("file", file);
    void authHeaders().then((headers) => {
      if (aborted) return reject(new ApiError("Upload cancelled."));
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
      xhr.send(form);
    }, reject);
  });
  return {
    promise,
    abort: () => {
      aborted = true;
      xhr.abort();
    },
  };
}
