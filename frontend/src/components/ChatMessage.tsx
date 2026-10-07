import { motion } from "framer-motion";
import { AlertTriangle, Bot, Check, Copy, Files, RotateCcw, User, Zap } from "lucide-react";
import { memo, useMemo, useState } from "react";
import type { Intent } from "@/api/types";
import { CitationContext } from "@/components/CitationContext";
import { FlashcardDeck } from "@/components/FlashcardDeck";
import { Markdown } from "@/components/Markdown";
import { QuizCard } from "@/components/QuizCard";
import { SourcesList } from "@/components/SourcesList";
import { TypingIndicator } from "@/components/TypingIndicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ChatMessage as Message } from "@/store/useAppStore";

const INTENT_LABEL: Partial<Record<Intent, string>> = {
  SUMMARY: "Summary",
  QUIZ: "Quiz",
  FLASHCARDS: "Flashcards",
  NOTES: "Study notes",
  EXPLAIN: "Explanation",
};

export const ChatMessage = memo(function ChatMessage({
  message,
  onRetry,
}: {
  message: Message;
  onRetry?: () => void;
}) {
  const isUser = message.role === "user";
  const streaming = message.status === "streaming";
  const waiting = streaming && !message.content && !message.quiz && !message.flashcards;
  const scope = useMemo(
    () => ({ docIds: message.docIds ?? [], sources: message.sources ?? [] }),
    [message.docIds, message.sources],
  );
  const docCount = message.docIds?.length ?? 1;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 26 }}
      className={cn("flex gap-3", isUser && "flex-row-reverse")}
    >
      <div
        className={cn(
          "mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl",
          isUser ? "bg-secondary text-foreground" : "bg-brand text-white shadow-md shadow-indigo-500/30",
        )}
        aria-hidden
      >
        {isUser ? <User className="size-4" /> : <Bot className="size-4" />}
      </div>

      {isUser ? (
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-brand px-4 py-2.5 text-sm text-white shadow-lg shadow-indigo-500/20">
          {message.content}
        </div>
      ) : (
        <div className="group min-w-0 max-w-full flex-1 sm:max-w-[92%]">
          <CitationContext.Provider value={scope}>
          <div className="glass rounded-2xl rounded-tl-md px-4 py-3">
            {(INTENT_LABEL[message.intent ?? "QA"] || docCount > 1 || message.cached) && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {message.intent && INTENT_LABEL[message.intent] && (
                  <Badge>{INTENT_LABEL[message.intent]}{message.params?.topic ? ` · ${message.params.topic}` : ""}</Badge>
                )}
                {docCount > 1 && (
                  <Badge variant="outline">
                    <Files /> {docCount} documents
                  </Badge>
                )}
                {message.cached && (
                  <Badge variant="success" title="Answered instantly from the cache">
                    <Zap /> Instant
                  </Badge>
                )}
              </div>
            )}

            {waiting && <TypingIndicator text={message.statusText} />}
            {message.content && <Markdown content={message.content} />}
            {streaming && message.content && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary align-middle" aria-hidden />
            )}
            {message.quiz && <QuizCard quiz={message.quiz} />}
            {message.flashcards && <FlashcardDeck deck={message.flashcards} deckId={message.id} />}

            {message.error && !message.content && !message.quiz && !message.flashcards && (
              <div className="flex items-start gap-2 text-sm text-destructive">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>{message.error}</span>
              </div>
            )}

            {message.sources && message.sources.length > 0 && !streaming && <SourcesList sources={message.sources} />}
          </div>
          </CitationContext.Provider>

          {!streaming && (
            <div className="mt-1 flex gap-1 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
              {message.content && <CopyButton text={message.content} />}
              {message.status === "error" && onRetry && (
                <Button variant="ghost" size="sm" onClick={onRetry}>
                  <RotateCcw /> Retry
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
});

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip content={copied ? "Copied!" : "Copy"}>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Copy answer"
        onClick={async () => {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check className="text-success" /> : <Copy />}
      </Button>
    </Tooltip>
  );
}
