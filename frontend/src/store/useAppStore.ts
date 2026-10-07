import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { DocumentInfo, FlashcardDeck, Intent, Quiz, RouterParams, SourceChunk } from "@/api/types";

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
  pdfPage: number;
  pdfJumpKey: number;
  sidebarOpen: boolean;
  pdfOpen: boolean;
  activeQuiz: ActiveQuiz | null;
  shortcutsOpen: boolean;

  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setView: (v: View) => void;
  setDocuments: (docs: DocumentInfo[]) => void;
  upsertDocument: (doc: DocumentInfo) => void;
  removeDocument: (id: string) => void;
  setActiveDoc: (id: string | null) => void;
  addMessage: (docId: string, msg: ChatMessage) => void;
  patchMessage: (docId: string, id: string, patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => void;
  clearChat: (docId: string) => void;
  jumpToPage: (page: number) => void;
  setPdfPage: (page: number) => void;
  setSidebarOpen: (open: boolean) => void;
  setPdfOpen: (open: boolean) => void;
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
      pdfPage: 1,
      pdfJumpKey: 0,
      sidebarOpen: false,
      pdfOpen: false,
      activeQuiz: null,
      shortcutsOpen: false,

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
          const activeDocId = s.activeDocId === id ? (documents[0]?.doc_id ?? null) : s.activeDocId;
          return { documents, messages, activeDocId, view: activeDocId ? s.view : "landing" };
        }),
      setActiveDoc: (activeDocId) => set({ activeDocId, pdfPage: 1, view: "workspace", sidebarOpen: false }),
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
      jumpToPage: (page) =>
        set((s) => ({
          pdfPage: Math.max(1, page),
          pdfJumpKey: s.pdfJumpKey + 1,
          // On narrow screens the viewer is a drawer: open it so the jump is visible.
          pdfOpen: window.matchMedia("(min-width: 1280px)").matches ? s.pdfOpen : true,
        })),
      setPdfPage: (pdfPage) => set({ pdfPage }),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
      setPdfOpen: (pdfOpen) => set({ pdfOpen }),
      openQuiz: (quiz, order) => set({ activeQuiz: { quiz, order: order ?? quiz.questions.map((_, i) => i) } }),
      closeQuiz: () => set({ activeQuiz: null }),
      setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
    }),
    {
      name: "askmypdf",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ theme: s.theme, activeDocId: s.activeDocId, messages: s.messages }),
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

const EMPTY: ChatMessage[] = [];
export const useActiveMessages = () => useAppStore((s) => (s.activeDocId ? (s.messages[s.activeDocId] ?? EMPTY) : EMPTY));
