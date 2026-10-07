import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { Drawer } from "@/components/Drawer";
import { QuizModal } from "@/components/QuizModal";
import { Sidebar } from "@/components/Sidebar";
import { useActiveDocument, useAppStore } from "@/store/useAppStore";

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

export function WorkspacePage() {
  const doc = useActiveDocument();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);
  const isLg = useMediaQuery("(min-width: 1024px)");

  if (!doc) return null;

  return (
    <div className="flex h-dvh overflow-hidden">
      {isLg ? (
        // On desktop Ctrl+B collapses the docked sidebar.
        <AnimatePresence initial={false}>
          {!sidebarOpen && (
            <motion.div initial={{ width: 0, opacity: 0 }} animate={{ width: "auto", opacity: 1 }} exit={{ width: 0, opacity: 0 }} className="shrink-0 overflow-hidden">
              <Sidebar />
            </motion.div>
          )}
        </AnimatePresence>
      ) : (
        <Drawer open={sidebarOpen} onClose={() => setSidebarOpen(false)} side="left" label="Documents">
          <Sidebar onClose={() => setSidebarOpen(false)} />
        </Drawer>
      )}

      <ChatPanel doc={doc} />

      <QuizModal />
    </div>
  );
}
