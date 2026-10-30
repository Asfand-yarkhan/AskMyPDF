import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, BookOpen, Eraser, ExternalLink, GraduationCap, Layers, ListChecks, LockKeyhole, MailWarning, Menu, MessageSquareText, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { DocumentInfo } from "@/api/types";
import { AccountMenu, TrialMeter } from "@/components/AccountMenu";
import { ChatInput } from "@/components/ChatInput";
import { ChatMessage } from "@/components/ChatMessage";
import { DocumentScopePicker, ScopeChips } from "@/components/DocumentScopePicker";
import { QuickActions } from "@/components/QuickActions";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useChat } from "@/hooks/useChat";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { STRATEGY_LABELS } from "@/lib/utils";
import { useActiveMessages, useAppStore } from "@/store/useAppStore";
import { useAuthStore, useTrialsExhausted } from "@/store/useAuthStore";

const SUGGESTIONS = [
  { icon: Sparkles, title: "Summarize", text: "Give me a detailed summary of this document" },
  { icon: GraduationCap, title: "Quiz me", text: "Generate a 10-question medium quiz" },
  { icon: ListChecks, title: "Key points", text: "What are the key points?" },
  { icon: Layers, title: "Flashcards", text: "Make 12 flashcards for revision" },
];

export function ChatPanel({ doc }: { doc: DocumentInfo }) {
  const messages = useActiveMessages();
  const { send, stop, isStreaming } = useChat(doc.doc_id);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);
  const clearChat = useAppStore((s) => s.clearChat);
  const trialsUsedUp = useTrialsExhausted();

  useKeyboardShortcuts({ onStop: stop });

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  // Follow streaming output only while the user is already at the bottom.
  const last = messages[messages.length - 1];
  useEffect(() => {
    if (stickToBottom.current) scrollToBottom(false);
  }, [messages.length, last?.content, last?.quiz, last?.flashcards, last?.statusText, scrollToBottom]);

  useEffect(() => {
    stickToBottom.current = true;
    scrollToBottom(false);
  }, [doc.doc_id, scrollToBottom]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickToBottom.current = nearBottom;
    setShowJump(!nearBottom);
  };

  const sendAndFollow = (text: string) => {
    stickToBottom.current = true;
    void send(text);
  };

  const retryFrom = (index: number) => {
    const prevUser = [...messages.slice(0, index)].reverse().find((m) => m.role === "user");
    if (prevUser) sendAndFollow(prevUser.content);
  };

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col" aria-label="Chat">
      <header className="flex items-center gap-2 border-b border-border/60 px-3 py-2.5 sm:px-5">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="Open documents">
          <Menu />
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold sm:text-base">{doc.filename}</h1>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{doc.page_count} pages</span>·<span>{doc.chunk_count} chunks</span>
            <Badge variant="outline" className="hidden py-0 sm:inline-flex">{STRATEGY_LABELS[doc.chunk_config.strategy]}</Badge>
          </div>
        </div>
        {messages.length > 0 && (
          <Tooltip content="Clear chat">
            <Button variant="ghost" size="icon" onClick={() => clearChat(doc.doc_id)} aria-label="Clear chat" disabled={isStreaming}>
              <Eraser />
            </Button>
          </Tooltip>
        )}
        <DocumentScopePicker doc={doc} />
        <ThemeToggle />
        <Tooltip content="Open the PDF in a new tab">
          <Button variant="ghost" size="icon" asChild aria-label="Open PDF in a new tab">
            <a href={api.fileUrl(doc)} target="_blank" rel="noreferrer">
              <ExternalLink />
            </a>
          </Button>
        </Tooltip>
        <div className="ml-1 hidden sm:block">
          <AccountMenu compact />
        </div>
      </header>
      <ScopeChips doc={doc} />

      <div ref={scrollRef} onScroll={onScroll} className="relative flex-1 overflow-y-auto scrollbar-thin">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-3 py-6 sm:px-6">
          {messages.length === 0 ? (
            <EmptyChat doc={doc} onPick={sendAndFollow} />
          ) : (
            messages.map((m, i) => (
              <ChatMessage key={m.id} message={m} onRetry={m.status === "error" ? () => retryFrom(i) : undefined} />
            ))
          )}
        </div>
      </div>

      <div className="relative mx-auto w-full max-w-3xl space-y-2 px-3 pb-3 pt-2 sm:px-6 sm:pb-5">
        <AnimatePresence>
          {showJump && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} className="absolute -top-10 left-1/2 -translate-x-1/2">
              <Button
                size="sm"
                variant="outline"
                className="rounded-full shadow-lg"
                onClick={() => {
                  stickToBottom.current = true;
                  scrollToBottom();
                }}
              >
                <ArrowDown /> Latest
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
        {trialsUsedUp ? (
          <SignUpPrompt />
        ) : (
          <>
            <QuickActions onSend={sendAndFollow} disabled={isStreaming} />
            <ChatInput onSend={sendAndFollow} onStop={stop} streaming={isStreaming} />
            <TrialMeter className="justify-center pt-0.5" />
          </>
        )}
      </div>
    </section>
  );
}

/** Replaces the composer once a guest's free questions are used. */
function SignUpPrompt() {
  const openDialog = useAuthStore((s) => s.openDialog);
  const limit = useAuthStore((s) => s.trials?.limit ?? 3);
  const pendingEmail = useAuthStore((s) => (s.user?.pendingVerification ? s.user.email : null));

  if (pendingEmail) {
    return (
      <div className="surface animate-rise flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:items-center sm:gap-4">
        <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-warning/10 text-warning">
          <MailWarning className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">Verify your email to keep going</p>
          <p className="break-words text-sm text-muted-foreground">Open the link we sent to {pendingEmail}. This chat stays with you.</p>
        </div>
        <Button onClick={() => openDialog("trial", "verify")}>I've verified</Button>
      </div>
    );
  }

  return (
    <div className="surface animate-rise flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:items-center sm:gap-4">
      <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
        <LockKeyhole className="size-5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">You have used your {limit} free questions</p>
        <p className="text-sm text-muted-foreground">Create a free account to keep asking. This chat stays with you.</p>
      </div>
      <div className="flex gap-2">
        <Button variant="ghost" onClick={() => openDialog("trial", "signin")}>
          Sign in
        </Button>
        <Button onClick={() => openDialog("trial", "signup")}>Create account</Button>
      </div>
    </div>
  );
}

function EmptyChat({ doc, onPick }: { doc: DocumentInfo; onPick: (text: string) => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col items-center py-6 text-center sm:py-12">
      <div className="grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
        <MessageSquareText className="size-6" />
      </div>
      <h2 className="mt-5 text-xl font-semibold tracking-tight sm:text-2xl">Ask your document anything</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Answers come only from <span className="font-medium text-foreground">{doc.filename}</span>, with page citations you can click to open the PDF at that page.
      </p>
      <div className="mt-8 grid w-full gap-3 sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, title, text }, i) => (
          <motion.button
            key={title}
            type="button"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06 * i, duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            onClick={() => onPick(text)}
            className="focus-ring surface group flex items-start gap-3 rounded-xl p-4 text-left transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/40"
          >
            <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
              <Icon className="size-4" />
            </div>
            <div>
              <div className="text-sm font-semibold">{title}</div>
              <div className="text-xs text-muted-foreground">{text}</div>
            </div>
          </motion.button>
        ))}
      </div>
      <p className="mt-6 flex items-center gap-1.5 text-xs text-muted-foreground">
        <BookOpen className="size-3.5" /> Tip: ask in English, اردو or Roman Urdu. Replies match your language.
      </p>
    </motion.div>
  );
}
