import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";
import { streamChat } from "@/api/client";
import type { ChatEvent, ChatTurn } from "@/api/types";
import { uid } from "@/lib/utils";
import { type ChatMessage, useAppStore } from "@/store/useAppStore";

const HISTORY_MESSAGES = 12;

/** What the backend sees of earlier turns (quizzes/flashcards are summarized). */
function toTurn(m: ChatMessage): ChatTurn | null {
  if (m.status === "error") return null;
  let content = m.content;
  if (m.quiz) content = `[Generated a ${m.quiz.questions.length}-question ${m.quiz.difficulty} quiz: ${m.quiz.title}]`;
  if (m.flashcards) content = `[Generated ${m.flashcards.cards.length} flashcards: ${m.flashcards.title}]`;
  return content.trim() ? { role: m.role, content: content.slice(0, 4000) } : null;
}

export function useChat(docId: string | null) {
  const controllerRef = useRef<AbortController | null>(null);
  const isStreaming = useAppStore((s) =>
    docId ? (s.messages[docId] ?? []).some((m) => m.status === "streaming") : false,
  );

  useEffect(() => () => controllerRef.current?.abort(), [docId]);

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!docId || !message) return;
      const store = useAppStore.getState();
      if ((store.messages[docId] ?? []).some((m) => m.status === "streaming")) return;

      const history = (store.messages[docId] ?? [])
        .map(toTurn)
        .filter((t): t is ChatTurn => t !== null)
        .slice(-HISTORY_MESSAGES);

      const known = new Set(store.documents.map((d) => d.doc_id));
      const extraDocIds = (store.extraDocIds[docId] ?? []).filter((id) => known.has(id) && id !== docId);

      const assistantId = uid();
      store.addMessage(docId, { id: uid(), role: "user", content: message, createdAt: Date.now() });
      store.addMessage(docId, {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: Date.now(),
        status: "streaming",
        statusText: "Thinking...",
        docIds: [docId, ...extraDocIds],
      });

      const patch = (p: Parameters<typeof store.patchMessage>[2]) =>
        useAppStore.getState().patchMessage(docId, assistantId, p);

      // Tokens arrive faster than React needs to paint; flush them once per frame.
      let pending = "";
      let frame = 0;
      const flush = () => {
        frame = 0;
        if (!pending) return;
        const chunk = pending;
        pending = "";
        patch((m) => ({ content: m.content + chunk, statusText: undefined }));
      };

      const onEvent = (event: ChatEvent) => {
        switch (event.type) {
          case "intent":
            // Summaries, notes, quizzes and flashcards only use the active document.
            patch({
              intent: event.intent,
              params: event.params,
              ...(["QA", "EXPLAIN"].includes(event.intent) ? {} : { docIds: [docId] }),
            });
            break;
          case "cached":
            patch({ cached: true });
            break;
          case "status":
            patch({ statusText: event.message });
            break;
          case "sources":
            patch({ sources: event.sources });
            break;
          case "token":
            pending += event.content;
            if (!frame) frame = requestAnimationFrame(flush);
            break;
          case "quiz":
            patch({ quiz: event.quiz, statusText: undefined });
            break;
          case "flashcards":
            patch({ flashcards: event.flashcards, statusText: undefined });
            break;
          case "error":
            patch({ error: event.message });
            toast.error(event.message);
            break;
          case "done":
            break;
        }
      };

      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        await streamChat({ doc_id: docId, extra_doc_ids: extraDocIds, message, history }, onEvent, controller.signal);
        if (frame) cancelAnimationFrame(frame);
        flush();
        patch((m) => ({
          status: m.error && !m.content && !m.quiz && !m.flashcards ? "error" : "done",
          statusText: undefined,
        }));
      } catch (err) {
        if (frame) cancelAnimationFrame(frame);
        flush();
        if ((err as Error).name === "AbortError") {
          patch((m) => ({ status: "done", statusText: undefined, content: m.content || "_Stopped._" }));
        } else {
          const msg = (err as Error).message || "Something went wrong.";
          patch({ status: "error", statusText: undefined, error: msg });
          toast.error(msg);
        }
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    [docId],
  );

  return { send, stop, isStreaming };
}
