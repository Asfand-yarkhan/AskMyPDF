import { motion } from "framer-motion";
import { ArrowLeft, BookOpenCheck, FileText, GraduationCap, Languages, Layers, Quote } from "lucide-react";
import type { DocumentInfo } from "@/api/types";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

const FEATURES = [
  { icon: Quote, label: "Cited answers" },
  { icon: GraduationCap, label: "Interactive quizzes" },
  { icon: Layers, label: "Flashcards" },
  { icon: BookOpenCheck, label: "Summaries & notes" },
  { icon: Languages, label: "English · اردو · Roman Urdu" },
];

export function LandingPage() {
  const documents = useAppStore((s) => s.documents);
  const setActiveDoc = useAppStore((s) => s.setActiveDoc);
  const setView = useAppStore((s) => s.setView);
  const hasDocs = documents.length > 0;

  const open = (doc: DocumentInfo) => setActiveDoc(doc.doc_id);

  return (
    <div className="min-h-full overflow-y-auto">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4 sm:px-6">
        <Logo />
        <div className="flex items-center gap-1">
          {hasDocs && (
            <Button variant="ghost" size="sm" onClick={() => setView("workspace")}>
              <ArrowLeft /> Back to chat
            </Button>
          )}
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-16 pt-6 sm:px-6 sm:pt-12">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="text-center">
          <span className="glass inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-muted-foreground">
            <span className="size-1.5 animate-pulse rounded-full bg-success" /> Grounded strictly in your document
          </span>
          <h1 className="mt-5 text-4xl font-bold tracking-tight sm:text-6xl">
            Chat with your <span className="text-gradient">PDF</span>
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-base text-muted-foreground sm:text-lg">
            Upload a document and ask questions, get summaries, or test yourself with quizzes and flashcards. Every answer cites its page.
          </p>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15, duration: 0.5 }} className="mt-10">
          <UploadDropzone onReady={open} />
        </motion.div>

        <motion.ul initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.06, delayChildren: 0.3 } } }} className="mt-8 flex flex-wrap justify-center gap-2">
          {FEATURES.map(({ icon: Icon, label }) => (
            <motion.li
              key={label}
              variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0 } }}
              className="glass flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-muted-foreground"
            >
              <Icon className="size-3.5 text-primary" /> {label}
            </motion.li>
          ))}
        </motion.ul>

        {hasDocs && (
          <motion.section initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }} className="mt-14">
            <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Recent documents</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {documents.slice(0, 6).map((doc) => (
                <motion.button
                  key={doc.doc_id}
                  type="button"
                  whileHover={{ y: -2 }}
                  onClick={() => open(doc)}
                  className="focus-ring glass flex items-center gap-3 rounded-2xl p-3 text-left transition-colors hover:border-primary/40"
                >
                  <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                    <FileText className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{doc.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {doc.page_count} pages · {formatBytes(doc.size_bytes)} · {doc.chunk_config.strategy}
                    </p>
                  </div>
                </motion.button>
              ))}
            </div>
          </motion.section>
        )}
      </main>
    </div>
  );
}
