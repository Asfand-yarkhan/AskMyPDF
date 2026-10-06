import type * as React from "react";
import { cn } from "@/lib/utils";

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-border bg-secondary px-1.5 font-sans text-[10px] font-semibold text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
