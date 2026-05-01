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
  equipped_badge_id?: string | null;
  equipped_name_template_id?: string | null;
}

export interface ParticipantPreview extends User {
  placement: number | null;
  status: ParticipantStatus;
  igt_ms: number | null;
}

export interface AuthUser extends User {
  role: string;
  locale: string | null;
  overlay_settings: { font_size?: number } | null;
  feedback_prompted_at: string | null;
}

export type RaceStatus = "setup" | "running" | "finished";

export interface Race {
  id: string;
  name: string;
  organizer: User;
  status: RaceStatus;
  pool_name: string | null;
  is_public: boolean;
  open_registration: boolean;
  max_participants: number | null;
  created_at: string;
  scheduled_at: string | null;
  started_at: string | null;
  seeds_released_at: string | null;
  late_join_window_minutes: number | null;
  race_duration_minutes: number | null;
  registration_closes_at: string | null;
  race_ends_at: string | null;
  private_dag: boolean;
  daily_date: string | null;
  exclude_from_elo: boolean;
  participant_count: number;
  participant_previews: ParticipantPreview[];
  casters: Caster[];
  seed_total_layers?: number | null;
  my_participant_status?: ParticipantStatus | null;
  my_current_layer?: number | null;
  my_igt_ms?: number | null;
  my_death_count?: number | null;
  can_join: boolean;
  my_role: string | null;
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
  is_live: boolean;
  stream_url: string | null;
}

export interface PoolConfig {
  name: string | null;
  type: string | null;
  sort_order: number;
  estimated_duration: string | null;
  description: string | null;
  min_layers: number | null;
  max_layers: number | null;
  final_tier: number | null;
  starting_runes: number | null;
  starting_upgrades: string[] | null;
  starting_items: string[] | null;
  care_package: boolean | null;
  weapon_upgrade: number | null;
  care_package_items: string[] | null;
  items_randomized: boolean | null;
  auto_upgrade_weapons: boolean | null;
  remove_requirements: boolean | null;
  major_boss_ratio: string | null;
  randomize_bosses: string | null;
  difficulty_curve: string | null;
  nerf_gargoyles: boolean | null;
  nerf_malenia: boolean | null;
  allcraft: boolean | null;
  sentry_torch_shop: boolean | null;
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
const USER_KEY = "speedfog_user";

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
  localStorage.removeItem(USER_KEY);
}

export function getStoredUser(): AuthUser | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (
      !parsed ||
      typeof parsed.id !== "string" ||
      typeof parsed.twitch_username !== "string"
    ) {
      localStorage.removeItem(USER_KEY);
      return null;
    }
    return parsed as AuthUser;
  } catch {
    localStorage.removeItem(USER_KEY);
    return null;
  }
}

export function setStoredUser(user: AuthUser): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
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
 * Fetch open-registration races the current user can join.
 * Requires authentication.
 */
export async function fetchJoinableRaces(): Promise<Race[]> {
  const response = await fetch(`${API_BASE}/races/joinable`, {
    headers: getAuthHeaders(),
  });
  const data = await handleResponse<RaceListResponse>(response);
  return data.races;
}

export interface DailyPodiumEntry {
  placement: number;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  igt_ms: number;
}

export interface DailyMyResult {
  status: ParticipantStatus;
  placement: number | null;
  total_finishers: number;
  igt_ms: number | null;
  death_count: number;
}

export type DailyWeekDayState = "missing_past" | "past" | "today" | "future";

export interface DailyWeekDay {
  weekday: number;
  date: string;
  state: DailyWeekDayState;
  pool_name: string | null;
  pool_display_name: string | null;
  race_id: string | null;
  started_at: string | null;
  ends_at: string | null;
  finishers_count: number;
  participants_count: number;
  podium: DailyPodiumEntry[];
  my_result: DailyMyResult | null;
}

export interface DailyWeekResponse {
  week_start: string;
  today: string;
  days: DailyWeekDay[];
}

/**
 * Fetch the seven-cell weekly grid (Monday through Sunday in ISO order)
 * for the home page and dashboard.
 */
export async function fetchDailyWeek(
  customFetch: typeof fetch = fetch,
): Promise<DailyWeekResponse> {
  const response = await customFetch(`${API_BASE}/daily/week`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<DailyWeekResponse>(response);
}

/**
 * Fetch the running Daily Seed for the current UTC rotation day.
 * 404 when no daily is active.
 *
 * Returns the ``Race`` summary shape (with ``participant_previews`` and the
 * ``my_*`` fields scoped to the current user). Surfaces that need the full
 * detail (e.g. the dedicated daily page) call ``fetchDailyByDate`` instead.
 */
export async function fetchTodayDaily(
  customFetch: typeof fetch = fetch,
): Promise<Race> {
  const response = await customFetch(`${API_BASE}/daily/today`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<Race>(response);
}

/**
 * Fetch a Daily Seed by its rotation date (YYYY-MM-DD).
 */
export async function fetchDailyByDate(
  date: string,
  customFetch: typeof fetch = fetch,
): Promise<RaceDetail> {
  const response = await customFetch(`${API_BASE}/daily/${date}`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}

/**
 * Fetch the most recent past Daily Seeds (excluding today).
 */
export async function fetchRecentDailies(
  limit = 7,
  customFetch: typeof fetch = fetch,
): Promise<Race[]> {
  const response = await customFetch(
    `${API_BASE}/daily/recent?limit=${limit}`,
    {
      headers: getAuthHeaders(),
    },
  );
  const data = await handleResponse<RaceListResponse>(response);
  return data.races;
}

/**
 * Fetch current authenticated user.
 * Returns null if not authenticated or token is invalid.
 */
export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = getStoredToken();
  if (!token) return null;

  let url = `${API_BASE}/auth/me`;
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (tz) {
      url += `?timezone=${encodeURIComponent(tz)}`;
    }
  } catch {
    // Intl API unavailable, proceed without timezone
  }

  const response = await fetch(url, {
    headers: getAuthHeaders(),
  });

  if (response.status === 401) {
    clearStoredToken();
    return null;
  }

  return await handleResponse<AuthUser>(response);
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
  if (typeof window === "undefined") return "#";
  const callbackUrl = `${window.location.origin}/auth/callback`;
  const lang = navigator.language?.split("-")[0] || "en";
  return `${API_BASE}/auth/twitch?redirect_url=${encodeURIComponent(callbackUrl)}&locale=${encodeURIComponent(lang)}`;
}

/**
 * Fetch a single race with full details.
 */
export async function fetchRace(
  id: string,
  customFetch: typeof fetch = fetch,
): Promise<RaceDetail> {
  const response = await customFetch(`${API_BASE}/races/${id}`, {
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
  openRegistration: boolean = false,
  maxParticipants: number | null = null,
  lateJoinWindowMinutes: number | null = null,
  raceDurationMinutes: number | null = null,
  privateDag: boolean = false,
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
      open_registration: openRegistration,
      max_participants: maxParticipants,
      late_join_window_minutes: lateJoinWindowMinutes,
      race_duration_minutes: raceDurationMinutes,
      private_dag: privateDag,
    }),
  });
  return handleResponse<Race>(response);
}

/**
 * Update race properties (PATCH). Organizer only.
 */
export async function updateRace(
  raceId: string,
  data: {
    scheduled_at?: string | null;
    is_public?: boolean;
    open_registration?: boolean;
    max_participants?: number | null;
    late_join_window_minutes?: number | null;
    race_duration_minutes?: number | null;
    private_dag?: boolean;
  },
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
 * Self-register as a participant in an open-registration race.
 */
export async function joinRace(raceId: string): Promise<Participant> {
  const response = await fetch(`${API_BASE}/races/${raceId}/join`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<Participant>(response);
}

/**
 * Self-remove from a race during setup.
 */
export async function leaveRace(raceId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/races/${raceId}/leave`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    const error: ApiError = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail);
  }
}

/**
 * Self-register as a caster for a race.
 */
export async function castJoin(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/cast-join`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
}

/**
 * Self-remove as a caster from a race.
 */
export async function castLeave(raceId: string): Promise<RaceDetail> {
  const response = await fetch(`${API_BASE}/races/${raceId}/cast-leave`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<RaceDetail>(response);
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
 * Re-roll the seed for a SETUP race, optionally reporting it as buggy.
 */
export async function rerollSeed(
  raceId: string,
  reportBuggy?: boolean,
  reportReason?: string,
): Promise<RaceDetail> {
  const body =
    reportBuggy != null && reportBuggy
      ? { report_buggy: true, report_reason: reportReason || null }
      : undefined;
  const response = await fetch(`${API_BASE}/races/${raceId}/reroll-seed`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
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
 * Abandon a running race as a participant.
 */
export async function abandonRace(raceId: string): Promise<Race> {
  const response = await fetch(`${API_BASE}/races/${raceId}/abandon`, {
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
export async function getInvite(
  token: string,
  customFetch: typeof fetch = fetch,
): Promise<InviteInfo> {
  const response = await customFetch(`${API_BASE}/invite/${token}`);
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
    {
      headers: getAuthHeaders(),
    },
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

/**
 * Fetch per-pool aggregated stats for a user.
 */
export async function fetchUserPoolStats(
  username: string,
): Promise<UserPoolStats> {
  const response = await fetch(
    `${API_BASE}/users/${encodeURIComponent(username)}/pool-stats`,
  );
  if (!response.ok)
    throw new Error(`Failed to fetch pool stats: ${response.status}`);
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
 * Update the current user's overlay settings.
 */
export async function updateOverlaySettings(settings: {
  font_size?: number;
}): Promise<{ overlay_settings: { font_size?: number } }> {
  const response = await fetch(`${API_BASE}/users/me/settings`, {
    method: "PATCH",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(settings),
  });
  return handleResponse<{ overlay_settings: { font_size?: number } }>(response);
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
export interface UserStats {
  race_count: number;
  training_count: number;
  organized_count: number;
  casted_count: number;
}

export interface ProfileBadgeDto {
  id: string;
  name: string;
  icon_filename: string;
  description?: string | null;
}

export interface UserProfile {
  id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  role: string;
  created_at: string;
  stats: UserStats;
  held_badges?: ProfileBadgeDto[];
}

export interface PoolTypeStats {
  runs: number;
  avg_time_ms: number | null;
  avg_deaths: number;
  best_time_ms: number | null;
}

export interface UserPoolStatsEntry {
  pool_name: string;
  race: PoolTypeStats | null;
  training: PoolTypeStats | null;
  total_runs: number;
}

export interface UserPoolStats {
  pools: UserPoolStatsEntry[];
}

export type ActivityType =
  | "race_participant"
  | "race_organizer"
  | "race_caster"
  | "training"
  | "daily_participant";

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
  is_mod_connected: boolean;
  is_organizer: boolean;
}

export interface DailyParticipantActivity extends ActivityItemBase {
  type: "daily_participant";
  race_id: string;
  daily_date: string;
  pool_name: string;
  pool_display_name: string | null;
  status: string;
  placement: number | null;
  total_participants: number;
  igt_ms: number;
  death_count: number;
  is_mod_connected: boolean;
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
  pool_display_name: string | null;
  status: string;
  igt_ms: number;
  death_count: number;
  exclude_from_stats: boolean;
  is_mod_connected: boolean;
}

export type ActivityItem =
  | RaceParticipantActivity
  | RaceOrganizerActivity
  | RaceCasterActivity
  | TrainingActivityItem
  | DailyParticipantActivity;

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

export interface AdminPool {
  name: string;
  enabled: boolean;
  last_scanned_at: string | null;
  available: number;
  consumed: number;
  discarded: number;
  reported: number;
}

export interface AnalyticsKpis {
  total_users: number;
  new_users_this_month: number;
  active_users_30d: number;
  active_users_pct: number;
  total_races_finished: number;
  avg_participants: number;
  total_solo: number;
  solo_completion_pct: number;
}

export interface AnalyticsWeekly {
  weeks: string[];
  new_users: number[];
  races: number[];
  solo: number[];
  solo_finished: number[];
  solo_abandoned: number[];
  avg_participants: number[];
}

export interface AnalyticsTimezone {
  timezone: string;
  offset_minutes: number;
  count: number;
}

export interface AnalyticsPoolUsage {
  pool_name: string;
  race_runs: number;
  training_runs: number;
  total_runs: number;
}

export interface AnalyticsTopOrganizer {
  user_id: string;
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  race_count: number;
  avg_participants: number;
}

export interface AdminAnalytics {
  kpis: AnalyticsKpis;
  weekly: AnalyticsWeekly;
  heatmaps: {
    race_players: number[][];
    solo: number[][];
  };
  timezones: AnalyticsTimezone[];
  pool_usage: AnalyticsPoolUsage[];
  top_organizers: AnalyticsTopOrganizer[];
}

/**
 * Fetch admin analytics data (admin only).
 */
export async function fetchAdminAnalytics(): Promise<AdminAnalytics> {
  const response = await fetch(`${API_BASE}/admin/analytics`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<AdminAnalytics>(response);
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
 * List all pools with admin metadata (enabled, last_scanned_at, seed counts).
 */
export async function fetchAdminPools(): Promise<AdminPool[]> {
  const response = await fetch(`${API_BASE}/admin/pools`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<AdminPool[]>(response);
}

/**
 * Enable or disable a pool for end users (admin only).
 */
export async function setAdminPoolEnabled(
  poolName: string,
  enabled: boolean,
): Promise<AdminPool> {
  const response = await fetch(
    `${API_BASE}/admin/pools/${encodeURIComponent(poolName)}`,
    {
      method: "PATCH",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ enabled }),
    },
  );
  return handleResponse<AdminPool>(response);
}

export interface ReportedSeed {
  id: string;
  seed_number: string;
  pool_name: string;
  difficulty_score: number;
  reported_by: string;
  reported_reason: string | null;
  reported_at: string;
}

/**
 * Fetch reported seeds (admin only).
 */
export async function fetchReportedSeeds(): Promise<ReportedSeed[]> {
  const response = await fetch(`${API_BASE}/admin/reported-seeds`, {
    headers: getAuthHeaders(),
  });
  return handleResponse<ReportedSeed[]>(response);
}

/**
 * Resolve a reported seed (admin only).
 */
export async function resolveReportedSeed(
  seedId: string,
  action: "discard" | "restore",
): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/admin/seeds/${seedId}/resolve`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });
  return handleResponse<{ status: string }>(response);
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
    {
      headers: getAuthHeaders(),
    },
  );
  return handleResponse<ActivityTimeline>(response);
}

/**
 * Recalculate all user/participant stats (admin only).
 */
export async function adminRecalculateStats(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/admin/stats/recalculate`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  return handleResponse<{ status: string }>(response);
}

// =============================================================================
// Training API
// =============================================================================

export interface TrainingSession {
  id: string;
  user: User;
  status: "active" | "finished" | "abandoned" | "cancelled";
  pool_name: string;
  pool_display_name: string | null;
  igt_ms: number;
  death_count: number;
  exclude_from_stats: boolean;
  created_at: string;
  finished_at: string | null;
  seed_total_layers: number | null;
  seed_total_nodes: number | null;
  current_layer: number;
}

export interface TrainingSessionDetail extends TrainingSession {
  seed_number: string | null;
  seed_total_paths: number | null;
  zone_history: Array<{ node_id: string; igt_ms: number }> | null;
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
  excludeFromStats: boolean = false,
): Promise<TrainingSessionDetail> {
  const response = await fetch(`${API_BASE}/training`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      pool_name: poolName,
      exclude_from_stats: excludeFromStats,
    }),
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
  customFetch: typeof fetch = fetch,
): Promise<TrainingSessionDetail> {
  const response = await customFetch(`${API_BASE}/training/${id}`, {
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

export interface Ghost {
  zone_history: Array<{
    node_id: string;
    igt_ms: number;
    deaths?: number;
    type?: string;
  }>;
  igt_ms: number;
  death_count: number;
}

export async function fetchTrainingGhosts(sessionId: string): Promise<Ghost[]> {
  const res = await fetch(`${API_BASE}/training/${sessionId}/ghosts`);
  if (!res.ok) return [];
  return res.json();
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
  a.download = match?.[1] ?? `speedfog_solo_${sessionId}.zip`;
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

// =============================================================================
// Stats API
// =============================================================================

export interface LeaderboardPlayer {
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  elo_rating: number;
  elo_races: number;
  trend_delta: number;
  avg_opponent_elo: number | null;
  equipped_badge_id?: string | null;
  equipped_name_template_id?: string | null;
}

export interface CommunityStats {
  total_races: number;
  active_players: number;
  ranked_players: number;
  total_deaths: number;
  hours_raced: number;
}

export interface LeaderboardResponse {
  players: LeaderboardPlayer[];
  community: CommunityStats;
}

export interface ZoneStatEntry {
  display_name: string;
  type: string;
  total_deaths: number;
  avg_deaths_per_visit: number;
}

export interface ZoneBacktrackEntry {
  display_name: string;
  type: string;
  backtrack_count: number;
  avg_backtracks_per_race: number;
}

export interface ZoneTimeEntry {
  display_name: string;
  type: string;
  avg_time_ms: number;
  visits: number;
}

export interface ZoneStatsResponse {
  deadliest: ZoneStatEntry[];
  most_backtracked: ZoneBacktrackEntry[];
  slowest: ZoneTimeEntry[];
  fastest: ZoneTimeEntry[];
}

export interface BossStatEntry {
  display_name: string;
  type: string;
  encounters: number;
  avg_deaths: number;
  max_deaths: number;
  avg_time_ms: number;
  back_ratio: number;
}

export interface BossStatsResponse {
  bosses: BossStatEntry[];
}

export interface TraitPlayerEntry {
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  score: number;
  elo_rating: number;
}

export interface PlayerProfilesResponse {
  profiles: Record<string, TraitPlayerEntry[]>;
}

export interface TraitScoresDetail {
  rusher: number;
  cautious: number;
  resilient: number;
  rage_quitter: number;
  explorer: number;
  pathfinder: number;
  boss_slayer: number;
}

export interface UserTraitsResponse {
  dominant_trait: string | null;
  dominant_description: string | null;
  scores: TraitScoresDetail | null;
  finished_races: number;
  races_required: number;
  elo_rating: number;
  elo_rank: number | null;
  elo_trend_delta: number;
}

/**
 * Fetch the ELO leaderboard and community stats.
 */
export async function fetchLeaderboard(): Promise<LeaderboardResponse> {
  const res = await fetch(`${API_BASE}/stats/leaderboard`);
  if (!res.ok) throw new Error("Failed to fetch leaderboard");
  return res.json();
}

/**
 * Fetch zone death/visit statistics, optionally filtered by pool.
 */
export async function fetchZoneStats(
  pool?: string,
): Promise<ZoneStatsResponse> {
  const params = pool ? `?pool=${pool}` : "";
  const res = await fetch(`${API_BASE}/stats/zones${params}`);
  if (!res.ok) throw new Error("Failed to fetch zone stats");
  return res.json();
}

/**
 * Fetch boss encounter statistics, optionally filtered by pool.
 */
export async function fetchBossStats(
  pool?: string,
): Promise<BossStatsResponse> {
  const params = pool ? `?pool=${pool}` : "";
  const res = await fetch(`${API_BASE}/stats/bosses${params}`);
  if (!res.ok) throw new Error("Failed to fetch boss stats");
  return res.json();
}

/**
 * Fetch per-trait player leaderboards.
 */
export async function fetchPlayerProfiles(): Promise<PlayerProfilesResponse> {
  const res = await fetch(`${API_BASE}/stats/players`);
  if (!res.ok) throw new Error("Failed to fetch player profiles");
  return res.json();
}

/**
 * Fetch a user's trait scores and ELO details.
 */
export async function fetchUserTraits(
  username: string,
): Promise<UserTraitsResponse> {
  const res = await fetch(`${API_BASE}/users/${username}/traits`);
  if (!res.ok) throw new Error("Failed to fetch user traits");
  return res.json();
}

// =============================================================================
// Rewards
// =============================================================================

export interface BadgeDef {
  id: string;
  name: string;
  description?: string;
  icon_filename: string;
  lifecycle: "permanent" | "transient";
  sort_order: number;
}

export interface NameTemplateDef {
  id: string;
  name: string;
  description?: string;
  color: string | null;
  gradient: [string, string] | null;
  name_css: string | null;
  background_css: string | null;
  sort_order: number;
}

export interface RewardsCatalog {
  badges: BadgeDef[];
  name_templates: NameTemplateDef[];
}

export interface RewardNotificationDto {
  id: string;
  kind: "badge_granted" | "badge_revoked" | "name_template_unlocked";
  reward_id: string;
  created_at: string;
}

export interface MyInventoryDto {
  held_badges: { id: string; name: string; icon_filename: string }[];
  unlocked_templates: NameTemplateDef[];
  equipped_badge_id: string | null;
  equipped_name_template_id: string | null;
}

/**
 * Fetch pending reward notifications for the current user.
 * Returns an empty array when unauthenticated or on error.
 */
export async function fetchRewardNotifications(): Promise<
  RewardNotificationDto[]
> {
  const token = getStoredToken();
  if (!token) return [];
  const resp = await fetch(`${API_BASE}/rewards/notifications`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) return [];
  return resp.json();
}

/**
 * Bulk-dismiss all pending reward notifications for the current user.
 */
export async function dismissRewardNotifications(): Promise<void> {
  const token = getStoredToken();
  if (!token) return;
  await fetch(`${API_BASE}/rewards/notifications/dismiss`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

/**
 * Fetch the current user's reward inventory (held badges + unlocked templates + equipped ids).
 * Returns null when unauthenticated or on error.
 */
export async function fetchMyInventory(): Promise<MyInventoryDto | null> {
  const token = getStoredToken();
  if (!token) return null;
  const resp = await fetch(`${API_BASE}/rewards/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) return null;
  return resp.json();
}

/**
 * Update the current user's equipped badge and/or name template.
 * Pass null for a field to actively clear it; omit it to leave it unchanged.
 */
export async function patchEquipped(payload: {
  equipped_badge_id?: string | null;
  equipped_name_template_id?: string | null;
}): Promise<{
  equipped_badge_id: string | null;
  equipped_name_template_id: string | null;
} | null> {
  const token = getStoredToken();
  if (!token) return null;
  const resp = await fetch(`${API_BASE}/rewards/me/equipped`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) return null;
  return resp.json();
}

// =============================================================================
// Feedback API
// =============================================================================

export type FeedbackSource = "post_first_race" | "user_menu";

export interface FeedbackInput {
  rating: number;
  comment?: string | null;
  source: FeedbackSource;
  race_id?: string | null;
}

export interface Feedback {
  id: string;
  rating: number;
  comment: string | null;
  source: FeedbackSource;
  race_id: string | null;
  races_played_at_feedback: number;
  created_at: string;
}

export interface AdminFeedbackItem extends Feedback {
  user: {
    id: string;
    twitch_username: string;
    twitch_display_name: string | null;
  };
  race: { id: string } | null;
}

export interface AdminFeedbackList {
  items: AdminFeedbackItem[];
  total: number;
  average_rating: number | null;
  distribution: Record<string, number>;
}

/**
 * Submit user feedback (rating + optional comment).
 */
export async function submitFeedback(input: FeedbackInput): Promise<Feedback> {
  const response = await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  return handleResponse<Feedback>(response);
}

/**
 * Mark the current user as having been prompted for feedback (idempotent, 204).
 */
export async function markFeedbackPrompted(): Promise<void> {
  const response = await fetch(`${API_BASE}/feedback/mark-prompted`, {
    method: "POST",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    const error: ApiError = await response
      .json()
      .catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail);
  }
}

/**
 * List feedback entries (admin only).
 */
export async function adminListFeedback(params: {
  source?: FeedbackSource;
  rating_min?: number;
  rating_max?: number;
  limit?: number;
  offset?: number;
}): Promise<AdminFeedbackList> {
  const query = new URLSearchParams();
  if (params.source !== undefined) query.set("source", params.source);
  if (params.rating_min !== undefined)
    query.set("rating_min", String(params.rating_min));
  if (params.rating_max !== undefined)
    query.set("rating_max", String(params.rating_max));
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  const url = qs
    ? `${API_BASE}/admin/feedback?${qs}`
    : `${API_BASE}/admin/feedback`;
  const response = await fetch(url, {
    headers: getAuthHeaders(),
  });
  return handleResponse<AdminFeedbackList>(response);
}
