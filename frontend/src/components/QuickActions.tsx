import { AnimatePresence, motion } from "framer-motion";
import { BookOpenCheck, GraduationCap, Layers, ListChecks, NotebookPen, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Difficulty } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ACTIONS = [
  { label: "Summarize", icon: Sparkles, prompt: "Summarize this document" },
  { label: "Generate quiz", icon: GraduationCap, prompt: null },
  { label: "Key points", icon: ListChecks, prompt: "List the key points of this document" },
  { label: "Flashcards", icon: Layers, prompt: "Make 12 flashcards from this document" },
  { label: "Study notes", icon: NotebookPen, prompt: "Create study notes for this document" },
  { label: "Explain", icon: BookOpenCheck, prompt: "Explain the main concept of this document in simple words" },
] as const;

export function QuickActions({ onSend, disabled }: { onSend: (text: string) => void; disabled?: boolean }) {
  const [quizOpen, setQuizOpen] = useState(false);

  return (
    <div className="relative">
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin [mask-image:linear-gradient(to_right,black_92%,transparent)] sm:flex-wrap sm:overflow-visible sm:[mask-image:none]">
        {ACTIONS.map(({ label, icon: Icon, prompt }) => (
          <motion.button
            key={label}
            type="button"
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.96 }}
            disabled={disabled}
            onClick={() => (prompt ? onSend(prompt) : setQuizOpen((o) => !o))}
            aria-expanded={prompt ? undefined : quizOpen}
            className={cn(
              "focus-ring glass inline-flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors hover:border-primary/40 hover:text-primary disabled:pointer-events-none disabled:opacity-50",
              !prompt && quizOpen && "border-primary/50 text-primary",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </motion.button>
        ))}
      </div>
      <AnimatePresence>
        {quizOpen && (
          <QuizOptions
            onClose={() => setQuizOpen(false)}
            onGenerate={(prompt) => {
              setQuizOpen(false);
              onSend(prompt);
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

const COUNTS = [5, 10, 15, 20];
const LEVELS: Difficulty[] = ["easy", "medium", "hard"];
const TYPES = [
  { id: "mcq", label: "MCQ" },
  { id: "true/false", label: "True/False" },
  { id: "short answer", label: "Short" },
  { id: "mixed", label: "Mixed" },
];

function QuizOptions({ onGenerate, onClose }: { onGenerate: (prompt: string) => void; onClose: () => void }) {
  const [count, setCount] = useState(10);
  const [level, setLevel] = useState<Difficulty>("medium");
  const [type, setType] = useState("mcq");
  const [topic, setTopic] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    const id = window.setTimeout(() => document.addEventListener("mousedown", onDown), 0);
    return () => {
      window.clearTimeout(id);
      document.removeEventListener("mousedown", onDown);
    };
  }, [onClose]);

  const build = () => {
    const kind = type === "mixed" ? "mixed-type" : type;
    const about = topic.trim() ? ` on ${topic.trim()}` : "";
    return `Generate a ${count}-question ${level} ${kind} quiz${about}`;
  };

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 8, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.97 }}
      className="glass absolute bottom-full left-0 z-30 mb-2 w-[min(22rem,calc(100vw-2rem))] rounded-2xl bg-card/95 p-4"
      role="dialog"
      aria-label="Quiz options"
      onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), onClose())}
    >
      <Segment label="Questions" options={COUNTS.map((c) => ({ id: String(c), label: String(c) }))} value={String(count)} onChange={(v) => setCount(Number(v))} />
      <Segment label="Difficulty" options={LEVELS.map((l) => ({ id: l, label: l[0].toUpperCase() + l.slice(1) }))} value={level} onChange={(v) => setLevel(v as Difficulty)} />
      <Segment label="Type" options={TYPES} value={type} onChange={setType} />
      <label className="mt-3 block text-xs font-medium text-muted-foreground">
        Topic (optional)
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onGenerate(build())}
          placeholder="e.g. chapter 3, photosynthesis"
          className="focus-ring mt-1 h-9 w-full rounded-xl border border-border bg-background/60 px-3 text-sm text-foreground"
        />
      </label>
      <Button className="mt-4 w-full" onClick={() => onGenerate(build())}>
        <GraduationCap /> Generate quiz
      </Button>
    </motion.div>
  );
}

function Segment({
  label, options, value, onChange,
}: {
  label: string; options: { id: string; label: string }[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="mt-3 first:mt-0">
      <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
      <div className="flex rounded-xl bg-secondary p-1" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={value === o.id}
            onClick={() => onChange(o.id)}
            className={cn(
              "focus-ring relative flex-1 rounded-lg px-2 py-1 text-xs font-medium transition-colors",
              value === o.id ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {value === o.id && (
              <motion.span layoutId={`seg-${label}`} className="absolute inset-0 rounded-lg bg-background shadow-sm" transition={{ type: "spring", stiffness: 400, damping: 32 }} />
            )}
            <span className="relative">{o.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
