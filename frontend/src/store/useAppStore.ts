import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { DocumentInfo, FlashcardDeck, Intent, Quiz, RouterParams, SourceChunk } from "@/api/types";
import { type CardState, type Grade, review } from "@/lib/srs";

export type Theme = "light" | "dark";
export type View = "landing" | "workspace";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  status?: "streaming" | "done" | "error";
  statusText?: string;
  intent?: Intent;
  params?: RouterParams;
  sources?: SourceChunk[];
  quiz?: Quiz;
  flashcards?: FlashcardDeck;
  error?: string;
  /** Documents searched for this answer, in citation order ([Doc 1, ...]). */
  docIds?: string[];
  /** Served instantly from the server-side answer cache. */
  cached?: boolean;
}

export interface ActiveQuiz {
  quiz: Quiz;
  /** Indexes into quiz.questions; lets "retry wrong ones" reuse the same quiz. */
  order: number[];
}

interface AppState {
  theme: Theme;
  view: View;
  documents: DocumentInfo[];
  documentsLoaded: boolean;
  activeDocId: string | null;
  messages: Record<string, ChatMessage[]>;
  sidebarOpen: boolean;
  activeQuiz: ActiveQuiz | null;
  shortcutsOpen: boolean;
  /** Extra documents searched together with the active one, keyed by active doc id. */
  extraDocIds: Record<string, string[]>;
  /** Spaced-repetition state per flashcard, keyed `${messageId}:${cardIndex}`. */
  srs: Record<string, CardState>;

  setTheme: (t: Theme) => void;
  setExtraDocs: (docId: string, ids: string[]) => void;
  rateCard: (key: string, grade: Grade) => void;
  toggleTheme: () => void;
  setView: (v: View) => void;
  setDocuments: (docs: DocumentInfo[]) => void;
  upsertDocument: (doc: DocumentInfo) => void;
  removeDocument: (id: string) => void;
  setActiveDoc: (id: string | null) => void;
  addMessage: (docId: string, msg: ChatMessage) => void;
  patchMessage: (docId: string, id: string, patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => void;
  clearChat: (docId: string) => void;
  setSidebarOpen: (open: boolean) => void;
  openQuiz: (quiz: Quiz, order?: number[]) => void;
  closeQuiz: () => void;
  setShortcutsOpen: (open: boolean) => void;
}

const MAX_MESSAGES_PER_DOC = 120;

const applyTheme = (theme: Theme) => document.documentElement.classList.toggle("dark", theme === "dark");

const preferredTheme = (): Theme =>
  window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      theme: preferredTheme(),
      view: "landing",
      documents: [],
      documentsLoaded: false,
      activeDocId: null,
      messages: {},
      sidebarOpen: false,
      activeQuiz: null,
      shortcutsOpen: false,
      extraDocIds: {},
      srs: {},

      setExtraDocs: (docId, ids) =>
        set((s) => ({ extraDocIds: { ...s.extraDocIds, [docId]: ids.filter((i) => i !== docId) } })),
      rateCard: (key, grade) => set((s) => ({ srs: { ...s.srs, [key]: review(s.srs[key], grade) } })),
      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
      toggleTheme: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
      setView: (view) => set({ view }),
      setDocuments: (documents) =>
        set((s) => {
          const activeDocId = documents.some((d) => d.doc_id === s.activeDocId)
            ? s.activeDocId
            : (documents[0]?.doc_id ?? null);
          // First load: returning users land straight back in their last chat.
          const view = !s.documentsLoaded && activeDocId ? "workspace" : s.view;
          return { documents, documentsLoaded: true, activeDocId, view };
        }),
      upsertDocument: (doc) =>
        set((s) => ({ documents: [doc, ...s.documents.filter((d) => d.doc_id !== doc.doc_id)] })),
      removeDocument: (id) =>
        set((s) => {
          const documents = s.documents.filter((d) => d.doc_id !== id);
          const messages = { ...s.messages };
          delete messages[id];
          const extraDocIds = Object.fromEntries(
            Object.entries(s.extraDocIds)
              .filter(([key]) => key !== id)
              .map(([key, ids]) => [key, ids.filter((i) => i !== id)]),
          );
          const activeDocId = s.activeDocId === id ? (documents[0]?.doc_id ?? null) : s.activeDocId;
          return { documents, messages, extraDocIds, activeDocId, view: activeDocId ? s.view : "landing" };
        }),
      setActiveDoc: (activeDocId) => set({ activeDocId, view: "workspace", sidebarOpen: false }),
      addMessage: (docId, msg) =>
        set((s) => ({
          messages: { ...s.messages, [docId]: [...(s.messages[docId] ?? []), msg].slice(-MAX_MESSAGES_PER_DOC) },
        })),
      patchMessage: (docId, id, patch) =>
        set((s) => ({
          messages: {
            ...s.messages,
            [docId]: (s.messages[docId] ?? []).map((m) =>
              m.id === id ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m,
            ),
          },
        })),
      clearChat: (docId) => set((s) => ({ messages: { ...s.messages, [docId]: [] } })),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
      openQuiz: (quiz, order) => set({ activeQuiz: { quiz, order: order ?? quiz.questions.map((_, i) => i) } }),
      closeQuiz: () => set({ activeQuiz: null }),
      setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
    }),
    {
      name: "askmypdf",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        theme: s.theme,
        activeDocId: s.activeDocId,
        messages: s.messages,
        extraDocIds: s.extraDocIds,
        srs: s.srs,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        applyTheme(state.theme);
        // Streams cannot survive a reload: mark interrupted answers as finished.
        for (const list of Object.values(state.messages)) {
          for (const m of list) if (m.status === "streaming") m.status = m.content ? "done" : "error";
        }
      },
    },
  ),
);

export const useActiveDocument = () =>
  useAppStore((s) => s.documents.find((d) => d.doc_id === s.activeDocId) ?? null);

const NO_IDS: string[] = [];
/** Extra documents for the active chat, limited to ones that still exist. */
export const useExtraDocIds = () =>
  useAppStore((s) => (s.activeDocId ? (s.extraDocIds[s.activeDocId] ?? NO_IDS) : NO_IDS));

const EMPTY: ChatMessage[] = [];
export const useActiveMessages = () => useAppStore((s) => (s.activeDocId ? (s.messages[s.activeDocId] ?? EMPTY) : EMPTY));
