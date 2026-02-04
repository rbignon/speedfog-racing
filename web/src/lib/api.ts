/**
 * REST API client for SpeedFog Racing backend.
 */

const API_BASE = "/api";

// =============================================================================
// Types (matching backend schemas)
// =============================================================================

export interface User {
  id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
}

export type RaceStatus =
  | "draft"
  | "open"
  | "countdown"
  | "running"
  | "finished";

export interface Race {
  id: string;
  name: string;
  organizer: User;
  status: RaceStatus;
  pool_name: string | null;
  scheduled_start: string | null;
  created_at: string;
  participant_count: number;
}

export interface RaceListResponse {
  races: Race[];
}

export interface ApiError {
  detail: string;
}

// =============================================================================
// Token management
// =============================================================================

const TOKEN_KEY = "speedfog_token";

export function getStoredToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof localStorage === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

// =============================================================================
// HTTP helpers
// =============================================================================

function getAuthHeaders(): HeadersInit {
  const token = getStoredToken();
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error: ApiError = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail);
  }
  return response.json();
}

// =============================================================================
// API functions
// =============================================================================

/**
 * Fetch list of races, optionally filtered by status.
 */
export async function fetchRaces(status?: string): Promise<Race[]> {
  const url = status
    ? `${API_BASE}/races?status=${encodeURIComponent(status)}`
    : `${API_BASE}/races`;

  const response = await fetch(url, {
    headers: getAuthHeaders(),
  });

  const data = await handleResponse<RaceListResponse>(response);
  return data.races;
}

/**
 * Fetch current authenticated user.
 * Returns null if not authenticated or token is invalid.
 */
export async function fetchCurrentUser(): Promise<User | null> {
  const token = getStoredToken();
  if (!token) return null;

  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      headers: getAuthHeaders(),
    });

    if (response.status === 401) {
      clearStoredToken();
      return null;
    }

    return await handleResponse<User>(response);
  } catch {
    return null;
  }
}

/**
 * Get the Twitch OAuth login URL.
 */
export function getTwitchLoginUrl(): string {
  return `${API_BASE}/auth/twitch`;
}
