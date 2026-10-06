import { motion } from "framer-motion";
import { Blocks, FileText, Layers, ScanText, Sparkles, Table2 } from "lucide-react";
import type { DocumentInfo } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn, STRATEGY_LABELS } from "@/lib/utils";

export function ChunkConfigCard({ doc, compact = false }: { doc: DocumentInfo; compact?: boolean }) {
  const { chunk_config: cfg, profile } = doc;
  const stats = [
    { icon: FileText, label: "Pages", value: doc.page_count },
    { icon: Blocks, label: "Chunks", value: doc.chunk_count },
    { icon: Layers, label: "Size / overlap", value: cfg.chunk_overlap ? `${cfg.chunk_size} / ${cfg.chunk_overlap}` : "1 slide / 0" },
    { icon: Table2, label: "Tables", value: profile.table_count },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("rounded-2xl border border-primary/20 bg-primary/5 p-4", compact && "p-3")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 text-primary" />
        <span className="text-sm font-semibold">Adaptive chunking</span>
        <Badge>{STRATEGY_LABELS[cfg.strategy] ?? cfg.strategy}</Badge>
        {profile.is_scanned && (
          <Badge variant="outline">
            <ScanText /> OCR
          </Badge>
        )}
      </div>
      <p className={cn("mt-2 text-muted-foreground", compact ? "text-xs" : "text-sm")}>{cfg.reason}</p>
      <div className={cn("mt-3 grid gap-2", compact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4")}>
        {stats.map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-xl bg-background/60 px-3 py-2">
            <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
              <Icon className="size-3" /> {label}
            </div>
            <div className="mt-0.5 font-semibold tabular-nums">{value}</div>
          </div>
        ))}
      </div>
    </motion.div>
  );
}
