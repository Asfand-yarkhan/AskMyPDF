import { motion } from "framer-motion";
import { GraduationCap, Play, Printer } from "lucide-react";
import { toast } from "sonner";
import type { Quiz } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { printQuiz } from "@/lib/export";
import { useAppStore } from "@/store/useAppStore";

/** Inline summary of a generated quiz; the quiz itself runs in QuizModal. */
export function QuizCard({ quiz }: { quiz: Quiz }) {
  const openQuiz = useAppStore((s) => s.openQuiz);
  const pages = [...new Set(quiz.questions.map((q) => q.page))].sort((a, b) => a - b);
  const types = [...new Set(quiz.questions.map((q) => q.type))];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      className="relative overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-indigo-500/10 to-cyan-500/10 p-4"
    >
      <div className="flex items-start gap-3">
        <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand text-white shadow-lg shadow-indigo-500/30">
          <GraduationCap className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{quiz.title}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Badge>{quiz.questions.length} questions</Badge>
            <Badge variant="outline" className="capitalize">{quiz.difficulty}</Badge>
            {types.map((t) => (
              <Badge key={t} variant="secondary">{t === "mcq" ? "MCQ" : t === "true_false" ? "True/False" : "Short"}</Badge>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Covers pages {pages.length > 6 ? `${pages[0]}–${pages[pages.length - 1]}` : pages.join(", ")}
          </p>
        </div>
      </div>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <Button className="w-full sm:w-auto" onClick={() => openQuiz(quiz)}>
          <Play /> Start quiz
        </Button>
        <Button
          variant="outline"
          className="w-full sm:w-auto"
          onClick={() => !printQuiz(quiz) && toast.error("Allow pop-ups for this site to print.")}
          title="Printable quiz with an answer key on a separate page"
        >
          <Printer /> Print / PDF
        </Button>
      </div>
    </motion.div>
  );
}
