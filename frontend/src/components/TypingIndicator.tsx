import { AnimatePresence, motion } from "framer-motion";

export function TypingIndicator({ text }: { text?: string }) {
  return (
    <div className="flex items-center gap-3 py-1 text-sm text-muted-foreground" aria-live="polite">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="size-1.5 rounded-full bg-primary"
            animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
          />
        ))}
      </span>
      <AnimatePresence mode="wait">
        {text && (
          <motion.span key={text} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>
            {text}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}
