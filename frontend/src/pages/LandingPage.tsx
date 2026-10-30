import { ArrowLeft, ArrowUpRight, BookOpenCheck, FileText, GraduationCap, Languages, Layers, Quote } from "lucide-react";
import type { DocumentInfo } from "@/api/types";
import { AccountMenu } from "@/components/AccountMenu";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Button } from "@/components/ui/button";
import { authEnabled } from "@/lib/auth";
import { formatBytes } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";
import { useAuthStore } from "@/store/useAuthStore";

const FEATURES = [
  { icon: Quote, title: "Answers with page citations", text: "Every answer links to the page it came from. Hover a citation to read the passage." },
  { icon: GraduationCap, title: "Quizzes that grade themselves", text: "MCQ, true or false and short answers, with explanations and a retry for the ones you missed." },
  { icon: Layers, title: "Flashcards with spaced repetition", text: "Review the cards you find hard more often. Export to Anki or print." },
  { icon: BookOpenCheck, title: "Summaries and study notes", text: "Short, detailed or bullet summaries of the whole document or one chapter." },
  { icon: Languages, title: "English, اردو and Roman Urdu", text: "Ask in the language you think in. Replies match it." },
];

export function LandingPage() {
  const documents = useAppStore((s) => s.documents);
  const setActiveDoc = useAppStore((s) => s.setActiveDoc);
  const setView = useAppStore((s) => s.setView);
  const isGuest = useAuthStore((s) => Boolean(s.user?.isGuest));
  const pending = useAuthStore((s) => Boolean(s.user?.pendingVerification));
  const openDialog = useAuthStore((s) => s.openDialog);
  const trials = useAuthStore((s) => s.trials);
  const hasDocs = documents.length > 0;

  const open = (doc: DocumentInfo) => setActiveDoc(doc.doc_id);

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <header className="sticky top-0 z-30 border-b border-border/60 bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-2 px-4 sm:px-6">
          <Logo />
          <nav className="flex items-center gap-1" aria-label="Account">
            {hasDocs && (
              <Button variant="ghost" size="sm" onClick={() => setView("workspace")}>
                <ArrowLeft /> <span className="hidden sm:inline">Back to chat</span>
              </Button>
            )}
            <ThemeToggle />
            <AccountMenu />
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 sm:px-6">
        <section className="grid items-center gap-10 pb-16 pt-10 sm:pt-16 lg:grid-cols-[1fr_minmax(0,30rem)] lg:gap-16 lg:pb-24 lg:pt-24">
          <div className="animate-rise">
            <h1 className="max-w-xl text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl lg:text-[3.5rem]">
              Ask your PDF. Get answers you can check.
            </h1>
            <p className="mt-5 max-w-lg text-base leading-relaxed text-muted-foreground sm:text-lg">
              Upload lecture notes, a textbook chapter or a report. AskMyPDF answers only from the document and shows the page behind every claim.
            </p>
            {authEnabled && pending && (
              <button
                type="button"
                onClick={() => openDialog("manual", "verify")}
                className="focus-ring mt-6 inline-flex items-center gap-2 rounded-lg bg-warning/10 px-3 py-1.5 text-sm transition-colors hover:bg-warning/15"
              >
                <span className="size-1.5 rounded-full bg-warning" aria-hidden />
                Verify your email to unlock unlimited questions
              </button>
            )}
            {authEnabled && isGuest && (
              <p className="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary/[0.07] px-3 py-1.5 text-sm text-primary">
                <span className="size-1.5 rounded-full bg-primary" aria-hidden />
                {trials ? `${trials.remaining} of ${trials.limit} free questions left` : "Try it free"}, no account needed
              </p>
            )}
          </div>

          <div className="animate-rise [animation-delay:80ms]">
            <UploadDropzone onReady={open} />
          </div>
        </section>

        {hasDocs && (
          <section className="pb-16" aria-labelledby="recent-heading">
            <div className="mb-4 flex items-baseline justify-between">
              <h2 id="recent-heading" className="text-sm font-semibold">
                Your documents
              </h2>
              <span className="text-xs tabular-nums text-muted-foreground">{documents.length} total</span>
            </div>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {documents.slice(0, 6).map((doc) => (
                <li key={doc.doc_id}>
                  <button
                    type="button"
                    onClick={() => open(doc)}
                    className="focus-ring surface group flex w-full items-center gap-3 rounded-xl p-3 text-left transition-[border-color,transform] duration-200 ease-out-expo hover:-translate-y-0.5 hover:border-primary/40"
                  >
                    <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary">
                      <FileText className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{doc.filename}</p>
                      <p className="text-xs tabular-nums text-muted-foreground">
                        {doc.page_count} pages · {formatBytes(doc.size_bytes)}
                      </p>
                    </div>
                    <ArrowUpRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="border-t border-border/70 py-16 lg:py-20" aria-labelledby="features-heading">
          <div className="grid gap-10 lg:grid-cols-[18rem_1fr] lg:gap-16">
            <div>
              <h2 id="features-heading" className="text-2xl font-semibold tracking-tight">
                Built for studying, not skimming
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                Everything works from one chat. Type a question or pick an action under the message box.
              </p>
            </div>
            <ul className="grid gap-x-10 gap-y-8 sm:grid-cols-2">
              {FEATURES.map(({ icon: Icon, title, text }) => (
                <li key={title} className="flex gap-4">
                  <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary" aria-hidden>
                    <Icon className="size-[18px]" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">{title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{text}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="border-t border-border/70">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>AskMyPDF · answers come only from your documents</span>
          <span>Your files are private to your account. Delete them anytime.</span>
        </div>
      </footer>
    </div>
  );
}
