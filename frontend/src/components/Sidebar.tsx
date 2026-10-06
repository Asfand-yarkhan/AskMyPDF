import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, CircleAlert, FileText, Keyboard, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { DocumentInfo } from "@/api/types";
import { ChunkConfigCard } from "@/components/ChunkConfigCard";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { useDeleteDocument, useHealth } from "@/hooks/useDocuments";
import { cn, formatBytes, modKey } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const documents = useAppStore((s) => s.documents);
  const loaded = useAppStore((s) => s.documentsLoaded);
  const activeId = useAppStore((s) => s.activeDocId);
  const setActiveDoc = useAppStore((s) => s.setActiveDoc);
  const setView = useAppStore((s) => s.setView);
  const setShortcutsOpen = useAppStore((s) => s.setShortcutsOpen);
  const active = documents.find((d) => d.doc_id === activeId);
  const [showConfig, setShowConfig] = useState(true);

  return (
    <div className="flex h-full w-[min(20rem,85vw)] flex-col border-r border-border/60 bg-card/70 backdrop-blur-xl lg:w-72 lg:bg-card/40">
      <div className="flex items-center justify-between px-4 py-3.5">
        <Logo />
        {onClose && (
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close sidebar">
            <X />
          </Button>
        )}
      </div>

      <div className="px-3">
        <Button className="w-full" onClick={() => setView("landing")}>
          <Plus /> New document
        </Button>
      </div>

      <div className="mt-5 flex-1 overflow-y-auto px-3 scrollbar-thin">
        <p className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Documents</p>
        {!loaded ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : documents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            No documents yet. Upload a PDF to get started.
          </div>
        ) : (
          <ul className="space-y-1.5">
            <AnimatePresence initial={false}>
              {documents.map((doc) => (
                <DocumentItem key={doc.doc_id} doc={doc} active={doc.doc_id === activeId} onSelect={() => setActiveDoc(doc.doc_id)} />
              ))}
            </AnimatePresence>
          </ul>
        )}

        {active && (
          <div className="mt-5">
            <button
              type="button"
              onClick={() => setShowConfig((s) => !s)}
              className="focus-ring flex w-full items-center justify-between rounded-lg px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
              aria-expanded={showConfig}
            >
              Index settings
              <ChevronDown className={cn("size-3.5 transition-transform", showConfig && "rotate-180")} />
            </button>
            <AnimatePresence initial={false}>
              {showConfig && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <ChunkConfigCard doc={active} compact />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>

      <SidebarFooter onShortcuts={() => setShortcutsOpen(true)} />
    </div>
  );
}

function DocumentItem({ doc, active, onSelect }: { doc: DocumentInfo; active: boolean; onSelect: () => void }) {
  const remove = useDeleteDocument();
  const [confirming, setConfirming] = useState(false);

  return (
    <motion.li layout initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10, height: 0 }}>
      <div
        className={cn(
          "group relative flex items-center gap-2.5 rounded-xl px-2.5 py-2 transition-colors",
          active ? "bg-primary/10 ring-1 ring-inset ring-primary/25" : "hover:bg-secondary",
        )}
      >
        {active && <motion.span layoutId="doc-active" className="absolute inset-y-2 left-0 w-1 rounded-full bg-primary" />}
        <button type="button" onClick={onSelect} className="focus-ring flex min-w-0 flex-1 items-center gap-2.5 rounded-lg text-left" aria-current={active}>
          <div className={cn("grid size-9 shrink-0 place-items-center rounded-lg", active ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground")}>
            <FileText className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{doc.filename}</p>
            <p className="text-[11px] text-muted-foreground">
              {doc.page_count} pages · {formatBytes(doc.size_bytes)}
            </p>
          </div>
        </button>
        {confirming ? (
          <div className="flex items-center gap-1">
            <Button size="sm" variant="destructive" className="h-7 px-2" onClick={() => void remove(doc.doc_id, doc.filename)}>
              Delete
            </Button>
            <Button size="icon-sm" variant="ghost" className="size-7" onClick={() => setConfirming(false)} aria-label="Cancel delete">
              <X />
            </Button>
          </div>
        ) : (
          <Tooltip content="Delete document">
            <Button
              size="icon-sm"
              variant="ghost"
              className="size-7 opacity-100 hover:text-destructive sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100"
              onClick={() => setConfirming(true)}
              aria-label={`Delete ${doc.filename}`}
            >
              <Trash2 />
            </Button>
          </Tooltip>
        )}
      </div>
    </motion.li>
  );
}

function SidebarFooter({ onShortcuts }: { onShortcuts: () => void }) {
  const { health, offline } = useHealth();
  return (
    <div className="space-y-2 border-t border-border/60 p-3">
      <div className="flex items-center gap-2 rounded-xl px-2 py-1.5 text-xs">
        <span className={cn("size-2 rounded-full", offline ? "bg-destructive" : health?.llm_configured ? "bg-success" : "bg-amber-500")} />
        <span className="truncate text-muted-foreground">
          {offline ? "Backend offline" : health ? `${health.llm_provider} · ${health.llm_model}` : "Connecting…"}
        </span>
        {health && !health.llm_configured && (
          <Tooltip content="No API key configured in backend/.env">
            <CircleAlert className="ml-auto size-3.5 text-amber-500" />
          </Tooltip>
        )}
      </div>
      <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground" onClick={onShortcuts}>
        <Keyboard /> Keyboard shortcuts <span className="ml-auto text-[10px]">?</span>
      </Button>
      <p className="px-2 text-[10px] text-muted-foreground">{modKey}+B toggles this sidebar</p>
    </div>
  );
}
