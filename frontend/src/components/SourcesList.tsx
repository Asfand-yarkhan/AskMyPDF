import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Library, Table2 } from "lucide-react";
import { useState } from "react";
import type { SourceChunk } from "@/api/types";
import { CitationChip } from "@/components/CitationChip";
import { cn } from "@/lib/utils";

export function SourcesList({ sources }: { sources: SourceChunk[] }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!sources.length) return null;

  return (
    <div className="mt-3 border-t border-border/60 pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="focus-ring flex items-center gap-1.5 rounded-lg px-1 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <Library className="size-3.5" />
        Sources ({sources.length})
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mt-1 space-y-2 overflow-hidden"
          >
            {sources.map((s) => {
              const isOpen = expanded === s.chunk_id;
              return (
                <li key={s.chunk_id} className="rounded-xl bg-muted/50 p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <CitationChip page={s.page} label={s.page_end > s.page ? `p. ${s.page}-${s.page_end}` : undefined} />
                    {(s.kind === "table" || s.has_table) && <Table2 className="size-3.5 text-muted-foreground" aria-label="table" />}
                    {s.section && <span className="truncate font-medium text-foreground/80">{s.section}</span>}
                    <span className="ml-auto text-muted-foreground">#{s.chunk_index + 1}</span>
                  </div>
                  <p className={cn("mt-2 whitespace-pre-wrap leading-relaxed text-muted-foreground", !isOpen && "line-clamp-3")}>
                    {s.text}
                  </p>
                  {s.text.length > 220 && (
                    <button
                      type="button"
                      className="mt-1 font-medium text-primary hover:underline"
                      onClick={() => setExpanded(isOpen ? null : s.chunk_id)}
                    >
                      {isOpen ? "Show less" : "Show full chunk"}
                    </button>
                  )}
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
