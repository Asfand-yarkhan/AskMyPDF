import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export function Progress({ value, className, shimmer = false }: { value: number; className?: string; shimmer?: boolean }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-secondary", className)}
    >
      <motion.div
        className="relative h-full overflow-hidden rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-cyan-400"
        initial={false}
        animate={{ width: `${pct}%` }}
        transition={{ type: "spring", stiffness: 120, damping: 24 }}
      >
        {shimmer && (
          <span className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/40 to-transparent" />
        )}
      </motion.div>
    </div>
  );
}
