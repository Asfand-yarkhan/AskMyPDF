import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { Drawer } from "@/components/Drawer";
import { PdfViewer } from "@/components/PdfViewer";
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
  const pdfOpen = useAppStore((s) => s.pdfOpen);
  const setPdfOpen = useAppStore((s) => s.setPdfOpen);
  const isLg = useMediaQuery("(min-width: 1024px)");
  const isXl = useMediaQuery("(min-width: 1280px)");

  // Desktop starts with the viewer docked open.
  useEffect(() => {
    if (window.matchMedia("(min-width: 1280px)").matches) setPdfOpen(true);
  }, [setPdfOpen]);

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

      {isXl ? (
        <AnimatePresence initial={false}>
          {pdfOpen && (
            <motion.aside
              key="pdf"
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: "min(42vw, 640px)", opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ type: "spring", stiffness: 260, damping: 32 }}
              className="shrink-0 overflow-hidden border-l border-border/60 bg-card/40 backdrop-blur-xl"
              aria-label="PDF viewer"
            >
              <div className="h-full w-[min(42vw,640px)]">
                <PdfViewer doc={doc} />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      ) : (
        <Drawer open={pdfOpen} onClose={() => setPdfOpen(false)} side="right" label="PDF viewer" className="w-full bg-card/95 backdrop-blur-xl sm:w-[34rem]">
          <PdfViewer doc={doc} onClose={() => setPdfOpen(false)} />
        </Drawer>
      )}

      <QuizModal />
    </div>
  );
}
