import { AnimatePresence, motion } from "framer-motion";
import type * as React from "react";
import { cn } from "@/lib/utils";

/** Slide-in panel used for the sidebar / PDF viewer on smaller screens. */
export function Drawer({
  open,
  onClose,
  side,
  children,
  className,
  label,
}: {
  open: boolean;
  onClose: () => void;
  side: "left" | "right";
  children: React.ReactNode;
  className?: string;
  label: string;
}) {
  const offset = side === "left" ? "-100%" : "100%";
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={label}>
          <motion.div
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className={cn("absolute inset-y-0 flex flex-col", side === "left" ? "left-0" : "right-0", className)}
            initial={{ x: offset }}
            animate={{ x: 0 }}
            exit={{ x: offset }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            {children}
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
