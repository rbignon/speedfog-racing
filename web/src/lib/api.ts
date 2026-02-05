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

export type ParticipantStatus =
  | "registered"
  | "ready"
  | "playing"
  | "finished"
  | "abandoned";

export interface Participant {
  id: string;
  user: User;
  status: ParticipantStatus;
  current_layer: number;
  igt_ms: number;
  death_count: number;
}

export interface RaceDetail extends Race {
  seed_total_layers: number | null;
  participants: Participant[];
}

export interface PoolStats {
  [poolName: string]: {
    available: number;
    consumed: number;
  };
}

export interface DownloadInfo {
  participant_id: string;
  twitch_username: string;
  url: string;
}

export interface GenerateZipsResponse {
  downloads: DownloadInfo[];
}

export interface AddParticipantResponse {
  participant: Participant | null;
  invite: {
    token: string;
    twitch_username: string;
    race_id: string;
  } | null;
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
 * Redirects to /auth/callback after successful authentication.
 */
export function getTwitchLoginUrl(): string {
  const callbackUrl = `${window.location.origin}/auth/callback`;
  return `${API_BASE}/auth/twitch?redirect_url=${encodeURIComponent(callbackUrl)}`;
}

/**
 * Fetch a single race with full details.
 */
export async function fetchRace(id: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${id}`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}

/**
 * Fetch pool statistics (available/consumed seeds per pool).
 */
export async function fetchPoolStats(): Promise<PoolStats> {
  const response = await fetch(`${API_BASE}/pools`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<PoolStats>(response);
}

/**
 * Create a new race.
 */
export async function createRace(
  name: string,
  poolName: string = "standard",
): Promise<Race> {
  const response = await fetch(`${API_BASE}/races`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name, pool_name: poolName }),
  });
  return handleResponse<Race>(response);
}

/**
 * Add a participant to a race by Twitch username.
 */
export async function addParticipant(
  raceId: string,
  twitchUsername: string,
): Promise<AddParticipantResponse> {
  const response = await fetch(`${API_BASE}/races/${raceId}/participants`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ twitch_username: twitchUsername }),
  });
  return handleResponse<AddParticipantResponse>(response);
}

/**
 * Remove a participant from a race.
 */
export async function removeParticipant(
  raceId: string,
  participantId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/races/${raceId}/participants/${participantId}`,
    {
      method: "DELETE",
      headers: getAuthHeaders(),
    },
  );
  if (!response.ok) {
    const error: ApiError = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail);
  }
}

/**
 * Generate zips for all participants in a race.
 */
export async function generateZips(
  raceId: string,
): Promise<GenerateZipsResponse> {
  const response = await fetch(`${API_BASE}/races/${raceId}/generate-zips`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<GenerateZipsResponse>(response);
}

/**
 * Start a race with a scheduled start time.
 */
export async function startRace(
  raceId: string,
  scheduledStart: Date,
): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/start`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ scheduled_start: scheduledStart.toISOString() }),
  });
  return handleResponse<Race>(response);
}
