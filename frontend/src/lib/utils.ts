import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const modKey = isMac ? "⌘" : "Ctrl";

/**
 * Matches [p. 3], [p. 3-4], [pp. 3, 5], [p. 3, p. 7] and multi-document [Doc 2, p. 3] tags.
 * Some models emit 【p. 3】 brackets or exotic dashes instead.
 */
export const CITATION_RE =
  /[[【](?:doc\s*(\d+)\s*[,:|·-]?\s*)?(?:pp?\.\s*)(\d+(?:\s*[-‐‑‒–—,]\s*(?:p\.\s*)?\d+)*)[\]】]/gi;

/**
 * Turn citation tags into markdown links with a `cite:<doc>:<page>` scheme that the renderer
 * turns into chips (`doc` is 0 for single-document answers).
 */
export function linkifyCitations(markdown: string): string {
  return markdown.replace(CITATION_RE, (_match, doc: string | undefined, body: string) => {
    const docNumber = doc ? Number.parseInt(doc, 10) : 0;
    const pages = body
      .split(",")
      .map((part) => part.replace(/p\.\s*/i, "").trim())
      .filter(Boolean);
    return pages
      .map((p) => {
        const first = p.split(/[-‐‑‒–—]/)[0].trim();
        const range = p.replace(/\s+/g, "").replace(/[‐‑‒—]/g, "–");
        const label = docNumber ? `D${docNumber} · p. ${range}` : `p. ${range}`;
        return `[${label}](cite:${docNumber}:${first})`;
      })
      .join(" ");
  });
}

/** Parse a `cite:<doc>:<page>` href (also accepts the old `cite:<page>` form). */
export function parseCiteHref(href: string): { doc: number; page: number } | null {
  const m = /^cite:(?:(\d+):)?(\d+)$/.exec(href);
  return m ? { doc: m[1] ? Number(m[1]) : 0, page: Number(m[2]) } : null;
}

export const STRATEGY_LABELS: Record<string, string> = {
  short: "Short doc",
  notes: "Notes",
  slides: "Slides",
  general: "Report / book",
  technical: "Technical",
};
