import { BookOpen, ExternalLink } from "lucide-react";
import { api } from "@/api/client";
import type { SourceChunk } from "@/api/types";
import { useCitationScope } from "@/components/CitationContext";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

const PREVIEW_CHARS = 420;

function findSource(sources: SourceChunk[], docId: string | undefined, page: number): SourceChunk | undefined {
  const sameDoc = sources.filter((s) => !docId || !s.doc_id || s.doc_id === docId);
  return (
    sameDoc.find((s) => s.page === page) ??
    sameDoc.find((s) => s.page <= page && page <= s.page_end)
  );
}

function snippet(text: string): string {
  const flat = text.replace(/\|/g, " ").replace(/-{3,}/g, "").replace(/\s+/g, " ").trim();
  return flat.length > PREVIEW_CHARS ? `${flat.slice(0, PREVIEW_CHARS).trimEnd()}…` : flat;
}

/**
 * Page citation. Hover shows the passage the answer used; click opens the original PDF at
 * that page in a new tab (the browser's PDF viewer).
 */
export function CitationChip({
  page,
  docNumber = 0,
  label,
  className,
}: {
  page: number;
  docNumber?: number;
  label?: string;
  className?: string;
}) {
  const activeDocId = useAppStore((s) => s.activeDocId);
  const documents = useAppStore((s) => s.documents);
  const scope = useCitationScope();
  const docId = (docNumber > 0 ? scope.docIds[docNumber - 1] : scope.docIds[0]) ?? activeDocId ?? undefined;
  const filename = documents.find((d) => d.doc_id === docId)?.filename;
  const source = findSource(scope.sources, docId, page);

  const chipClass = cn(
    "focus-ring mx-0.5 inline-flex translate-y-[-1px] items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 align-middle text-[11px] font-semibold text-primary no-underline ring-1 ring-inset ring-primary/25 transition hover:bg-primary hover:text-primary-foreground",
    className,
  );
  const content = (
    <>
      <BookOpen className="size-3" />
      {label ?? `p. ${page}`}
    </>
  );
  if (!docId) return <span className={chipClass}>{content}</span>;

  const chip = (
    <a href={`${api.fileUrl(docId)}#page=${page}`} target="_blank" rel="noreferrer" className={chipClass}>
      {content}
    </a>
  );

  const preview = (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-primary">
        <BookOpen className="size-3" />
        <span className="truncate">
          {docNumber > 0 && filename ? `${filename} · ` : ""}Page {page}
          {source?.section ? ` · ${source.section}` : ""}
        </span>
      </div>
      {source ? (
        <p className="text-xs leading-relaxed text-foreground/85">{snippet(source.text)}</p>
      ) : (
        <p className="text-xs text-muted-foreground">Open this page of the PDF.</p>
      )}
      <p className="flex items-center gap-1 text-[10px] text-muted-foreground">
        <ExternalLink className="size-3" /> Click to open the PDF at this page
      </p>
    </div>
  );

  return (
    <Tooltip
      content={preview}
      delayDuration={150}
      className="glass w-80 max-w-[calc(100vw-2rem)] rounded-xl bg-popover/95 p-3 font-normal text-popover-foreground"
    >
      {chip}
    </Tooltip>
  );
}
