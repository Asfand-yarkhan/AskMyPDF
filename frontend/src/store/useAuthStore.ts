import { create } from "zustand";

export interface AuthUser {
  uid: string;
  /** Anonymous session: has not signed up. */
  isGuest: boolean;
  /** Signed up with email/password but hasn't clicked the verification link yet. */
  pendingVerification: boolean;
  email: string | null;
  emailVerified: boolean;
  name: string | null;
  photoURL: string | null;
}

/** Why the account dialog opened; changes its headline. */
export type AuthReason = "trial" | "upload" | "manual";
export type AuthMode = "signup" | "signin" | "reset" | "verify";

export interface Trials {
  remaining: number;
  limit: number;
}

interface AuthState {
  /** "ready" once there is a user (guest or member), or always when accounts are off. */
  status: "loading" | "ready" | "error";
  error: string | null;
  user: AuthUser | null;
  /** Free AI requests left for a guest; null for members or before /me answers. */
  trials: Trials | null;
  dialog: { open: boolean; reason: AuthReason; mode: AuthMode };

  setUser: (user: AuthUser | null) => void;
  setStatus: (status: AuthState["status"], error?: string | null) => void;
  setTrials: (trials: Trials | null) => void;
  openDialog: (reason?: AuthReason, mode?: AuthMode) => void;
  setMode: (mode: AuthMode) => void;
  closeDialog: () => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  status: "loading",
  error: null,
  user: null,
  trials: null,
  dialog: { open: false, reason: "manual", mode: "signup" },

  setUser: (user) => set({ user }),
  setStatus: (status, error = null) => set({ status, error }),
  setTrials: (trials) => set({ trials }),
  openDialog: (reason = "manual", mode = "signup") => set({ dialog: { open: true, reason, mode } }),
  setMode: (mode) => set((s) => ({ dialog: { ...s.dialog, mode } })),
  closeDialog: () => set((s) => ({ dialog: { ...s.dialog, open: false } })),
}));

/** Guests and unverified accounts have the free-trial limit; verified members don't. */
export const isLimited = (user: AuthUser | null) => Boolean(user && (user.isGuest || user.pendingVerification));

/** Used every free request: guests must sign up, unverified accounts must click the link. */
export const useTrialsExhausted = () =>
  useAuthStore((s) => Boolean(isLimited(s.user) && s.trials && s.trials.remaining <= 0));

/** Open the dialog step that lifts the limit for this user. */
export function promptToUnlock(reason: AuthReason) {
  const { user, openDialog } = useAuthStore.getState();
  openDialog(reason, user?.pendingVerification ? "verify" : "signup");
}
