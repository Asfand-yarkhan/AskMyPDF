import { useEffect } from "react";
import { useAppStore } from "@/store/useAppStore";

export const SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ["/"], label: "Focus the chat input" },
  { keys: ["Mod", "K"], label: "Focus the chat input" },
  { keys: ["Mod", "U"], label: "Upload a new PDF" },
  { keys: ["Mod", "B"], label: "Toggle document sidebar" },
  { keys: ["Mod", "J"], label: "Toggle PDF viewer" },
  { keys: ["Mod", "Shift", "L"], label: "Toggle dark / light mode" },
  { keys: ["Enter"], label: "Send message" },
  { keys: ["Shift", "Enter"], label: "New line" },
  { keys: ["Esc"], label: "Stop generating / close dialogs" },
  { keys: ["1-4"], label: "Pick a quiz option" },
  { keys: ["Space"], label: "Flip flashcard" },
  { keys: ["?"], label: "Show shortcuts" },
];

export const CHAT_INPUT_ID = "chat-input";

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

export function useKeyboardShortcuts({ onStop }: { onStop?: () => void } = {}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const s = useAppStore.getState();
      const mod = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();

      if (key === "escape") {
        if (s.shortcutsOpen) s.setShortcutsOpen(false);
        else if (s.sidebarOpen) s.setSidebarOpen(false);
        else onStop?.();
        return;
      }
      if (s.activeQuiz) return; // the quiz modal owns the keyboard

      if ((key === "/" && !isTyping(e.target)) || (mod && key === "k")) {
        e.preventDefault();
        document.getElementById(CHAT_INPUT_ID)?.focus();
      } else if (mod && key === "u") {
        e.preventDefault();
        s.setView("landing");
      } else if (mod && key === "b") {
        e.preventDefault();
        s.setSidebarOpen(!s.sidebarOpen);
      } else if (mod && key === "j") {
        e.preventDefault();
        s.setPdfOpen(!s.pdfOpen);
      } else if (mod && e.shiftKey && key === "l") {
        e.preventDefault();
        s.toggleTheme();
      } else if (e.key === "?" && !isTyping(e.target)) {
        e.preventDefault();
        s.setShortcutsOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onStop]);
}
