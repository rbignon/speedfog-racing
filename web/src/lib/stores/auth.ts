/**
 * Authentication store for managing user session.
 */

import { writable, derived } from "svelte/store";
import {
  type User,
  fetchCurrentUser,
  getStoredToken,
  setStoredToken,
  clearStoredToken,
} from "$lib/api";

// =============================================================================
// Types
// =============================================================================

interface AuthState {
  user: User | null;
  token: string | null;
  loading: boolean;
  initialized: boolean;
}

// =============================================================================
// Store
// =============================================================================

const initialState: AuthState = {
  user: null,
  token: null,
  loading: true,
  initialized: false,
};

export const auth = writable<AuthState>(initialState);

// Derived stores for convenience
export const currentUser = derived(auth, ($auth) => $auth.user);
export const isLoggedIn = derived(auth, ($auth) => $auth.user !== null);
export const isLoading = derived(auth, ($auth) => $auth.loading);
export const isInitialized = derived(auth, ($auth) => $auth.initialized);

// =============================================================================
// Actions
// =============================================================================

/**
 * Initialize auth state from stored token.
 * Call this on app startup.
 */
export async function initAuth(): Promise<void> {
  const token = getStoredToken();

  if (!token) {
    auth.set({
      user: null,
      token: null,
      loading: false,
      initialized: true,
    });
    return;
  }

  auth.update((state) => ({ ...state, token, loading: true }));

  const user = await fetchCurrentUser();

  if (user) {
    auth.set({
      user,
      token,
      loading: false,
      initialized: true,
    });
  } else {
    // Token was invalid
    clearStoredToken();
    auth.set({
      user: null,
      token: null,
      loading: false,
      initialized: true,
    });
  }
}

/**
 * Login with a token (called after OAuth callback).
 */
export async function login(token: string): Promise<boolean> {
  setStoredToken(token);
  auth.update((state) => ({ ...state, token, loading: true }));

  const user = await fetchCurrentUser();

  if (user) {
    auth.set({
      user,
      token,
      loading: false,
      initialized: true,
    });
    return true;
  } else {
    clearStoredToken();
    auth.set({
      user: null,
      token: null,
      loading: false,
      initialized: true,
    });
    return false;
  }
}

/**
 * Logout and clear session.
 */
export function logout(): void {
  clearStoredToken();
  auth.set({
    user: null,
    token: null,
    loading: false,
    initialized: true,
  });
}
