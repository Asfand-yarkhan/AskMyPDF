import confetti from "canvas-confetti";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check, Loader2, RotateCcw, Sparkles, Trophy, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { QuizQuestion } from "@/api/types";
import { CitationChip } from "@/components/CitationChip";
import { Modal } from "@/components/Modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

interface Answer {
  value: string;
  correct: boolean;
  score: number;
  feedback?: string;
}

const TYPE_LABEL: Record<QuizQuestion["type"], string> = {
  mcq: "Multiple choice",
  true_false: "True / False",
  short: "Short answer",
};

const norm = (s: string) => s.toLowerCase().replace(/\W+/g, " ").trim();

export function QuizModal() {
  const active = useAppStore((s) => s.activeQuiz);
  const close = useAppStore((s) => s.closeQuiz);
  const openQuiz = useAppStore((s) => s.openQuiz);
  const docId = useAppStore((s) => s.activeDocId);

  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<string>("");
  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [grading, setGrading] = useState(false);

  // Reset whenever a new quiz (or a retry subset) opens.
  useEffect(() => {
    setStep(0);
    setSelected("");
    setAnswers({});
  }, [active]);

  const order = active?.order ?? [];
  const finished = active !== null && step >= order.length;
  const qIndex = order[step];
  const question = active && !finished ? active.quiz.questions[qIndex] : null;
  const answer = qIndex !== undefined ? answers[qIndex] : undefined;

  const score = useMemo(() => Object.values(answers).reduce((sum, a) => sum + a.score, 0), [answers]);
  const wrong = useMemo(() => order.filter((i) => answers[i] && !answers[i].correct), [order, answers]);

  const submit = useCallback(async () => {
    if (!question || answer || !selected.trim()) return;
    if (question.type !== "short") {
      const correct = norm(selected) === norm(question.correct_answer);
      setAnswers((a) => ({ ...a, [qIndex]: { value: selected, correct, score: correct ? 1 : 0 } }));
      return;
    }
    setGrading(true);
    try {
      const res = await api.grade(
        [{ ...question, user_answer: selected, explanation: question.explanation, page: question.page }],
        docId ?? undefined,
      );
      const r = res.results[0];
      setAnswers((a) => ({ ...a, [qIndex]: { value: selected, correct: r.correct, score: r.score, feedback: r.feedback } }));
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setGrading(false);
    }
  }, [question, answer, selected, qIndex, docId]);

  const next = useCallback(() => {
    setSelected("");
    setStep((s) => s + 1);
  }, []);

  // Celebrate on the results screen.
  useEffect(() => {
    if (!finished || !order.length) return;
    const pct = score / order.length;
    const burst = (particleRatio: number, opts: confetti.Options) =>
      confetti({ origin: { y: 0.7 }, zIndex: 9999, particleCount: Math.floor(220 * particleRatio), ...opts });
    burst(0.3, { spread: 30, startVelocity: 55 });
    burst(0.25, { spread: 70 });
    if (pct >= 0.7) {
      burst(0.4, { spread: 110, decay: 0.92, scalar: 0.9 });
      burst(0.15, { spread: 130, startVelocity: 30, scalar: 1.2 });
    }
  }, [finished, order.length, score]);

  // Keyboard: 1-4 to pick, Enter to check / continue.
  useEffect(() => {
    if (!question) return;
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLTextAreaElement;
      if (!answer && !typing && question.options.length && /^[1-9]$/.test(e.key)) {
        const opt = question.options[Number(e.key) - 1];
        if (opt) setSelected(opt);
      } else if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (answer) next();
        else void submit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [question, answer, submit, next]);

  if (!active) return <Modal open={false} onClose={close}>{null}</Modal>;

  return (
    <Modal open onClose={close} title={active.quiz.title} className="sm:max-w-2xl">
      {!finished && question ? (
        <div>
          <div className="mb-4 flex items-center gap-3">
            <Progress value={(step + (answer ? 1 : 0)) / order.length} className="flex-1" />
            <span className="text-xs font-medium tabular-nums text-muted-foreground">
              {step + 1} / {order.length}
            </span>
          </div>
          <div className="mb-3 flex flex-wrap gap-2">
            <Badge variant="secondary">{TYPE_LABEL[question.type]}</Badge>
            <Badge variant="outline" className="capitalize">{active.quiz.difficulty}</Badge>
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={`${qIndex}-${step}`}
              initial={{ opacity: 0, x: 24 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -24 }}
              transition={{ duration: 0.22 }}
            >
              <h3 className="text-lg font-semibold leading-snug">{question.question}</h3>

              {question.type === "short" ? (
                <textarea
                  value={answer?.value ?? selected}
                  onChange={(e) => setSelected(e.target.value)}
                  disabled={!!answer}
                  rows={3}
                  placeholder="Type your answer… (Enter to check)"
                  className="focus-ring mt-4 w-full resize-none rounded-2xl border border-border bg-background/60 p-3 text-sm"
                  autoFocus
                />
              ) : (
                <div className="mt-4 grid gap-2.5" role="radiogroup">
                  {question.options.map((opt, i) => {
                    const isSelected = (answer?.value ?? selected) === opt;
                    const isCorrect = norm(opt) === norm(question.correct_answer);
                    const state = answer ? (isCorrect ? "correct" : isSelected ? "wrong" : "idle") : isSelected ? "selected" : "idle";
                    return (
                      <motion.button
                        key={opt}
                        type="button"
                        role="radio"
                        aria-checked={isSelected}
                        disabled={!!answer}
                        onClick={() => setSelected(opt)}
                        animate={state === "wrong" ? { x: [0, -6, 6, -4, 4, 0] } : state === "correct" && answer ? { scale: [1, 1.02, 1] } : {}}
                        transition={{ duration: 0.35 }}
                        className={cn(
                          "focus-ring flex items-center gap-3 rounded-2xl border px-4 py-3 text-left text-sm transition-colors",
                          state === "idle" && "border-border bg-background/50 hover:border-primary/50 hover:bg-primary/5",
                          state === "selected" && "border-primary bg-primary/10 ring-1 ring-primary",
                          state === "correct" && "border-success bg-success/10 text-foreground",
                          state === "wrong" && "border-destructive bg-destructive/10",
                          answer && state === "idle" && "opacity-60",
                        )}
                      >
                        <span
                          className={cn(
                            "grid size-7 shrink-0 place-items-center rounded-lg text-xs font-bold",
                            state === "correct" ? "bg-success text-success-foreground"
                              : state === "wrong" ? "bg-destructive text-destructive-foreground"
                              : state === "selected" ? "bg-primary text-primary-foreground" : "bg-secondary",
                          )}
                        >
                          {state === "correct" ? <Check className="size-4" /> : state === "wrong" ? <X className="size-4" /> : i + 1}
                        </span>
                        <span className="flex-1">{opt}</span>
                      </motion.button>
                    );
                  })}
                </div>
              )}

              <AnimatePresence>
                {answer && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={cn(
                      "mt-4 rounded-2xl border p-4 text-sm",
                      answer.correct ? "border-success/30 bg-success/10" : "border-destructive/30 bg-destructive/10",
                    )}
                    aria-live="polite"
                  >
                    <p className="flex items-center gap-2 font-semibold">
                      {answer.correct ? <Check className="size-4 text-success" /> : <X className="size-4 text-destructive" />}
                      {answer.correct ? "Correct!" : question.type === "short" ? "Not quite" : "Incorrect"}
                      {question.type === "short" && <span className="font-normal text-muted-foreground">({Math.round(answer.score * 100)}%)</span>}
                    </p>
                    {answer.feedback && <p className="mt-1.5">{answer.feedback}</p>}
                    {!answer.correct && (
                      <p className="mt-1.5">
                        <span className="text-muted-foreground">Answer: </span>
                        <span className="font-medium">{question.correct_answer}</span>
                      </p>
                    )}
                    {question.explanation && <p className="mt-1.5 text-muted-foreground">{question.explanation}</p>}
                    <div className="mt-2">
                      <CitationChip page={question.page} label={`Source p. ${question.page}`} />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </AnimatePresence>

          <div className="mt-5 flex items-center justify-between gap-3">
            <span className="hidden text-xs text-muted-foreground sm:flex sm:items-center sm:gap-1">
              {question.type !== "short" && <><Kbd>1</Kbd>-<Kbd>{question.options.length}</Kbd> select ·</>} <Kbd>Enter</Kbd> {answer ? "next" : "check"}
            </span>
            {answer ? (
              <Button onClick={next} className="ml-auto" autoFocus>
                {step + 1 === order.length ? "See results" : "Next question"} <ArrowRight />
              </Button>
            ) : (
              <Button onClick={() => void submit()} disabled={!selected.trim() || grading} className="ml-auto">
                {grading && <Loader2 className="animate-spin" />} Check answer
              </Button>
            )}
          </div>
        </div>
      ) : (
        <Results
          score={score}
          total={order.length}
          wrongCount={wrong.length}
          onRetryWrong={() => openQuiz(active.quiz, wrong)}
          onRestart={() => openQuiz(active.quiz)}
          onClose={close}
        />
      )}
    </Modal>
  );
}

function Results({
  score, total, wrongCount, onRetryWrong, onRestart, onClose,
}: {
  score: number; total: number; wrongCount: number;
  onRetryWrong: () => void; onRestart: () => void; onClose: () => void;
}) {
  const pct = total ? Math.round((score / total) * 100) : 0;
  const message = pct >= 90 ? "Outstanding!" : pct >= 70 ? "Great job!" : pct >= 50 ? "Good effort!" : "Keep practicing!";
  const radius = 54;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="flex flex-col items-center py-2 text-center">
      <div className="relative size-36">
        <svg viewBox="0 0 128 128" className="size-full -rotate-90">
          <circle cx="64" cy="64" r={radius} className="fill-none stroke-secondary" strokeWidth="10" />
          <motion.circle
            cx="64" cy="64" r={radius} fill="none" strokeWidth="10" strokeLinecap="round"
            stroke="url(#score-gradient)"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: circumference * (1 - pct / 100) }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          />
          <defs>
            <linearGradient id="score-gradient" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" />
              <stop offset="100%" stopColor="#06b6d4" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <div>
            <motion.div initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.3 }} className="text-3xl font-bold tabular-nums">
              {pct}%
            </motion.div>
            <div className="text-xs text-muted-foreground">{Number.isInteger(score) ? score : score.toFixed(1)} / {total}</div>
          </div>
        </div>
      </div>
      <h3 className="mt-4 flex items-center gap-2 text-xl font-semibold">
        {pct >= 70 ? <Trophy className="size-5 text-amber-500" /> : <Sparkles className="size-5 text-primary" />}
        {message}
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {wrongCount ? `${wrongCount} question${wrongCount > 1 ? "s" : ""} to review.` : "You got everything right."}
      </p>
      <div className="mt-6 flex w-full flex-col gap-2 sm:flex-row sm:justify-center">
        {wrongCount > 0 && (
          <Button onClick={onRetryWrong}>
            <RotateCcw /> Retry wrong ones ({wrongCount})
          </Button>
        )}
        <Button variant="outline" onClick={onRestart}>Restart quiz</Button>
        <Button variant="ghost" onClick={onClose}>Done</Button>
      </div>
    </div>
  );
}
