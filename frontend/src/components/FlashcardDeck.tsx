import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ChevronLeft, ChevronRight, Download, Layers, RotateCw, Shuffle } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import type { FlashcardDeck as Deck } from "@/api/types";
import { CitationChip } from "@/components/CitationChip";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Progress } from "@/components/ui/progress";
import { exportAnki, exportCsv, printFlashcards } from "@/lib/export";
import { type Grade, dueIndexes, formatDue, MAX_BOX } from "@/lib/srs";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

type Mode = "all" | "due";

const GRADES: { grade: Grade; label: string; hint: string; className: string }[] = [
  { grade: "again", label: "Again", hint: "1", className: "border-destructive/40 text-destructive hover:bg-destructive/10" },
  { grade: "good", label: "Good", hint: "2", className: "border-primary/40 text-primary hover:bg-primary/10" },
  { grade: "easy", label: "Easy", hint: "3", className: "border-success/40 text-success hover:bg-success/10" },
];

export function FlashcardDeck({ deck, deckId }: { deck: Deck; deckId: string }) {
  const srs = useAppStore((s) => s.srs);
  const rateCard = useAppStore((s) => s.rateCard);
  const keyOf = useCallback((i: number) => `${deckId}:${i}`, [deckId]);
  const states = useMemo(() => deck.cards.map((_, i) => srs[keyOf(i)]), [deck.cards, srs, keyOf]);
  const dueCount = useMemo(() => dueIndexes(states).length, [states]);

  const [mode, setMode] = useState<Mode>("all");
  const [order, setOrder] = useState(() => deck.cards.map((_, i) => i));
  const [pos, setPos] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [direction, setDirection] = useState(1);
  const [menuOpen, setMenuOpen] = useState(false);

  const cardIndex = order[pos];
  const card = cardIndex === undefined ? undefined : deck.cards[cardIndex];
  const state = cardIndex === undefined ? undefined : states[cardIndex];

  const go = useCallback(
    (delta: number) => {
      if (!order.length) return;
      setFlipped(false);
      setDirection(delta);
      setPos((p) => (p + delta + order.length) % order.length);
    },
    [order.length],
  );

  const switchMode = (next: Mode) => {
    setMode(next);
    setOrder(next === "due" ? dueIndexes(states) : deck.cards.map((_, i) => i));
    setPos(0);
    setFlipped(false);
  };

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

  const grade = (g: Grade) => {
    if (cardIndex === undefined) return;
    rateCard(keyOf(cardIndex), g);
    setFlipped(false);
    setDirection(1);
    if (mode === "due") {
      // Review session: a graded card leaves the queue ("Again" cards come back at the end).
      const rest = order.filter((_, i) => i !== pos);
      const next = g === "again" ? [...rest, cardIndex] : rest;
      setOrder(next);
      setPos((p) => (next.length ? p % next.length : 0));
    } else {
      setPos((p) => (p + 1) % order.length);
    }
  };

  const doExport = (kind: "anki" | "csv" | "print") => {
    setMenuOpen(false);
    if (kind === "anki") exportAnki(deck);
    else if (kind === "csv") exportCsv(deck);
    else if (!printFlashcards(deck)) toast.error("Allow pop-ups for this site to print.");
  };

  return (
    <div
      className="focus-ring rounded-2xl outline-none"
      tabIndex={0}
      aria-label="Flashcards: Space to flip, arrow keys to navigate, 1-3 to grade"
      onKeyDown={(e) => {
        if (e.key === " ") {
          e.preventDefault();
          setFlipped((f) => !f);
        } else if (e.key === "ArrowRight") go(1);
        else if (e.key === "ArrowLeft") go(-1);
        else if (flipped && ["1", "2", "3"].includes(e.key)) grade(GRADES[Number(e.key) - 1].grade);
      }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Layers className="size-4 text-primary" />
        <span className="text-sm font-semibold">{deck.title}</span>
        <div className="ml-auto flex items-center gap-1 rounded-lg bg-secondary p-0.5 text-xs" role="tablist">
          {(["all", "due"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => switchMode(m)}
              className={cn(
                "focus-ring rounded-md px-2 py-0.5 font-medium transition-colors",
                mode === m ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m === "all" ? `All ${deck.cards.length}` : `Due ${dueCount}`}
            </button>
          ))}
        </div>
        <div className="relative">
          <Button variant="ghost" size="icon-sm" onClick={() => setMenuOpen((o) => !o)} aria-label="Export flashcards" aria-expanded={menuOpen}>
            <Download />
          </Button>
          <AnimatePresence>
            {menuOpen && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="glass absolute right-0 top-full z-20 mt-1 w-48 rounded-xl bg-popover/95 p-1 text-sm"
                role="menu"
              >
                {[
                  ["anki", "Anki deck (.txt)"],
                  ["csv", "Spreadsheet (.csv)"],
                  ["print", "Print / save as PDF"],
                ].map(([kind, label]) => (
                  <button
                    key={kind}
                    type="button"
                    role="menuitem"
                    onClick={() => doExport(kind as "anki" | "csv" | "print")}
                    className="focus-ring w-full rounded-lg px-3 py-1.5 text-left hover:bg-secondary"
                  >
                    {label}
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {!card ? (
        <div className="flex h-56 flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-success/40 bg-success/5 text-center sm:h-60">
          <CheckCircle2 className="size-8 text-success" />
          <p className="font-semibold">All caught up!</p>
          <p className="text-xs text-muted-foreground">No cards are due. Come back later or review all cards.</p>
          <Button size="sm" variant="outline" className="mt-1" onClick={() => switchMode("all")}>
            Review all cards
          </Button>
        </div>
      ) : (
        <>
          <Progress value={(pos + 1) / order.length} className="mb-3 h-1.5" />
          <div className="relative h-56 [perspective:1200px] sm:h-60">
            <AnimatePresence mode="popLayout" custom={direction} initial={false}>
              <motion.div
                key={`${cardIndex}-${pos}`}
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
                  <div className="backface-hidden absolute inset-0 flex flex-col items-center justify-center rounded-2xl border border-primary/20 bg-gradient-to-br from-indigo-500/15 via-card to-cyan-500/10 p-6 text-center shadow-lg">
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

          <AnimatePresence initial={false} mode="wait">
            {flipped ? (
              <motion.div
                key="grade"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="mt-3 grid grid-cols-3 gap-2"
              >
                {GRADES.map((g) => (
                  <button
                    key={g.grade}
                    type="button"
                    onClick={() => grade(g.grade)}
                    className={cn("focus-ring rounded-xl border bg-background/50 py-2 text-sm font-semibold transition-colors", g.className)}
                  >
                    {g.label} <Kbd className="ml-1 hidden sm:inline-flex">{g.hint}</Kbd>
                  </button>
                ))}
              </motion.div>
            ) : (
              <motion.div key="nav" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-3 flex items-center gap-2">
                <Button variant="outline" size="icon-sm" onClick={() => go(-1)} aria-label="Previous card">
                  <ChevronLeft />
                </Button>
                <span className="w-12 text-center text-xs tabular-nums text-muted-foreground">
                  {pos + 1} / {order.length}
                </span>
                <Button variant="outline" size="icon-sm" onClick={() => go(1)} aria-label="Next card">
                  <ChevronRight />
                </Button>
                <Button variant="ghost" size="sm" onClick={shuffle}>
                  <Shuffle /> Shuffle
                </Button>
                <div className="ml-auto flex items-center gap-2">
                  <span className="hidden items-center gap-0.5 sm:flex" title={`Box ${state?.box ?? 1} of ${MAX_BOX} · ${formatDue(state)}`}>
                    {Array.from({ length: MAX_BOX }, (_, i) => (
                      <span key={i} className={cn("size-1.5 rounded-full", i < (state?.box ?? 0) ? "bg-primary" : "bg-muted-foreground/25")} />
                    ))}
                  </span>
                  <CitationChip page={card.page} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
