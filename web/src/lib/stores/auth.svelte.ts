/**
 * Authentication store for managing user session (Svelte 5 runes).
 */

import {
  type User,
  fetchCurrentUser,
  getStoredToken,
  setStoredToken,
  clearStoredToken,
} from "$lib/api";

class AuthStore {
  user = $state<User | null>(null);
  token = $state<string | null>(null);
  loading = $state(true);
  initialized = $state(false);

  isLoggedIn = $derived(this.user !== null);

  /**
   * Initialize auth state from stored token.
   * Call this on app startup.
   */
  async init(): Promise<void> {
    const token = getStoredToken();

    if (!token) {
      this.user = null;
      this.token = null;
      this.loading = false;
      this.initialized = true;
      return;
    }

    this.token = token;
    this.loading = true;

    const user = await fetchCurrentUser();

    if (user) {
      this.user = user;
      this.token = token;
      this.loading = false;
      this.initialized = true;
    } else {
      // Token was invalid
      clearStoredToken();
      this.user = null;
      this.token = null;
      this.loading = false;
      this.initialized = true;
    }
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
}

export const auth = new AuthStore();
