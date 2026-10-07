import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, ExternalLink, FileWarning, Minus, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { api } from "@/api/client";
import type { DocumentInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

const ZOOMS = [0.6, 0.8, 1, 1.25, 1.5, 2];

export function PdfViewer({ doc, onClose }: { doc: DocumentInfo; onClose?: () => void }) {
  const page = useAppStore((s) => s.pdfPage);
  const jumpKey = useAppStore((s) => s.pdfJumpKey);
  const setPage = useAppStore((s) => s.setPdfPage);
  const [numPages, setNumPages] = useState(doc.page_count);
  const [zoomIndex, setZoomIndex] = useState(2);
  const [width, setWidth] = useState(400);
  const [pageInput, setPageInput] = useState(String(page));
  const [highlight, setHighlight] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const fileUrl = api.fileUrl(doc.doc_id);

  // Fit the page to the panel width.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(200, entry.contentRect.width - 32)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => setPageInput(String(page)), [page]);

  // Flash the page when a citation chip jumps here.
  useEffect(() => {
    if (!jumpKey) return;
    setHighlight(true);
    containerRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    const t = window.setTimeout(() => setHighlight(false), 1400);
    return () => window.clearTimeout(t);
  }, [jumpKey]);

  const clamped = Math.min(Math.max(page, 1), numPages || 1);
  const go = (p: number) => setPage(Math.min(Math.max(p, 1), numPages || 1));

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-border/60 px-3 py-2">
        <Button variant="ghost" size="icon-sm" onClick={() => go(clamped - 1)} disabled={clamped <= 1} aria-label="Previous page">
          <ChevronLeft />
        </Button>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const n = Number.parseInt(pageInput, 10);
            if (!Number.isNaN(n)) go(n);
          }}
          className="flex items-center gap-1 text-xs text-muted-foreground"
        >
          <input
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ""))}
            onBlur={() => setPageInput(String(clamped))}
            aria-label="Page number"
            className="focus-ring h-7 w-10 rounded-md border border-border bg-background/60 text-center text-xs tabular-nums text-foreground"
          />
          <span className="tabular-nums">/ {numPages}</span>
        </form>
        <Button variant="ghost" size="icon-sm" onClick={() => go(clamped + 1)} disabled={clamped >= numPages} aria-label="Next page">
          <ChevronRight />
        </Button>
        <div className="mx-1 h-4 w-px bg-border" />
        <Button variant="ghost" size="icon-sm" onClick={() => setZoomIndex((z) => Math.max(0, z - 1))} disabled={zoomIndex === 0} aria-label="Zoom out">
          <Minus />
        </Button>
        <span className="w-10 text-center text-xs tabular-nums text-muted-foreground">{Math.round(ZOOMS[zoomIndex] * 100)}%</span>
        <Button variant="ghost" size="icon-sm" onClick={() => setZoomIndex((z) => Math.min(ZOOMS.length - 1, z + 1))} disabled={zoomIndex === ZOOMS.length - 1} aria-label="Zoom in">
          <Plus />
        </Button>
        <div className="ml-auto flex items-center">
          <Button variant="ghost" size="icon-sm" asChild aria-label="Open PDF in new tab">
            <a href={`${fileUrl}#page=${clamped}`} target="_blank" rel="noreferrer">
              <ExternalLink />
            </a>
          </Button>
          {onClose && (
            <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close PDF viewer">
              <X />
            </Button>
          )}
        </div>
      </div>

      <div ref={containerRef} className="flex-1 overflow-auto bg-muted/30 p-4 scrollbar-thin">
        <Document
          file={fileUrl}
          onLoadSuccess={({ numPages: n }) => setNumPages(n)}
          loading={<PageSkeleton />}
          error={
            <div className="flex flex-col items-center gap-2 py-16 text-center text-sm text-muted-foreground">
              <FileWarning className="size-8" />
              Could not load the PDF preview.
            </div>
          }
          className="flex justify-center"
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={clamped}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.18 }}
              className={cn(
                "overflow-hidden rounded-lg bg-white shadow-xl ring-1 ring-black/5 transition-shadow",
                highlight && "animate-pulse-ring ring-2 ring-primary",
              )}
            >
              <Page pageNumber={clamped} width={width * ZOOMS[zoomIndex]} loading={<PageSkeleton />} />
            </motion.div>
          </AnimatePresence>
        </Document>
      </div>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-md space-y-3 rounded-lg bg-card p-6">
      <Skeleton className="h-5 w-2/3" />
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} className={cn("h-3", i % 3 === 2 ? "w-4/5" : "w-full")} />
      ))}
    </div>
  );
}
