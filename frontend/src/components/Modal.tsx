import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import type * as React from "react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
  closeOnEsc?: boolean;
}

/** Accessible animated dialog: focus moves in on open and back out on close. */
export function Modal({ open, onClose, title, children, className, closeOnEsc = true }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => panelRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && closeOnEsc) {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, [open, onClose, closeOnEsc]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} aria-hidden />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            className={cn(
              "glass relative max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl bg-card/90 p-5 outline-none scrollbar-thin sm:max-w-lg sm:rounded-3xl sm:p-6",
              className,
            )}
            initial={{ y: 40, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 30, opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              {title && <h2 className="text-lg font-semibold tracking-tight">{title}</h2>}
              <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close" className="-mr-1 ml-auto">
                <X />
              </Button>
            </div>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
