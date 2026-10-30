import { FileSearch } from "lucide-react";
import { cn } from "@/lib/utils";

export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground">
        <FileSearch className="size-5" />
      </div>
      {!compact && (
        <span className="text-lg font-semibold tracking-tight">
          AskMy<span className="text-primary">PDF</span>
        </span>
      )}
    </div>
  );
}
