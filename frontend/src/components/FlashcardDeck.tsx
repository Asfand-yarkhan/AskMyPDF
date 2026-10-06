import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Layers, RotateCw, Shuffle } from "lucide-react";
import { useCallback, useState } from "react";
import type { FlashcardDeck as Deck } from "@/api/types";
import { CitationChip } from "@/components/CitationChip";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

export function FlashcardDeck({ deck }: { deck: Deck }) {
  const [order, setOrder] = useState(() => deck.cards.map((_, i) => i));
  const [pos, setPos] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [direction, setDirection] = useState(1);
  const card = deck.cards[order[pos]];

  const go = useCallback(
    (delta: number) => {
      setFlipped(false);
      setDirection(delta);
      setPos((p) => (p + delta + order.length) % order.length);
    },
    [order.length],
  );

  const shuffle = () => {
    const next = [...order];
    for (let i = next.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [next[i], next[j]] = [next[j], next[i]];
    }
    setOrder(next);
    setPos(0);
    setFlipped(false);
  };

  if (!card) return null;

  return (
    <div
      className="focus-ring rounded-2xl outline-none"
      tabIndex={0}
      aria-label="Flashcards: Space to flip, arrow keys to navigate"
      onKeyDown={(e) => {
        if (e.key === " ") {
          e.preventDefault();
          setFlipped((f) => !f);
        } else if (e.key === "ArrowRight") go(1);
        else if (e.key === "ArrowLeft") go(-1);
      }}
    >
      <div className="mb-3 flex items-center gap-2">
        <Layers className="size-4 text-primary" />
        <span className="text-sm font-semibold">{deck.title}</span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {pos + 1} / {order.length}
        </span>
      </div>
      <Progress value={(pos + 1) / order.length} className="mb-3 h-1.5" />

      <div className="relative h-56 [perspective:1200px] sm:h-60">
        <AnimatePresence mode="popLayout" custom={direction} initial={false}>
          <motion.div
            key={order[pos]}
            custom={direction}
            initial={{ x: direction * 60, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: direction * -60, opacity: 0 }}
            transition={{ duration: 0.22 }}
            className="absolute inset-0"
          >
            <motion.button
              type="button"
              onClick={() => setFlipped((f) => !f)}
              aria-label={flipped ? "Show question" : "Show answer"}
              className="relative size-full cursor-pointer [transform-style:preserve-3d]"
              animate={{ rotateY: flipped ? 180 : 0 }}
              transition={{ type: "spring", stiffness: 260, damping: 26 }}
            >
              <div className="backface-hidden absolute inset-0 flex flex-col items-center justify-center rounded-2xl border border-primary/20 bg-gradient-to-br from-violet-500/15 via-card to-cyan-500/10 p-6 text-center shadow-lg">
                <span className="text-[11px] font-semibold uppercase tracking-widest text-primary">Question</span>
                <p className="mt-3 text-lg font-semibold leading-snug">{card.front}</p>
                <span className="absolute bottom-3 flex items-center gap-1 text-xs text-muted-foreground">
                  <RotateCw className="size-3" /> Tap or Space to flip
                </span>
              </div>
              <div className="backface-hidden absolute inset-0 flex flex-col items-center justify-center overflow-y-auto rounded-2xl border border-success/25 bg-gradient-to-br from-emerald-500/10 via-card to-cyan-500/10 p-6 text-center shadow-lg [transform:rotateY(180deg)]">
                <span className="text-[11px] font-semibold uppercase tracking-widest text-success">Answer</span>
                <p className="mt-3 text-sm leading-relaxed sm:text-base">{card.back}</p>
              </div>
            </motion.button>
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Button variant="outline" size="icon-sm" onClick={() => go(-1)} aria-label="Previous card">
          <ChevronLeft />
        </Button>
        <Button variant="outline" size="icon-sm" onClick={() => go(1)} aria-label="Next card">
          <ChevronRight />
        </Button>
        <Button variant="ghost" size="sm" onClick={shuffle}>
          <Shuffle /> Shuffle
        </Button>
        <div className="ml-auto">
          <CitationChip page={card.page} />
        </div>
      </div>
    </div>
  );
}
