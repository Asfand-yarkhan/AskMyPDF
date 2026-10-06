import { BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

export function CitationChip({ page, label, className }: { page: number; label?: string; className?: string }) {
  const jumpToPage = useAppStore((s) => s.jumpToPage);
  return (
    <button
      type="button"
      onClick={() => jumpToPage(page)}
      title={`Open page ${page} in the viewer`}
      className={cn(
        "focus-ring mx-0.5 inline-flex translate-y-[-1px] items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 align-middle text-[11px] font-semibold text-primary ring-1 ring-inset ring-primary/25 transition hover:bg-primary hover:text-primary-foreground",
        className,
      )}
    >
      <BookOpen className="size-3" />
      {label ?? `p. ${page}`}
    </button>
  );
}
