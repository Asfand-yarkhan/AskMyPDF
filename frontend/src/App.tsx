import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { CloudOff, RotateCcw } from "lucide-react";
import { useEffect } from "react";
import { Toaster } from "sonner";
import { AuthDialog } from "@/components/AuthDialog";
import { Logo } from "@/components/Logo";
import { ShortcutsDialog } from "@/components/ShortcutsDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useDocuments } from "@/hooks/useDocuments";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { initAuth } from "@/lib/auth";
import { LandingPage } from "@/pages/LandingPage";
import { WorkspacePage } from "@/pages/WorkspacePage";
import { useActiveDocument, useAppStore } from "@/store/useAppStore";
import { useAuthStore } from "@/store/useAuthStore";

export default function App() {
  useEffect(() => initAuth(), []);
  useDocuments();
  const theme = useAppStore((s) => s.theme);
  const view = useAppStore((s) => s.view);
  const loaded = useAppStore((s) => s.documentsLoaded);
  const authStatus = useAuthStore((s) => s.status);
  const activeDoc = useActiveDocument();
  const showWorkspace = view === "workspace" && activeDoc !== null;

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        {authStatus === "error" ? (
          <AuthError />
        ) : authStatus === "loading" || !loaded ? (
          <AppSkeleton />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={showWorkspace ? "workspace" : "landing"}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="h-full"
            >
              {showWorkspace ? <WorkspacePage /> : <LandingWithShortcuts />}
            </motion.div>
          </AnimatePresence>
        )}
        <ShortcutsDialog />
        <AuthDialog />
        <Toaster theme={theme} position="top-center" closeButton toastOptions={{ className: "rounded-xl" }} />
      </TooltipProvider>
    </MotionConfig>
  );
}

/** The workspace registers shortcuts via ChatPanel; the landing page needs its own. */
function LandingWithShortcuts() {
  useKeyboardShortcuts();
  return <LandingPage />;
}

function AuthError() {
  const error = useAuthStore((s) => s.error);
  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <div className="max-w-sm text-center">
        <Logo className="justify-center" />
        <div className="mx-auto mt-10 grid size-12 place-items-center rounded-xl bg-destructive/10 text-destructive">
          <CloudOff className="size-6" />
        </div>
        <h1 className="mt-4 text-lg font-semibold">We couldn't start your session</h1>
        <p className="mt-2 text-sm text-muted-foreground">{error ?? "Check your connection and try again."}</p>
        <Button className="mt-6" onClick={() => window.location.reload()}>
          <RotateCcw /> Try again
        </Button>
      </div>
    </main>
  );
}

function AppSkeleton() {
  return (
    <div className="flex h-dvh" aria-busy="true" aria-label="Loading">
      <div className="hidden w-72 flex-col gap-3 border-r border-border/70 p-4 lg:flex">
        <Skeleton className="h-9 w-36" />
        <Skeleton className="mt-3 h-10" />
        <Skeleton className="mt-4 h-12" />
        <Skeleton className="h-12" />
      </div>
      <div className="flex flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-border/70 px-5 py-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="ml-auto size-9" />
        </div>
        <div className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-6 py-8">
          <Skeleton className="ml-auto h-10 w-1/2" />
          <Skeleton className="h-28" />
        </div>
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          <Skeleton className="h-14" />
        </div>
      </div>
    </div>
  );
}
