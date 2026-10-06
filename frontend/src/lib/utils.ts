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

/** Matches [p. 3], [p. 3-4], [pp. 3, 5], [p. 3, p. 7] tags; some models emit 【p. 3】 instead. */
export const CITATION_RE = /[[【](?:pp?\.\s*)(\d+(?:\s*[-–,]\s*(?:p\.\s*)?\d+)*)[\]】]/gi;

/** Turn citation tags into markdown links with a cite: scheme the renderer turns into chips. */
export function linkifyCitations(markdown: string): string {
  return markdown.replace(CITATION_RE, (_match, body: string) => {
    const pages = body
      .split(",")
      .map((part) => part.replace(/p\.\s*/i, "").trim())
      .filter(Boolean);
    return pages
      .map((p) => {
        const first = p.split(/[-–]/)[0].trim();
        return `[p. ${p.replace(/\s+/g, "")}](cite:${first})`;
      })
      .join(" ");
  });
}

export const STRATEGY_LABELS: Record<string, string> = {
  short: "Short doc",
  notes: "Notes",
  slides: "Slides",
  general: "Report / book",
  technical: "Technical",
};
