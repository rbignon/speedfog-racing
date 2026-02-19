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

export interface AuthUser extends User {
  role: string;
  locale: string | null;
}

export type RaceStatus = "setup" | "running" | "finished";

export interface Race {
  id: string;
  name: string;
  organizer: User;
  status: RaceStatus;
  pool_name: string | null;
  is_public: boolean;
  created_at: string;
  scheduled_at: string | null;
  started_at: string | null;
  seeds_released_at: string | null;
  participant_count: number;
  participant_previews: User[];
  casters: Caster[];
  seed_total_layers?: number | null;
  my_current_layer?: number | null;
  my_igt_ms?: number | null;
  my_death_count?: number | null;
}

export interface RaceListResponse {
  races: Race[];
  total?: number | null;
  has_more?: boolean | null;
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
}

export interface Caster {
  id: string;
  user: User;
}

export interface PoolConfig {
  type: string | null;
  estimated_duration: string | null;
  description: string | null;
  legacy_dungeons: number | null;
  min_layers: number | null;
  max_layers: number | null;
  final_tier: number | null;
  starting_items: string[] | null;
  care_package: boolean | null;
  weapon_upgrade: number | null;
  care_package_items: string[] | null;
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
  seed_number: string | null;
  seed_total_layers: number | null;
  seed_total_nodes: number | null;
  seed_total_paths: number | null;
  participants: Participant[];
  pending_invites: PendingInvite[];
  pool_config: PoolConfig | null;
}

export interface PoolInfo {
  available: number;
  consumed: number;
  discarded: number;
  played_by_user: number | null;
  pool_config: PoolConfig | null;
}

export type PoolStats = Record<string, PoolInfo>;

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
 * Fetch list of races with pagination support.
 */
export async function fetchRacesPaginated(
  status: string,
  offset: number,
  limit: number,
): Promise<RaceListResponse> {
  const params = new URLSearchParams({
    status,
    offset: String(offset),
    limit: String(limit),
  });
  const response = await fetch(`${API_BASE}/races?${params}`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceListResponse>(response);
}

/**
 * Fetch current authenticated user.
 * Returns null if not authenticated or token is invalid.
 */
export async function fetchCurrentUser(): Promise<AuthUser | null> {
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

    return await handleResponse<AuthUser>(response);
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
  const lang =
    typeof navigator !== "undefined" ? navigator.language?.split("-")[0] : "en";
  return `${API_BASE}/auth/twitch?redirect_url=${encodeURIComponent(callbackUrl)}&locale=${encodeURIComponent(lang || "en")}`;
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
  const response = await fetch(`${API_BASE}/pools?type=race`, {
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
  scheduledAt: string | null = null,
  isPublic: boolean = true,
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
      scheduled_at: scheduledAt,
      is_public: isPublic,
    }),
  });
  return handleResponse<Race>(response);
}

/**
 * Update race properties (PATCH). Organizer only.
 */
export async function updateRace(
  raceId: string,
  data: { scheduled_at?: string | null; is_public?: boolean },
): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}`, {
    method: "PATCH",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
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
 * Re-roll the seed for a SETUP race.
 */
export async function rerollSeed(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/reroll-seed`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}

/**
 * Release seeds for a SETUP race. Organizer only.
 */
export async function releaseSeeds(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/release-seeds`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}

/**
 * Reset a race back to SETUP status, clearing all participant progress.
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

/**
 * Fetch a user's public profile by Twitch username.
 */
export async function fetchUserProfile(username: string): Promise<UserProfile> {
  const response = await fetch(
    `${API_BASE}/users/${encodeURIComponent(username)}`,
  );
  if (!response.ok)
    throw new Error(`Failed to fetch profile: ${response.status}`);
  return response.json();
}

/**
 * Fetch a user's activity timeline.
 */
export async function fetchUserActivity(
  username: string,
  offset = 0,
  limit = 20,
): Promise<ActivityTimeline> {
  const response = await fetch(
    `${API_BASE}/users/${encodeURIComponent(username)}/activity?offset=${offset}&limit=${limit}`,
  );
  if (!response.ok)
    throw new Error(`Failed to fetch activity: ${response.status}`);
  return response.json();
}

// =============================================================================
// i18n / Locale API
// =============================================================================

export interface LocaleInfo {
  code: string;
  name: string;
}

/**
 * Fetch available locales (public, no auth).
 */
export async function fetchLocales(): Promise<LocaleInfo[]> {
  const response = await fetch(`${API_BASE}/i18n/locales`);
  return handleResponse<LocaleInfo[]>(response);
}

/**
 * Update the current user's locale preference.
 */
export async function updateLocale(
  locale: string,
): Promise<{ locale: string }> {
  const response = await fetch(`${API_BASE}/users/me/locale`, {
    method: "PATCH",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ locale }),
  });
  return handleResponse<{ locale: string }>(response);
}

/**
 * Detect locale from browser language, mapped to available locale codes.
 * Returns "en" if no match.
 */
export function detectBrowserLocale(availableLocales: LocaleInfo[]): string {
  if (typeof navigator === "undefined") return "en";
  const lang = navigator.language?.split("-")[0];
  if (!lang) return "en";
  const codes = new Set(availableLocales.map((l) => l.code));
  return codes.has(lang) ? lang : "en";
}

// =============================================================================
// Admin API
// =============================================================================

export interface AdminUser {
  id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  role: string;
  created_at: string;
  last_seen: string | null;
  training_count: number;
  race_count: number;
}

// User profile
export interface BestRecentPlacement {
  placement: number;
  race_name: string;
  race_id: string;
  finished_at: string | null;
}

export interface UserStats {
  race_count: number;
  training_count: number;
  podium_count: number;
  first_place_count: number;
  organized_count: number;
  casted_count: number;
  podium_rate: number | null;
  best_recent_placement: BestRecentPlacement | null;
}

export interface UserProfile {
  id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  role: string;
  created_at: string;
  stats: UserStats;
}

export type ActivityType =
  | "race_participant"
  | "race_organizer"
  | "race_caster"
  | "training";

export interface ActivityItemBase {
  type: ActivityType;
  date: string;
  user?: User;
}

export interface RaceParticipantActivity extends ActivityItemBase {
  type: "race_participant";
  race_id: string;
  race_name: string;
  status: string;
  placement: number | null;
  total_participants: number;
  igt_ms: number;
  death_count: number;
}

export interface RaceOrganizerActivity extends ActivityItemBase {
  type: "race_organizer";
  race_id: string;
  race_name: string;
  status: string;
  participant_count: number;
}

export interface RaceCasterActivity extends ActivityItemBase {
  type: "race_caster";
  race_id: string;
  race_name: string;
  status: string;
}

export interface TrainingActivityItem extends ActivityItemBase {
  type: "training";
  session_id: string;
  pool_name: string;
  status: string;
  igt_ms: number;
  death_count: number;
}

export type ActivityItem =
  | RaceParticipantActivity
  | RaceOrganizerActivity
  | RaceCasterActivity
  | TrainingActivityItem;

export interface ActivityTimeline {
  items: ActivityItem[];
  total: number;
  has_more: boolean;
}

/**
 * Fetch all users (admin only).
 */
export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const response = await fetch(`${API_BASE}/admin/users`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<AdminUser[]>(response);
}

/**
 * Update a user's role (admin only).
 */
export async function updateAdminUserRole(
  userId: string,
  role: string,
): Promise<AdminUser> {
  const response = await fetch(`${API_BASE}/admin/users/${userId}`, {
    method: "PATCH",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ role }),
  });
  return handleResponse<AdminUser>(response);
}

export interface AdminPoolStats {
  pools: Record<
    string,
    { available: number; consumed: number; discarded: number }
  >;
}

/**
 * Fetch seed pool statistics (admin only).
 */
export async function fetchAdminSeedStats(): Promise<AdminPoolStats> {
  const response = await fetch(`${API_BASE}/admin/seeds/stats`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<AdminPoolStats>(response);
}

/**
 * Discard all available seeds in a pool (admin only).
 */
export async function adminDiscardPool(
  poolName: string,
): Promise<{ discarded: number; pool_name: string }> {
  const response = await fetch(`${API_BASE}/admin/seeds/discard`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ pool_name: poolName }),
  });
  return handleResponse<{ discarded: number; pool_name: string }>(response);
}

/**
 * Scan a seed pool directory (admin only).
 */
export async function adminScanPool(
  poolName: string,
): Promise<{ added: number; pool_name: string }> {
  const response = await fetch(`${API_BASE}/admin/seeds/scan`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ pool_name: poolName }),
  });
  return handleResponse<{ added: number; pool_name: string }>(response);
}

/**
 * Fetch global activity feed (admin only).
 */
export async function fetchAdminActivity(
  offset = 0,
  limit = 20,
): Promise<ActivityTimeline> {
  const response = await fetch(
    `${API_BASE}/admin/activity?offset=${offset}&limit=${limit}`,
    { headers: getAuthHeaders() },
  );
  return handleResponse<ActivityTimeline>(response);
}

// =============================================================================
// Training API
// =============================================================================

export interface TrainingSession {
  id: string;
  user: User;
  status: "active" | "finished" | "abandoned";
  pool_name: string;
  igt_ms: number;
  death_count: number;
  created_at: string;
  finished_at: string | null;
  seed_total_layers: number | null;
  seed_total_nodes: number | null;
  current_layer: number;
}

export interface TrainingSessionDetail extends TrainingSession {
  seed_number: string | null;
  seed_total_paths: number | null;
  progress_nodes: Array<{ node_id: string; igt_ms: number }> | null;
  graph_json: Record<string, unknown> | null;
  pool_config: PoolConfig | null;
}

export async function fetchTrainingPools(): Promise<PoolStats> {
  const response = await fetch(`${API_BASE}/pools?type=training`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<PoolStats>(response);
}

export async function createTrainingSession(
  poolName: string,
): Promise<TrainingSessionDetail> {
  const response = await fetch(`${API_BASE}/training`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ pool_name: poolName }),
  });
  return handleResponse<TrainingSessionDetail>(response);
}

export async function fetchTrainingSessions(): Promise<TrainingSession[]> {
  const response = await fetch(`${API_BASE}/training`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<TrainingSession[]>(response);
}

export async function fetchTrainingSession(
  id: string,
): Promise<TrainingSessionDetail> {
  const response = await fetch(`${API_BASE}/training/${id}`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<TrainingSessionDetail>(response);
}

export async function abandonTrainingSession(
  id: string,
): Promise<TrainingSessionDetail> {
  const response = await fetch(`${API_BASE}/training/${id}/abandon`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<TrainingSessionDetail>(response);
}

export async function downloadTrainingPack(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/training/${sessionId}/pack`, {
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
  const disposition = response.headers.get("content-disposition");
  const match = disposition?.match(/filename="?([^"]+)"?/);
  a.download = match?.[1] ?? `speedfog_training_${sessionId}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
