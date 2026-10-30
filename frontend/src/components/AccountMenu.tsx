import { AnimatePresence, motion } from "framer-motion";
import { LogOut, MailWarning } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { authEnabled, signOut } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { isLimited, useAuthStore } from "@/store/useAuthStore";

/** "2 of 3 free questions left": shown to guests so the limit never comes as a surprise. */
export function TrialMeter({ className }: { className?: string }) {
  const trials = useAuthStore((s) => (isLimited(s.user) ? s.trials : null));
  if (!trials) return null;
  const { remaining, limit } = trials;
  return (
    <div className={cn("flex items-center gap-2 text-xs text-muted-foreground", className)} aria-live="polite">
      <span className="flex gap-0.5" aria-hidden>
        {Array.from({ length: limit }, (_, i) => (
          <span key={i} className={cn("h-1.5 w-3 rounded-full transition-colors duration-200", i < remaining ? "bg-primary" : "bg-border")} />
        ))}
      </span>
      <span className="tabular-nums">
        {remaining > 0 ? `${remaining} of ${limit} free ${limit === 1 ? "question" : "questions"} left` : "Free questions used"}
      </span>
    </div>
  );
}

function initials(name: string | null, email: string | null) {
  const source = name?.trim() || email?.split("@")[0] || "?";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** Header account control: sign-up prompts for guests, a profile menu for members. */
export function AccountMenu({ compact = false, up = false }: { compact?: boolean; up?: boolean }) {
  const user = useAuthStore((s) => s.user);
  const openDialog = useAuthStore((s) => s.openDialog);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!authEnabled || !user) return null;

  if (user.isGuest) {
    return (
      <div className="flex items-center gap-1">
        {!compact && (
          <Button variant="ghost" size="sm" onClick={() => openDialog("manual", "signin")}>
            Sign in
          </Button>
        )}
        <Button size="sm" onClick={() => openDialog("manual", "signup")}>
          {compact ? "Sign up" : "Create account"}
        </Button>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Account"
        className="focus-ring grid size-9 place-items-center overflow-hidden rounded-lg bg-primary/10 text-xs font-semibold text-primary transition-colors hover:bg-primary/15"
      >
        {user.photoURL ? <img src={user.photoURL} alt="" className="size-full object-cover" referrerPolicy="no-referrer" /> : initials(user.name, user.email)}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className={cn("surface absolute z-40 w-64 rounded-xl p-1.5", up ? "bottom-full left-0 mb-2" : "right-0 top-full mt-2")}
          >
            <div className="px-2.5 py-2">
              {user.name && <p className="truncate text-sm font-medium">{user.name}</p>}
              <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            </div>
            <VerifyEmailHint onOpen={() => setOpen(false)} />
            <div className="my-1 h-px bg-border" />
            <button
              type="button"
              role="menuitem"
              onClick={async () => {
                setOpen(false);
                await signOut();
                toast.success("Signed out");
              }}
              className="focus-ring flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors hover:bg-secondary"
            >
              <LogOut className="size-4 text-muted-foreground" /> Sign out
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function VerifyEmailHint({ onOpen }: { onOpen: () => void }) {
  const pending = useAuthStore((s) => s.user?.pendingVerification);
  const openDialog = useAuthStore((s) => s.openDialog);
  if (!pending) return null;
  return (
    <div className="mx-1 mb-1 rounded-lg bg-warning/10 px-2.5 py-2 text-xs">
      <p className="flex items-start gap-2">
        <MailWarning className="mt-0.5 size-3.5 shrink-0 text-warning" />
        Verify your email to unlock unlimited questions.
      </p>
      <button
        type="button"
        onClick={() => {
          onOpen();
          openDialog("manual", "verify");
        }}
        className="focus-ring ml-5 mt-1 rounded font-medium text-primary hover:underline"
      >
        Verify now
      </button>
    </div>
  );
}
