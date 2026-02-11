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

export type RaceStatus = "draft" | "open" | "running" | "finished";

export interface Race {
  id: string;
  name: string;
  organizer: User;
  status: RaceStatus;
  pool_name: string | null;
  created_at: string;
  started_at: string | null;
  participant_count: number;
  participant_previews: User[];
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
  color_index: number;
  has_seed_pack: boolean;
}

export interface Caster {
  id: string;
  user: User;
}

export interface PoolConfig {
  estimated_duration: string | null;
  description: string | null;
  legacy_dungeons: number | null;
  min_layers: number | null;
  max_layers: number | null;
  final_tier: number | null;
  starting_items: string[] | null;
  care_package: boolean | null;
  weapon_upgrade: number | null;
  items_randomized: boolean | null;
  auto_upgrade_weapons: boolean | null;
  remove_requirements: boolean | null;
}

export interface PendingInvite {
  id: string;
  twitch_username: string;
  created_at: string;
  token: string | null;
}

export interface RaceDetail extends Race {
  seed_total_layers: number | null;
  participants: Participant[];
  casters: Caster[];
  pending_invites: PendingInvite[];
  pool_config: PoolConfig | null;
}

export interface PoolInfo {
  available: number;
  consumed: number;
  pool_config: PoolConfig | null;
}

export type PoolStats = Record<string, PoolInfo>;

export interface DownloadInfo {
  participant_id: string;
  twitch_username: string;
  url: string;
}

export interface GenerateSeedPacksResponse {
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
// Site config
// =============================================================================

export interface SiteConfig {
  coming_soon: boolean;
}

export async function fetchSiteConfig(): Promise<SiteConfig> {
  const response = await fetch(`${API_BASE}/site-config`);
  return handleResponse<SiteConfig>(response);
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
 * Exchange an ephemeral auth code for an API token.
 * Called after the OAuth redirect with ?code=... in the URL.
 */
export async function exchangeAuthCode(code: string): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  const data = await handleResponse<{ token: string }>(response);
  return data.token;
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
  organizerParticipates: boolean = false,
  config: Record<string, unknown> = {},
): Promise<Race> {
  const response = await fetch(`${API_BASE}/races`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name,
      pool_name: poolName,
      organizer_participates: organizerParticipates,
      config,
    }),
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
 * Generate seed packs for all participants in a race.
 */
export async function generateSeedPacks(
  raceId: string,
): Promise<GenerateSeedPacksResponse> {
  const response = await fetch(
    `${API_BASE}/races/${raceId}/generate-seed-packs`,
    {
      method: "POST",
      headers: getAuthHeaders(),
    },
  );
  return handleResponse<GenerateSeedPacksResponse>(response);
}

/**
 * Start a race immediately.
 */
export async function startRace(raceId: string): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/start`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<Race>(response);
}

/**
 * Transition a race from DRAFT to OPEN.
 */
export async function openRace(raceId: string): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/open`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<Race>(response);
}

/**
 * Reset a race back to OPEN status, clearing all participant progress.
 */
export async function resetRace(raceId: string): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/reset`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<Race>(response);
}

/**
 * Force finish a running race.
 */
export async function finishRace(raceId: string): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/finish`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<Race>(response);
}

/**
 * Delete a race and all associated data.
 */
export async function deleteRace(raceId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/races/${raceId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail);
  }
}

// =============================================================================
// Invite API
// =============================================================================

export interface InviteInfo {
  token: string;
  race_name: string;
  organizer_name: string;
  race_status: RaceStatus;
  twitch_username: string;
}

export interface AcceptInviteResponse {
  participant: Participant;
  race_id: string;
}

/**
 * Get public information about an invite.
 */
export async function getInvite(token: string): Promise<InviteInfo> {
  const response = await fetch(`${API_BASE}/invite/${token}`);
  return handleResponse<InviteInfo>(response);
}

/**
 * Accept an invite and become a participant.
 */
export async function acceptInvite(
  token: string,
): Promise<AcceptInviteResponse> {
  const response = await fetch(`${API_BASE}/invite/${token}/accept`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<AcceptInviteResponse>(response);
}

/**
 * Revoke a pending invite.
 */
export async function deleteInvite(
  raceId: string,
  inviteId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/races/${raceId}/invites/${inviteId}`,
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

// =============================================================================
// Caster API
// =============================================================================

/**
 * Add a caster to a race by Twitch username.
 */
export async function addCaster(
  raceId: string,
  twitchUsername: string,
): Promise<Caster> {
  const response = await fetch(`${API_BASE}/races/${raceId}/casters`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ twitch_username: twitchUsername }),
  });
  return handleResponse<Caster>(response);
}

/**
 * Remove a caster from a race.
 */
export async function removeCaster(
  raceId: string,
  casterId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/races/${raceId}/casters/${casterId}`,
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

// =============================================================================
// User API
// =============================================================================

/**
 * Search users by Twitch username or display name (prefix match).
 */
export async function searchUsers(query: string): Promise<User[]> {
  const response = await fetch(
    `${API_BASE}/users/search?q=${encodeURIComponent(query)}`,
    { headers: getAuthHeaders() },
  );
  return handleResponse<User[]>(response);
}

/**
 * Fetch races where the current user is organizer or participant.
 */
export async function fetchMyRaces(): Promise<Race[]> {
  const response = await fetch(`${API_BASE}/users/me/races`, {
    headers: getAuthHeaders(),
  });
  const data = await handleResponse<RaceListResponse>(response);
  return data.races;
}

// =============================================================================
// Download helpers
// =============================================================================

/**
 * Download the authenticated user's seed pack via fetch + blob.
 * Triggers a browser download since the endpoint requires auth headers.
 */
export async function downloadMySeedPack(raceId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/races/${raceId}/my-seed-pack`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const error: ApiError = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  // Extract filename from content-disposition or use default
  const disposition = response.headers.get("content-disposition");
  const match = disposition?.match(/filename="?([^"]+)"?/);
  a.download = match?.[1] ?? `speedfog_race_${raceId}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
