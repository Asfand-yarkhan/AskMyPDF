import { AnimatePresence, motion } from "framer-motion";
import { Check, FileText, Files, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { DocumentInfo } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useAppStore, useExtraDocIds } from "@/store/useAppStore";

const MAX_EXTRA = 4;

/** Header control: choose other documents to search together with the active one. */
export function DocumentScopePicker({ doc }: { doc: DocumentInfo }) {
  const documents = useAppStore((s) => s.documents);
  const setExtraDocs = useAppStore((s) => s.setExtraDocs);
  const extra = useExtraDocIds().filter((id) => documents.some((d) => d.doc_id === id));
  const others = documents.filter((d) => d.doc_id !== doc.doc_id);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!others.length) return null;

  const toggle = (id: string) =>
    setExtraDocs(doc.doc_id, extra.includes(id) ? extra.filter((i) => i !== id) : [...extra, id].slice(0, MAX_EXTRA));

  return (
    <div className="relative" ref={ref}>
      <Tooltip content="Search other documents too">
        <Button
          variant={extra.length ? "secondary" : "ghost"}
          size={extra.length ? "sm" : "icon"}
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label="Choose documents to search"
        >
          <Files />
          {extra.length > 0 && <span>+{extra.length}</span>}
        </Button>
      </Tooltip>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            className="glass absolute right-0 top-full z-30 mt-2 w-[min(20rem,calc(100vw-2rem))] rounded-2xl bg-popover/95 p-3"
            role="dialog"
            aria-label="Documents to search"
          >
            <p className="text-sm font-semibold">Search in</p>
            <p className="mb-2 text-xs text-muted-foreground">
              Questions and explanations search all selected documents. Summaries, quizzes and flashcards use only the
              current one.
            </p>
            <div className="flex items-center gap-2 rounded-xl bg-primary/10 px-3 py-2 text-sm">
              <FileText className="size-4 shrink-0 text-primary" />
              <span className="truncate font-medium">{doc.filename}</span>
              <Badge className="ml-auto shrink-0">current</Badge>
            </div>
            <ul className="mt-1 max-h-64 space-y-1 overflow-y-auto scrollbar-thin">
              {others.map((d) => {
                const checked = extra.includes(d.doc_id);
                const disabled = !checked && extra.length >= MAX_EXTRA;
                return (
                  <li key={d.doc_id}>
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={checked}
                      disabled={disabled}
                      onClick={() => toggle(d.doc_id)}
                      className="focus-ring flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-secondary disabled:opacity-50"
                    >
                      <span
                        className={cn(
                          "grid size-4 shrink-0 place-items-center rounded border",
                          checked ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground/40",
                        )}
                      >
                        {checked && <Check className="size-3" />}
                      </span>
                      <span className="truncate">{d.filename}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{d.page_count} p.</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {extra.length >= MAX_EXTRA && <p className="mt-2 text-[11px] text-muted-foreground">Up to {MAX_EXTRA} extra documents.</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Chips under the header listing extra documents in scope (click × to remove). */
export function ScopeChips({ doc }: { doc: DocumentInfo }) {
  const documents = useAppStore((s) => s.documents);
  const setExtraDocs = useAppStore((s) => s.setExtraDocs);
  const extra = useExtraDocIds();
  const selected = documents.filter((d) => extra.includes(d.doc_id));
  if (!selected.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-border/60 px-3 py-2 text-xs sm:px-5">
      <span className="text-muted-foreground">Also searching:</span>
      {selected.map((d) => (
        <span key={d.doc_id} className="inline-flex max-w-[14rem] items-center gap-1 rounded-full bg-secondary py-0.5 pl-2.5 pr-1">
          <span className="truncate">{d.filename}</span>
          <button
            type="button"
            onClick={() => setExtraDocs(doc.doc_id, extra.filter((i) => i !== d.doc_id))}
            className="focus-ring grid size-4 place-items-center rounded-full hover:bg-background"
            aria-label={`Stop searching ${d.filename}`}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
