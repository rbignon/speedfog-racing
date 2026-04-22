/**
 * Authentication store for managing user session (Svelte 5 runes).
 */

import {
  type AuthUser,
  fetchCurrentUser,
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  getStoredUser,
  setStoredUser,
} from "$lib/api";

// Read cached session synchronously at module init (before hydration).
// During SSR these return null (localStorage guard).
const _cachedToken = getStoredToken();
const _cachedUser = _cachedToken ? getStoredUser() : null;

class AuthStore {
  user = $state<AuthUser | null>(_cachedUser);
  token = $state<string | null>(_cachedToken);
  loading = $state(_cachedToken !== null && _cachedUser === null);
  initialized = $state(false);

  isLoggedIn = $derived(this.user !== null);
  isAdmin = $derived(this.user?.role === "admin");
  canCreateRace = $derived(
    this.user?.role === "admin" || this.user?.role === "organizer",
  );

  /**
   * Initialize auth state. Cached user is already loaded from localStorage
   * at module init. This validates the token with the API and refreshes.
   */
  async init(): Promise<void> {
    if (!this.token) {
      this.loading = false;
      this.initialized = true;
      return;
    }

    // Validate token and refresh user data.
    // Network errors keep the cached session; only a 401 clears it.
    try {
      const user = await fetchCurrentUser();

      if (user) {
        this.user = user;
        setStoredUser(user);
      } else {
        // 401 or no token: session is invalid
        clearStoredToken();
        this.user = null;
        this.token = null;
      }
    } catch {
      // Network error: keep cached user, will revalidate next load
    }

    this.loading = false;
    this.initialized = true;
  }

  /**
   * Login with a token (called after OAuth callback).
   */
  async login(token: string): Promise<boolean> {
    setStoredToken(token);
    this.token = token;
    this.loading = true;

    const user = await fetchCurrentUser();

    if (user) {
      this.user = user;
      this.token = token;
      setStoredUser(user);
      this.loading = false;
      this.initialized = true;
      return true;
    } else {
      clearStoredToken();
      this.user = null;
      this.token = null;
      this.loading = false;
      this.initialized = true;
      return false;
    }
  }

  /**
   * Logout and clear session.
   */
  logout(): void {
    clearStoredToken();
    this.user = null;
    this.token = null;
    this.loading = false;
    this.initialized = true;
  }

  /**
   * Mark the current user locally as having been prompted for feedback.
   * Idempotent: only updates if not already set.
   */
  markFeedbackPrompted(): void {
    if (this.user && this.user.feedback_prompted_at === null) {
      this.user = {
        ...this.user,
        feedback_prompted_at: new Date().toISOString(),
      };
      setStoredUser(this.user);
    }
  }
}

export const auth = new AuthStore();
