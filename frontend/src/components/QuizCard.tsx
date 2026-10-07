import { motion } from "framer-motion";
import { GraduationCap, Play } from "lucide-react";
import type { Quiz } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
      className="relative overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-violet-500/10 via-fuchsia-500/5 to-cyan-500/10 p-4"
    >
      <div className="flex items-start gap-3">
        <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-violet-500/30">
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
      <Button className="mt-4 w-full sm:w-auto" onClick={() => openQuiz(quiz)}>
        <Play /> Start quiz
      </Button>
    </motion.div>
  );
}
