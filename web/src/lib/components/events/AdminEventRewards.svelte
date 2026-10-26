<script lang="ts">
  import { onMount } from "svelte";
  import {
    fetchAdminEventRewards,
    grantAdminEventRewards,
    type EventRewardBlock,
  } from "$lib/api";
  import UserLink from "$lib/components/UserLink.svelte";

  interface Props {
    eventId: string;
    onClose: () => void;
  }

  let { eventId, onClose }: Props = $props();

  const WAITING_COPY: Record<
    NonNullable<EventRewardBlock["waiting"]>,
    string
  > = {
    ladder_provisional: "Waiting: the qualifier ladder is still provisional.",
    draw_not_locked: "Waiting: the draw is not locked yet.",
    stage_incomplete: "Waiting: the bracket's last stage is not complete.",
    no_champion: "No champion: nobody finished the bracket's last stage.",
  };

  let blocks = $state<EventRewardBlock[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let busyKey = $state<string | null>(null);
  // Count of the last grant, per block key.
  let grantedCounts = $state<Record<string, number>>({});

  const keyOf = (b: EventRewardBlock) => `${b.bracket_key}:${b.role}`;

  async function load() {
    try {
      blocks = (await fetchAdminEventRewards(eventId)).blocks;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load rewards";
    } finally {
      loading = false;
    }
  }

  async function grant(b: EventRewardBlock) {
    const key = keyOf(b);
    busyKey = key;
    error = null;
    try {
      const result = await grantAdminEventRewards(
        eventId,
        b.bracket_key,
        b.role,
      );
      grantedCounts[key] = result.granted;
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : "Grant failed";
    } finally {
      busyKey = null;
    }
  }

  function ownsAll(b: EventRewardBlock, owned: string[]): boolean {
    return b.rewards.every((r) => owned.includes(`${r.kind}:${r.id}`));
  }

  onMount(load);
</script>

<div class="rewards-panel">
  <div class="rewards-head">
    <h3>Rewards</h3>
    <button class="btn btn-outline" onclick={onClose}>Close</button>
  </div>
  {#if error}<p class="error-text">{error}</p>{/if}
  {#if loading}
    <p class="loading">Loading rewards...</p>
  {:else if blocks.length === 0}
    <p class="empty">This event's brackets declare no rewards.</p>
  {/if}
  {#each blocks as b (keyOf(b))}
    <section class="reward-block">
      <h4>
        {b.bracket_label}: {b.role === "seated" ? "qualifiers" : "champion"}
      </h4>
      <p class="reward-items">
        {b.rewards.map((r) => r.name).join(", ")}
      </p>
      {#if b.waiting}
        <p class="waiting">{WAITING_COPY[b.waiting]}</p>
      {/if}
      {#if b.unknown_rewards.length > 0}
        <p class="reward-sub">Not grantable, skipped</p>
        <ul>
          {#each b.unknown_rewards as ref (ref)}<li>{ref}</li>{/each}
        </ul>
      {/if}
      {#if b.recipients.length > 0}
        <ul class="recipients">
          {#each b.recipients as r (r.user.id)}
            <li>
              <UserLink user={r.user} />
              {#if ownsAll(b, r.owned)}<span class="owned">already owned</span
                >{/if}
            </li>
          {/each}
        </ul>
      {/if}
      {#if b.banned.length > 0}
        <p class="reward-sub">Skipped (banned)</p>
        <ul>
          {#each b.banned as u (u.id)}<li><UserLink user={u} /></li>{/each}
        </ul>
      {/if}
      <div class="reward-actions">
        <button
          class="btn btn-primary grant-btn"
          disabled={b.waiting !== null ||
            b.new_grants === 0 ||
            busyKey !== null}
          onclick={() => grant(b)}>Grant</button
        >
        {#if grantedCounts[keyOf(b)] !== undefined}
          <span class="signal signal-open"
            >Granted {grantedCounts[keyOf(b)]}</span
          >
        {/if}
      </div>
    </section>
  {/each}
</div>

<style>
  .rewards-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.8rem;
  }

  .reward-block {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.8rem;
    margin-bottom: 0.8rem;
  }

  .reward-block h4 {
    margin: 0 0 0.3rem;
  }

  .reward-items,
  .reward-sub,
  .waiting {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin: 0.3rem 0;
  }

  .recipients,
  ul {
    list-style: none;
    padding: 0;
    margin: 0.4rem 0;
  }

  .owned {
    margin-left: 0.5rem;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .reward-actions {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin-top: 0.6rem;
  }

  .error-text {
    color: var(--color-danger);
    font-size: var(--font-size-sm);
  }
</style>
