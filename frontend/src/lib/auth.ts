import { type FirebaseError, initializeApp } from "firebase/app";
import {
  type Auth,
  EmailAuthProvider,
  GoogleAuthProvider,
  type User,
  createUserWithEmailAndPassword,
  getAuth,
  linkWithCredential,
  linkWithPopup,
  onIdTokenChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInAnonymously,
  signInWithCredential,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  updateProfile,
} from "firebase/auth";
import { api, setTokenProvider } from "@/api/client";
import { useAppStore } from "@/store/useAppStore";
import { type AuthUser, useAuthStore } from "@/store/useAuthStore";

const env = import.meta.env;
const config = {
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  appId: env.VITE_FIREBASE_APP_ID,
};

/** Accounts are on when the Firebase web config is present (see frontend/.env.example). */
export const authEnabled = Boolean(config.apiKey && config.projectId && config.authDomain);

let auth: Auth | null = null;
if (authEnabled) {
  auth = getAuth(initializeApp(config));
  setTokenProvider(async () => (auth?.currentUser ? auth.currentUser.getIdToken() : null));
}

const LOCAL_USER: AuthUser = {
  uid: "local",
  isGuest: false,
  pendingVerification: false,
  email: null,
  emailVerified: true,
  name: null,
  photoURL: null,
};

function toAuthUser(user: User): AuthUser {
  const usesPassword = user.providerData.some((p) => p.providerId === "password");
  return {
    uid: user.uid,
    isGuest: user.isAnonymous,
    // Google vouches for its addresses; email/password accounts must click the emailed link.
    pendingVerification: !user.isAnonymous && usesPassword && !user.emailVerified,
    email: user.email,
    emailVerified: user.emailVerified,
    name: user.displayName,
    photoURL: user.photoURL,
  };
}

function adopt(user: AuthUser) {
  useAppStore.getState().adoptUser(user.uid, user.isGuest);
  const store = useAuthStore.getState();
  store.setUser(user);
  store.setStatus("ready");
  void refreshTrials();
}

/** Start listening for the Firebase session; visitors get an anonymous guest account. */
export function initAuth(): () => void {
  if (!auth) {
    adopt(LOCAL_USER);
    return () => {};
  }
  const a = auth;
  const unsubscribe = onIdTokenChanged(a, async (user) => {
    if (user) {
      adopt(toAuthUser(user));
      return;
    }
    try {
      await signInAnonymously(a);
    } catch (err) {
      useAuthStore.getState().setStatus("error", authErrorMessage(err));
    }
  });
  // Coming back from the verification email (another tab or app): pick up the new status.
  const onReturn = () => {
    if (document.visibilityState === "visible" && useAuthStore.getState().user?.pendingVerification) {
      void checkVerification();
    }
  };
  window.addEventListener("focus", onReturn);
  document.addEventListener("visibilitychange", onReturn);
  return () => {
    unsubscribe();
    window.removeEventListener("focus", onReturn);
    document.removeEventListener("visibilitychange", onReturn);
  };
}

export async function refreshTrials() {
  try {
    const me = await api.me();
    useAuthStore
      .getState()
      .setTrials(me.trials_remaining != null ? { remaining: me.trials_remaining, limit: me.trials_limit ?? 0 } : null);
  } catch {
    /* the chat endpoint enforces the limit anyway */
  }
}

/** After linking a guest to a real login, the old token still says "anonymous": refresh it. */
async function finishUpgrade(user: User) {
  await user.getIdToken(true);
  adopt(toAuthUser(user));
}

/** Move a guest's documents to the account they just signed in to, then reload the list. */
async function claimGuestDocuments(guestToken: string | null) {
  if (!guestToken) return;
  try {
    await api.claim(guestToken);
  } catch {
    /* nothing to move, or the guest session expired */
  }
  useAppStore.getState().setDocuments(await api.listDocuments());
}

async function currentGuestToken(): Promise<string | null> {
  const user = auth?.currentUser;
  return user?.isAnonymous ? user.getIdToken() : null;
}

function requireAuth(): Auth {
  if (!auth) throw new Error("Accounts are not configured.");
  return auth;
}

/** The emailed link opens Firebase's confirmation page, which then links back to this app. */
async function sendVerificationLink(user: User) {
  try {
    await sendEmailVerification(user, { url: window.location.origin });
  } catch (err) {
    // The app's domain isn't in Firebase's authorized list: send the link without the way back.
    if ((err as FirebaseError).code !== "auth/unauthorized-continue-uri") throw err;
    await sendEmailVerification(user);
  }
}

/**
 * Create an email/password account and email a verification link. The account keeps guest
 * limits until the link is clicked; the dialog then shows the "check your inbox" step.
 */
export async function signUpWithEmail(name: string, email: string, password: string) {
  const a = requireAuth();
  const credential = EmailAuthProvider.credential(email, password);
  // Linking keeps the guest's uid, so their documents and chats stay with the new account.
  const user = a.currentUser?.isAnonymous
    ? (await linkWithCredential(a.currentUser, credential)).user
    : (await createUserWithEmailAndPassword(a, email, password)).user;
  if (name.trim()) await updateProfile(user, { displayName: name.trim() });
  await finishUpgrade(user);
  await sendVerificationLink(user);
}

/** Returns false when the account still has to verify its email. */
export async function signInWithEmail(email: string, password: string): Promise<boolean> {
  const a = requireAuth();
  const guestToken = await currentGuestToken();
  const { user } = await signInWithEmailAndPassword(a, email, password);
  await claimGuestDocuments(guestToken);
  return user.emailVerified;
}

export async function resendVerification() {
  const user = requireAuth().currentUser;
  if (user) await sendVerificationLink(user);
}

/** Reload the account from Firebase; once verified, refresh the token so the backend sees it. */
export async function checkVerification(): Promise<boolean> {
  const user = auth?.currentUser;
  if (!user) return false;
  await user.reload();
  if (!user.emailVerified) return false;
  await finishUpgrade(user);
  return true;
}

export async function continueWithGoogle() {
  const a = requireAuth();
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const current = a.currentUser;
  if (!current?.isAnonymous) {
    await signInWithPopup(a, provider);
    return;
  }
  try {
    await finishUpgrade((await linkWithPopup(current, provider)).user);
  } catch (err) {
    // This Google account already has an AskMyPDF account: sign in to it instead.
    if ((err as FirebaseError).code !== "auth/credential-already-in-use") throw err;
    const credential = GoogleAuthProvider.credentialFromError(err as FirebaseError);
    if (!credential) throw err;
    const guestToken = await current.getIdToken();
    await signInWithCredential(a, credential);
    await claimGuestDocuments(guestToken);
  }
}

export async function resetPassword(email: string) {
  await sendPasswordResetEmail(requireAuth(), email);
}

export async function signOut() {
  if (auth) await firebaseSignOut(auth); // the listener then starts a fresh guest session
}

const MESSAGES: Record<string, string> = {
  "auth/email-already-in-use": "An account with this email already exists. Sign in instead.",
  "auth/credential-already-in-use": "This login is already linked to another account. Sign in instead.",
  "auth/invalid-credential": "Email or password is incorrect.",
  "auth/invalid-login-credentials": "Email or password is incorrect.",
  "auth/wrong-password": "Email or password is incorrect.",
  "auth/user-not-found": "No account uses this email. Create one instead.",
  "auth/invalid-email": "Enter a valid email address.",
  "auth/missing-password": "Enter your password.",
  "auth/weak-password": "Use at least 6 characters for your password.",
  "auth/too-many-requests": "Too many attempts. Wait a minute and try again.",
  "auth/network-request-failed": "Network error. Check your connection and try again.",
  "auth/popup-blocked": "Your browser blocked the sign-in window. Allow pop-ups for this site and try again.",
  "auth/operation-not-allowed": "This sign-in method is not enabled in Firebase yet.",
  "auth/admin-restricted-operation": "Guest access is not enabled in Firebase yet (Authentication > Sign-in method > Anonymous).",
  "auth/unauthorized-domain": "This website's domain is not authorized in Firebase (Authentication > Settings > Authorized domains).",
};

/** Plain-language message for a Firebase error. */
export function authErrorMessage(err: unknown): string {
  const code = (err as FirebaseError)?.code ?? "";
  return MESSAGES[code] ?? (err as Error)?.message ?? "Sign-in failed. Please try again.";
}

export function isPopupDismissed(err: unknown): boolean {
  const code = (err as FirebaseError)?.code;
  return code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request";
}
