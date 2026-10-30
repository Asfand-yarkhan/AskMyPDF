import { Check, Eye, EyeOff, Loader2, MailCheck } from "lucide-react";
import { type FormEvent, useEffect, useId, useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import {
  authErrorMessage,
  checkVerification,
  continueWithGoogle,
  isPopupDismissed,
  resendVerification,
  resetPassword,
  signInWithEmail,
  signUpWithEmail,
} from "@/lib/auth";
import { cn } from "@/lib/utils";
import { type AuthMode, type AuthReason, useAuthStore } from "@/store/useAuthStore";

const BENEFITS = [
  "Unlimited questions, summaries and quizzes",
  "Your documents stay private to your account",
  "Chats and flashcards saved on this device",
];

function headline(reason: AuthReason, mode: AuthMode, limit: number) {
  if (mode === "signin") return { title: "Sign in to AskMyPDF", sub: "Welcome back. Your documents are where you left them." };
  if (mode === "reset") return { title: "Reset your password", sub: "We will email you a link to choose a new password." };
  if (mode === "verify") return { title: "Verify your email", sub: "One more step before your account is ready." };
  if (reason === "trial")
    return {
      title: `You have used your ${limit} free questions`,
      sub: "Create a free account to keep going. Your document and this chat come with you.",
    };
  if (reason === "upload")
    return { title: "Create an account to add more documents", sub: "Guests can try one document. An account keeps up to 50." };
  return { title: "Create your free account", sub: "Save your documents and keep asking without limits." };
}

export function AuthDialog() {
  const { open, reason, mode } = useAuthStore((s) => s.dialog);
  const limit = useAuthStore((s) => s.trials?.limit ?? 3);
  const closeDialog = useAuthStore((s) => s.closeDialog);
  const setMode = useAuthStore((s) => s.setMode);
  const { title, sub } = headline(reason, mode, limit);

  return (
    <Modal open={open} onClose={closeDialog} title={title} className="sm:max-w-[26rem]">
      <p className="-mt-2 mb-5 text-sm text-muted-foreground">{sub}</p>
      {mode === "verify" ? (
        <VerifyStep onDone={closeDialog} />
      ) : mode === "reset" ? (
        <ResetForm onBack={() => setMode("signin")} />
      ) : (
        <>
          {mode === "signup" && reason !== "manual" && (
            <ul className="mb-5 space-y-1.5 rounded-xl bg-secondary/60 p-3 text-sm">
              {BENEFITS.map((b) => (
                <li key={b} className="flex items-start gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-primary" /> {b}
                </li>
              ))}
            </ul>
          )}
          <AccountForm key={mode} mode={mode} onDone={closeDialog} onMode={setMode} />
        </>
      )}
    </Modal>
  );
}

function AccountForm({ mode, onDone, onMode }: { mode: "signup" | "signin"; onDone: () => void; onMode: (m: AuthMode) => void }) {
  const id = useId();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState<"google" | "email" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const signup = mode === "signup";

  /** `action` resolves false when the account still has to verify its email address. */
  const run = async (kind: "google" | "email", action: () => Promise<boolean | void>) => {
    setBusy(kind);
    setError(null);
    try {
      const ready = await action();
      if (ready === false) return onMode("verify");
      onDone();
      toast.success(signup ? "Account created" : "Signed in");
    } catch (err) {
      if (!isPopupDismissed(err)) setError(authErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (signup && password.length < 6) return setError("Use at least 6 characters for your password.");
    void run("email", async () =>
      signup ? (await signUpWithEmail(name, email, password), false) : signInWithEmail(email, password),
    );
  };

  return (
    <div className="space-y-5">
      <Button type="button" variant="outline" size="lg" className="w-full" disabled={busy !== null} onClick={() => void run("google", continueWithGoogle)}>
        {busy === "google" ? <Loader2 className="animate-spin" /> : <GoogleMark />}
        Continue with Google
      </Button>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span className="h-px flex-1 bg-border" /> or with email <span className="h-px flex-1 bg-border" />
      </div>

      <form onSubmit={submit} className="space-y-4" noValidate>
        {signup && (
          <Field id={`${id}-name`} label="Name">
            <Input id={`${id}-name`} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ayesha Khan" />
          </Field>
        )}
        <Field id={`${id}-email`} label="Email">
          <Input
            id={`${id}-email`}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@university.edu"
            aria-invalid={Boolean(error) || undefined}
          />
        </Field>
        <Field
          id={`${id}-password`}
          label="Password"
          action={
            !signup && (
              <button type="button" className="focus-ring rounded text-xs font-medium text-primary hover:underline" onClick={() => onMode("reset")}>
                Forgot password?
              </button>
            )
          }
        >
          <div className="relative">
            <Input
              id={`${id}-password`}
              type={showPassword ? "text" : "password"}
              autoComplete={signup ? "new-password" : "current-password"}
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="pr-10"
              aria-invalid={Boolean(error) || undefined}
              aria-describedby={signup ? `${id}-pw-hint` : undefined}
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="focus-ring absolute inset-y-0 right-0 grid w-10 place-items-center rounded-r-lg text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {signup && (
            <p id={`${id}-pw-hint`} className="text-xs text-muted-foreground">
              At least 6 characters.
            </p>
          )}
        </Field>

        {error && (
          <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        <Button type="submit" size="lg" className="w-full" disabled={busy !== null || !email || !password}>
          {busy === "email" && <Loader2 className="animate-spin" />}
          {signup ? "Create account" : "Sign in"}
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        {signup ? "Already have an account?" : "New to AskMyPDF?"}{" "}
        <button type="button" className="focus-ring rounded font-medium text-primary hover:underline" onClick={() => onMode(signup ? "signin" : "signup")}>
          {signup ? "Sign in" : "Create an account"}
        </button>
      </p>
    </div>
  );
}

const RESEND_COOLDOWN_S = 60;

/** "Check your inbox": the account works with guest limits until the emailed link is clicked. */
function VerifyStep({ onDone }: { onDone: () => void }) {
  const email = useAuthStore((s) => s.user?.email);
  const verified = useAuthStore((s) => s.user != null && !s.user.isGuest && !s.user.pendingVerification);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_S); // a link was just sent

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => window.clearTimeout(t);
  }, [cooldown]);

  // Verified in another tab: the focus listener in lib/auth refreshes the user, and we finish here.
  useEffect(() => {
    if (!verified) return;
    onDone();
    toast.success("Email verified. Your account is ready.");
  }, [verified, onDone]);

  const check = async () => {
    setChecking(true);
    setMessage(null);
    try {
      if (!(await checkVerification())) {
        setMessage({ tone: "error", text: "Not verified yet. Open the link in the email, then try again." });
      }
    } catch (err) {
      setMessage({ tone: "error", text: authErrorMessage(err) });
    } finally {
      setChecking(false);
    }
  };

  const resend = async () => {
    setMessage(null);
    try {
      await resendVerification();
      setCooldown(RESEND_COOLDOWN_S);
      setMessage({ tone: "info", text: "A new link is on its way." });
    } catch (err) {
      setMessage({ tone: "error", text: authErrorMessage(err) });
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-xl bg-secondary/60 p-4">
        <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <MailCheck className="size-5" />
        </div>
        <p className="text-sm leading-relaxed">
          We sent a verification link to <span className="font-medium break-all">{email}</span>. Open it to activate your
          account, then come back here. Check your spam folder if it isn't in your inbox.
        </p>
      </div>

      {message && (
        <p
          role={message.tone === "error" ? "alert" : "status"}
          className={cn(
            "rounded-lg px-3 py-2 text-sm",
            message.tone === "error" ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary",
          )}
        >
          {message.text}
        </p>
      )}

      <Button size="lg" className="w-full" onClick={() => void check()} disabled={checking}>
        {checking && <Loader2 className="animate-spin" />}
        I've verified my email
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        Didn't get it?{" "}
        <button
          type="button"
          onClick={() => void resend()}
          disabled={cooldown > 0}
          className="focus-ring rounded font-medium text-primary hover:underline disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
        >
          {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend link"}
        </button>
      </p>
      <p className="text-center text-xs text-muted-foreground">
        Until then you can keep using your free questions.
      </p>
    </div>
  );
}

function ResetForm({ onBack }: { onBack: () => void }) {
  const id = useId();
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setError(null), [email]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setState("sending");
    try {
      await resetPassword(email);
      setState("sent");
    } catch (err) {
      setError(authErrorMessage(err));
      setState("idle");
    }
  };

  if (state === "sent") {
    return (
      <div className="space-y-5 text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
          <MailCheck className="size-6" />
        </div>
        <p className="text-sm">
          If an account uses <span className="font-medium">{email}</span>, a reset link is on its way. Check your spam folder too.
        </p>
        <Button variant="outline" className="w-full" onClick={onBack}>
          Back to sign in
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field id={`${id}-email`} label="Email">
        <Input id={`${id}-email`} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={Boolean(error) || undefined} />
      </Field>
      {error && (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" className="w-full" disabled={!email || state === "sending"}>
        {state === "sending" && <Loader2 className="animate-spin" />}
        Send reset link
      </Button>
      <button type="button" className="focus-ring mx-auto block rounded text-sm font-medium text-primary hover:underline" onClick={onBack}>
        Back to sign in
      </button>
    </form>
  );
}

/** Google's brand mark, required by its sign-in branding guidelines. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.9z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.9z" />
    </svg>
  );
}
