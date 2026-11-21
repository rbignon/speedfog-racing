<script lang="ts">
  import {
    createRelayTeam,
    deleteRelayTeam,
    fetchRace,
    joinRelayTeam,
    moveRelayParticipant,
    updateRace,
    updateRelayTeam,
    type Participant,
    type RaceDetail,
    type RelayTeam,
  } from "$lib/api";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { teamSlotAction, teamView } from "$lib/relay";
  import ParticipantCard from "./ParticipantCard.svelte";

  type MergedParticipant = Participant & {
    liveStatus?: string;
    isLive?: boolean;
    streamUrl?: string | null;
  };

  interface Props {
    raceId: string;
    teams: RelayTeam[];
    participants: MergedParticipant[];
    teamSize: number;
    runnersCreateTeams: boolean;
    /** The organizer's user id: their card carries the Org badge and no cross. */
    organizerUserId: string;
    viewer: {
      participantId: string | null;
      isOrganizer: boolean;
      /** May take a seat on a team (logged in, not a caster, not locked out). */
      canRegister: boolean;
    };
    onChanged: (race: RaceDetail) => void;
    onRemove: (participantId: string, username: string) => void;
  }

  let {
    raceId,
    teams,
    participants,
    teamSize,
    runnersCreateTeams,
    organizerUserId,
    viewer,
    onChanged,
    onRemove,
  }: Props = $props();

  let view = $derived(teamView(teams, participants));
  let myTeamId = $derived(
    participants.find((p) => p.id === viewer.participantId)?.relay_team_id ??
      null,
  );
  let slotViewer = $derived({
    participantTeamId: myTeamId,
    canRegister: viewer.canRegister,
  });
  let canCreate = $derived(
    viewer.isOrganizer || (runnersCreateTeams && viewer.canRegister),
  );

  let busy = $state(false);
  let error = $state<string | null>(null);
  let renamingId = $state<string | null>(null);
  let nameDraft = $state("");
  let changingId = $state<string | null>(null);
  let menuFor = $state<string | null>(null);

  /** Runs a REST action; true when it succeeded. A refusal broadcasts
   * nothing, so the list could be stale (a full or deleted team): re-read the
   * race and keep the server's message on screen. */
  async function run(
    action: () => Promise<RaceDetail | void>,
  ): Promise<boolean> {
    busy = true;
    error = null;
    try {
      const race = await action();
      if (race) onChanged(race);
      return true;
    } catch (e) {
      error = e instanceof Error ? e.message : "Something went wrong";
      try {
        onChanged(await fetchRace(raceId));
      } catch {
        // The refusal message stays; the next broadcast refreshes the list.
      }
      return false;
    } finally {
      busy = false;
    }
  }

  function canEdit(team: RelayTeam): boolean {
    return viewer.isOrganizer || team.id === myTeamId;
  }

  function startRename(team: RelayTeam) {
    changingId = null;
    renamingId = team.id;
    nameDraft = team.name;
  }

  async function saveRename(team: RelayTeam) {
    const name = nameDraft.trim();
    if (!name || name === team.name) {
      renamingId = null;
      return;
    }
    if (await run(() => updateRelayTeam(raceId, team.id, { name }))) {
      renamingId = null;
    }
  }

  async function chooseFirstRunner(team: RelayTeam, participantId: string) {
    const ok = await run(() =>
      updateRelayTeam(raceId, team.id, { first_runner_id: participantId }),
    );
    if (ok) changingId = null;
  }

  function takeSeat(team: RelayTeam) {
    return run(() => joinRelayTeam(raceId, team.id));
  }

  function moveMember(participantId: string, team: RelayTeam) {
    menuFor = null;
    return run(() => moveRelayParticipant(raceId, participantId, team.id));
  }

  function removeMember(p: MergedParticipant) {
    menuFor = null;
    onRemove(p.id, p.user.twitch_username);
  }

  function deleteTeam(team: RelayTeam) {
    return run(async () => {
      await deleteRelayTeam(raceId, team.id);
      return fetchRace(raceId);
    });
  }

  function createTeam() {
    return run(() => createRelayTeam(raceId, null));
  }

  let toggleEl = $state<HTMLInputElement | undefined>();

  async function setRunnersCreateTeams(allowed: boolean) {
    const ok = await run(async () => {
      await updateRace(raceId, { relay_runners_create_teams: allowed });
      return fetchRace(raceId);
    });
    // The box is one-way: after a refusal drive it back to the server's state.
    if (!ok && toggleEl) toggleEl.checked = runnersCreateTeams;
  }

  function nameOf(id: string | null): string {
    return participants.find((p) => p.id === id)?.user.twitch_username ?? "";
  }
</script>

<svelte:window
  onclick={(e) => {
    if (menuFor && !(e.target as HTMLElement).closest(".member"))
      menuFor = null;
  }}
  onkeydown={(e) => {
    if (e.key === "Escape") menuFor = null;
  }}
/>

<div class="relay-teams">
  {#each view as { team, members } (team.id)}
    {@const action = teamSlotAction(team, teamSize, slotViewer)}
    {@const starter = team.first_runner_id}
    <h3 class="team-header">
      <span
        class="team-color"
        style="background: {PLAYER_COLORS[
          team.color_index % PLAYER_COLORS.length
        ]}"
      ></span>
      {#if renamingId === team.id}
        <input
          class="team-name-input"
          aria-label="Team name"
          maxlength="40"
          bind:value={nameDraft}
          onkeydown={(e) => {
            if (e.key === "Enter") saveRename(team);
            if (e.key === "Escape") renamingId = null;
          }}
          disabled={busy}
        />
        <button class="link" onclick={() => saveRename(team)} disabled={busy}
          >Save</button
        >
        <button class="link" onclick={() => (renamingId = null)}>Cancel</button>
      {:else}
        <span class="team-name">{team.name}</span>
        <span class="team-count">{members.length}/{teamSize}</span>
        {#if canEdit(team)}
          <button
            class="link"
            title="Rename team"
            onclick={() => startRename(team)}>Edit</button
          >
        {/if}
        {#if viewer.isOrganizer && members.length === 0}
          <button
            class="link"
            title="Delete this empty team"
            onclick={() => deleteTeam(team)}
            disabled={busy}>Delete</button
          >
        {/if}
      {/if}
    </h3>

    {#if members.length === 0}
      <p class="no-runner">No runner yet</p>
    {:else}
      <p class="starts">
        <span>Starts: <strong>{nameOf(starter)}</strong></span>
        {#if canEdit(team) && members.length > 1}
          {#if changingId === team.id}
            <select
              aria-label="First runner"
              value={starter}
              onchange={(e) => chooseFirstRunner(team, e.currentTarget.value)}
              disabled={busy}
            >
              {#each members as m (m.id)}
                <option value={m.id}>{m.user.twitch_username}</option>
              {/each}
            </select>
            <button class="link" onclick={() => (changingId = null)}
              >Cancel</button
            >
          {:else}
            <button
              class="link underlined"
              onclick={() => {
                renamingId = null;
                changingId = team.id;
              }}>Change</button
            >
          {/if}
        {/if}
      </p>
    {/if}

    {#each members as mp (mp.id)}
      <div class="member">
        <ParticipantCard
          participant={mp}
          liveStatus={mp.liveStatus}
          isOrganizer={mp.user.id === organizerUserId}
          isCurrentUser={mp.id === viewer.participantId}
          isLive={mp.isLive}
          streamUrl={mp.streamUrl}
          canRemove={viewer.isOrganizer && mp.user.id !== organizerUserId}
          removeTitle="Move or remove"
          onRemove={() => (menuFor = menuFor === mp.id ? null : mp.id)}
        />
        {#if menuFor === mp.id}
          <div class="member-menu" role="menu">
            {#each teams as other (other.id)}
              {#if other.id !== team.id && teamSlotAction( other, teamSize, { participantTeamId: team.id, canRegister: true }, )}
                <button
                  role="menuitem"
                  onclick={() => moveMember(mp.id, other)}
                  disabled={busy}>Move to {other.name}</button
                >
              {/if}
            {/each}
            <button
              role="menuitem"
              class="danger"
              onclick={() => removeMember(mp)}>Remove from race</button
            >
          </div>
        {/if}
      </div>
    {/each}

    {#if action}
      <button class="dashed" onclick={() => takeSeat(team)} disabled={busy}>
        {action === "join" ? "+ Join this team" : "Move to this team"}
      </button>
    {/if}
  {/each}

  {#if canCreate}
    <button class="dashed create" onclick={createTeam} disabled={busy}
      >+ Create a team</button
    >
  {/if}

  {#if viewer.isOrganizer}
    <label class="create-toggle">
      <input
        type="checkbox"
        bind:this={toggleEl}
        checked={runnersCreateTeams}
        onchange={(e) => setRunnersCreateTeams(e.currentTarget.checked)}
        disabled={busy}
      />
      <span>Runners can create teams</span>
    </label>
    {#if !runnersCreateTeams}
      <p class="hint">
        Off: only you create teams, the race is full when they are.
      </p>
    {/if}
  {/if}

  {#if error}
    <p class="error">{error}</p>
  {/if}
</div>

<style>
  .team-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 18px 0 4px;
    font-size: var(--font-size-base);
    font-weight: 600;
  }

  .relay-teams > .team-header:first-child {
    margin-top: 0;
  }

  .team-color {
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex: none;
  }

  .team-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-text);
  }

  .team-name-input {
    flex: 1;
    min-width: 0;
    padding: 0.25rem 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
  }

  .team-count {
    opacity: 0.6;
    font-weight: 400;
  }

  .link {
    background: none;
    border: none;
    padding: 0;
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 400;
    opacity: 0.75;
    cursor: pointer;
  }

  .link.underlined {
    text-decoration: underline;
  }

  .link:hover {
    color: var(--color-purple);
    opacity: 1;
  }

  .starts {
    margin: 0 0 8px;
    font-size: 0.8rem;
    opacity: 0.7;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .starts strong {
    font-weight: 600;
  }

  .starts select {
    padding: 0.125rem 0.25rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-family);
  }

  .no-runner {
    margin: 0 0 8px;
    font-size: 0.8rem;
    opacity: 0.55;
    font-style: italic;
  }

  .member {
    margin-bottom: 6px;
  }

  .member-menu {
    display: flex;
    flex-direction: column;
    margin-top: 2px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface, var(--color-bg));
  }

  .member-menu button {
    background: none;
    border: none;
    padding: 0.5rem 0.75rem;
    text-align: left;
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
  }

  .member-menu button:hover {
    color: var(--color-purple);
  }

  .member-menu button.danger:hover {
    color: var(--color-danger);
  }

  .dashed {
    margin-top: 2px;
    width: 100%;
    padding: 0.75rem;
    border: 2px dashed var(--color-border);
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-base);
    cursor: pointer;
    transition: all var(--transition);
  }

  .dashed.create {
    margin-top: 18px;
  }

  .dashed:hover:not(:disabled) {
    border-color: var(--color-purple);
    color: var(--color-purple);
  }

  .create-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 12px 0 4px;
    font-size: 0.85rem;
    cursor: pointer;
  }

  .create-toggle input {
    accent-color: var(--color-purple);
    width: 15px;
    height: 15px;
    margin: 0;
  }

  .hint {
    margin: 0;
    font-size: 0.78rem;
    opacity: 0.6;
    line-height: 1.4;
  }

  .error {
    margin: 0.5rem 0 0;
    color: var(--color-danger, #ef4444);
    font-size: var(--font-size-sm);
  }
</style>
