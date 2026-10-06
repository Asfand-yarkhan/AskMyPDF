import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { Toaster } from "sonner";
import { BackgroundGradient } from "@/components/BackgroundGradient";
import { ShortcutsDialog } from "@/components/ShortcutsDialog";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useDocuments } from "@/hooks/useDocuments";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { LandingPage } from "@/pages/LandingPage";
import { WorkspacePage } from "@/pages/WorkspacePage";
import { useActiveDocument, useAppStore } from "@/store/useAppStore";

export default function App() {
  useDocuments();
  const theme = useAppStore((s) => s.theme);
  const view = useAppStore((s) => s.view);
  const loaded = useAppStore((s) => s.documentsLoaded);
  const activeDoc = useActiveDocument();
  const showWorkspace = view === "workspace" && activeDoc !== null;

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        <BackgroundGradient />
        {!loaded ? (
          <AppSkeleton />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={showWorkspace ? "workspace" : "landing"}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="h-full"
            >
              {showWorkspace ? <WorkspacePage /> : <LandingWithShortcuts />}
            </motion.div>
          </AnimatePresence>
        )}
        <ShortcutsDialog />
        <Toaster theme={theme} position="top-center" richColors closeButton toastOptions={{ className: "rounded-2xl" }} />
      </TooltipProvider>
    </MotionConfig>
  );
}

/** The workspace registers shortcuts via ChatPanel; the landing page needs its own. */
function LandingWithShortcuts() {
  useKeyboardShortcuts();
  return <LandingPage />;
}

function AppSkeleton() {
  return (
    <div className="flex h-dvh gap-4 p-4">
      <Skeleton className="hidden w-72 lg:block" />
      <div className="flex flex-1 flex-col gap-4">
        <Skeleton className="h-12" />
        <Skeleton className="flex-1" />
        <Skeleton className="h-16" />
      </div>
    </div>
  );
}
