import { FileSearch } from "lucide-react";
import { cn } from "@/lib/utils";

export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-violet-500 via-fuchsia-500 to-cyan-400 text-white shadow-lg shadow-violet-500/30">
        <FileSearch className="size-5" />
      </div>
      {!compact && (
        <span className="text-lg font-semibold tracking-tight">
          AskMy<span className="text-gradient">PDF</span>
        </span>
      )}
    </div>
  );
}
