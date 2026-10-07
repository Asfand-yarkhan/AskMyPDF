import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, Check, CloudUpload, Cpu, FileText, Loader2, RotateCcw, Scissors, ScanSearch, X,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { MAX_UPLOAD_MB } from "@/api/client";
import type { DocumentInfo } from "@/api/types";
import { ChunkConfigCard } from "@/components/ChunkConfigCard";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useUpload } from "@/hooks/useUpload";
import { cn, formatBytes } from "@/lib/utils";

const STEPS = [
  { id: "uploading", label: "Uploading", icon: CloudUpload },
  { id: "parsing", label: "Parsing", icon: ScanSearch },
  { id: "chunking", label: "Chunking", icon: Scissors },
  { id: "embedding", label: "Embedding", icon: Cpu },
] as const;

// Server stages mapped onto the four visible steps.
const STEP_INDEX: Record<string, number> = {
  uploading: 0, uploaded: 1, parsing: 1, analyzing: 1, chunking: 2, embedding: 3, done: 4,
};

export function UploadDropzone({ onReady }: { onReady: (doc: DocumentInfo) => void }) {
  const { state, start, cancel, reset } = useUpload();
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = !["idle", "done", "error"].includes(state.stage);

  const pick = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) void start(file);
    },
    [start],
  );

  if (state.stage === "idle") {
    return (
      <motion.div
        layout
        role="button"
        tabIndex={0}
        aria-label="Upload a PDF: drop a file here or press Enter to browse"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), inputRef.current?.click())}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files);
        }}
        animate={{ scale: dragging ? 1.02 : 1 }}
        className={cn(
          "focus-ring glass group relative flex cursor-pointer flex-col items-center justify-center overflow-hidden rounded-3xl border-2 border-dashed px-6 py-14 text-center transition-colors sm:py-20",
          dragging ? "border-primary bg-primary/10" : "border-primary/30 hover:border-primary/60",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            pick(e.target.files);
            e.target.value = "";
          }}
        />
        <motion.div
          animate={{ y: dragging ? -8 : [0, -6, 0] }}
          transition={dragging ? { duration: 0.2 } : { duration: 3, repeat: Infinity, ease: "easeInOut" }}
          className="grid size-20 place-items-center rounded-3xl bg-gradient-to-br from-violet-500 via-fuchsia-500 to-cyan-400 text-white shadow-2xl shadow-violet-500/40"
        >
          <CloudUpload className="size-9" />
        </motion.div>
        <h2 className="mt-6 text-xl font-semibold tracking-tight sm:text-2xl">
          {dragging ? "Drop it like it's hot" : "Drop your PDF here"}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          or <span className="font-medium text-primary underline-offset-4 group-hover:underline">browse files</span>{" "}
          · up to {MAX_UPLOAD_MB} MB · scanned PDFs supported (OCR)
        </p>
      </motion.div>
    );
  }

  const current = STEP_INDEX[state.stage] ?? 0;

  return (
    <motion.div layout initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="glass rounded-3xl p-5 sm:p-8">
      <div className="flex items-center gap-3">
        <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-primary/10 text-primary">
          <FileText className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{state.file?.name}</p>
          <p className="text-xs text-muted-foreground">{state.file && formatBytes(state.file.size)}</p>
        </div>
        {busy && (
          <Button variant="ghost" size="icon-sm" onClick={cancel} aria-label="Cancel upload">
            <X />
          </Button>
        )}
      </div>

      <ol className="mt-6 grid grid-cols-4 gap-2">
        {STEPS.map((step, i) => {
          const done = current > i || state.stage === "done";
          const active = current === i && busy;
          const Icon = step.icon;
          return (
            <li key={step.id} className="flex flex-col items-center gap-2 text-center">
              <motion.div
                animate={{ scale: active ? 1.08 : 1 }}
                className={cn(
                  "grid size-10 place-items-center rounded-2xl transition-colors",
                  done && "bg-success text-success-foreground",
                  active && "bg-primary text-primary-foreground shadow-lg shadow-primary/30",
                  !done && !active && "bg-secondary text-muted-foreground",
                  state.stage === "error" && active && "bg-destructive",
                )}
              >
                <AnimatePresence mode="wait" initial={false}>
                  {done ? (
                    <motion.span key="done" initial={{ scale: 0 }} animate={{ scale: 1 }}>
                      <Check className="size-5" />
                    </motion.span>
                  ) : active ? (
                    <motion.span key="active" initial={{ scale: 0 }} animate={{ scale: 1 }}>
                      <Loader2 className="size-5 animate-spin" />
                    </motion.span>
                  ) : (
                    <Icon className="size-5" />
                  )}
                </AnimatePresence>
              </motion.div>
              <span className={cn("text-xs font-medium", active ? "text-foreground" : "text-muted-foreground")}>
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>

      <Progress value={state.progress} shimmer={busy} className="mt-6" />
      <p className="mt-3 min-h-5 text-center text-sm text-muted-foreground" aria-live="polite">
        {state.stage === "error" ? <span className="text-destructive">{state.error}</span> : state.message}
      </p>

      <AnimatePresence>
        {state.stage === "done" && state.result && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="mt-5 space-y-4">
            <ChunkConfigCard doc={state.result} />
            <Button size="lg" className="w-full" onClick={() => onReady(state.result!)} autoFocus>
              Start chatting <ArrowRight />
            </Button>
          </motion.div>
        )}
        {state.stage === "error" && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-5 flex justify-center">
            <Button variant="outline" onClick={reset}>
              <RotateCcw /> Try another file
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
