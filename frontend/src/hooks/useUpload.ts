import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import { MAX_UPLOAD_MB, uploadPdf } from "@/api/client";
import type { DocumentInfo, UploadStage } from "@/api/types";
import { useAppStore } from "@/store/useAppStore";

export interface UploadState {
  file: File | null;
  stage: UploadStage | "idle" | "error";
  progress: number; // 0..1 overall
  message: string;
  result: DocumentInfo | null;
  reused: boolean;
  error: string | null;
}

const INITIAL: UploadState = {
  file: null,
  stage: "idle",
  progress: 0,
  message: "",
  result: null,
  reused: false,
  error: null,
};

// Byte upload is the first 20% of the bar; server stages fill the rest.
const UPLOAD_SHARE = 0.2;

export function validatePdf(file: File): string | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Only PDF files are supported.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `File is larger than ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export function useUpload() {
  const [state, setState] = useState<UploadState>(INITIAL);
  const abortRef = useRef<(() => void) | null>(null);
  const upsertDocument = useAppStore((s) => s.upsertDocument);

  const start = useCallback(
    async (file: File) => {
      const invalid = validatePdf(file);
      if (invalid) {
        toast.error(invalid);
        return;
      }
      setState({ ...INITIAL, file, stage: "uploading", message: "Uploading..." });
      const { promise, abort } = uploadPdf(file, {
        onUploadProgress: (f) =>
          setState((s) => (s.stage === "uploading" ? { ...s, progress: f * UPLOAD_SHARE } : s)),
        onEvent: (event) => {
          if (event.type !== "progress") return;
          setState((s) => ({
            ...s,
            stage: event.stage,
            message: event.message,
            progress: Math.max(s.progress, UPLOAD_SHARE + event.progress * (1 - UPLOAD_SHARE)),
          }));
        },
      });
      abortRef.current = abort;
      try {
        const { document, reused } = await promise;
        upsertDocument(document);
        setState((s) => ({ ...s, stage: "done", progress: 1, result: document, reused }));
        toast.success(reused ? "Already indexed. Ready instantly." : "Document ready!", {
          description: `${document.chunk_count} chunks · ${document.chunk_config.strategy} strategy (${document.chunk_config.chunk_size}/${document.chunk_config.chunk_overlap})`,
        });
      } catch (err) {
        const message = (err as Error).message;
        setState((s) => ({ ...s, stage: "error", error: message }));
        toast.error(message);
      } finally {
        abortRef.current = null;
      }
    },
    [upsertDocument],
  );

  const cancel = useCallback(() => abortRef.current?.(), []);
  const reset = useCallback(() => setState(INITIAL), []);

  return { state, start, cancel, reset };
}
