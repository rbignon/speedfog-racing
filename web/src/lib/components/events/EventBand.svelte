<script lang="ts">
  // The event on the bill, as the home page and the dashboard feature it:
  // the event page's lockup, a phase signal with one line of state, and the
  // buttons that lead there (or to the live race). Signing up stays on the
  // event page, which owns the Twitch intent flow.
  import type { EventSummary, User } from "$lib/api";
  import { eventBand, formatEventDate } from "$lib/events";
  import UserLink from "$lib/components/UserLink.svelte";

  let { event }: { event: EventSummary } = $props();

  // The instants on the line are ahead of the viewer, so they carry the zone.
  let state = $derived(eventBand(event, (iso) => formatEventDate(iso, true)));
  let overflowCount = $derived(
    Math.max(0, event.players - event.player_previews.length),
  );
  const nameOf = (user: User) =>
    user.twitch_display_name || user.twitch_username;
</script>

<section class="band" aria-label="Current event">
  <div class="band-inner">
    <div class="band-left">
      <h2>
        SpeedFog
        {#if event.partner_name}<span class="cross">&times;</span>
          {event.partner_name}{/if}
        <span class="brass">{event.name}</span>
      </h2>
      <div class="state">
        <span class="signal {state.signal.cls}">{state.signal.text}</span>
        {#if state.line}<span class="line">{state.line}</span>{/if}
        {#if event.phase === "finished" && event.champion}
          <UserLink user={event.champion} showAvatar />
        {/if}
        {#if state.showPlayers}
          <div
            class="avatar-stack"
            role="group"
            aria-label="{event.players} player{event.players === 1
              ? ''
              : 's'} in"
          >
            {#each event.player_previews as user (user.id)}
              {#if user.twitch_avatar_url}
                <img
                  src={user.twitch_avatar_url}
                  alt={nameOf(user)}
                  title={nameOf(user)}
                  class="avatar"
                />
              {:else}
                <span
                  class="avatar avatar-placeholder"
                  role="img"
                  aria-label={nameOf(user)}
                  title={nameOf(user)}
                  >{nameOf(user).charAt(0).toUpperCase()}</span
                >
              {/if}
            {/each}
            {#if overflowCount > 0}
              <span class="avatar avatar-overflow">+{overflowCount}</span>
            {/if}
          </div>
        {/if}
      </div>
    </div>
    <div class="band-right">
      {#if event.partner_name}
        {#if event.partner_logo_url}
          <img class="partner-logo" src={event.partner_logo_url} alt="" />
        {:else}
          <span class="partner-logo placeholder"
            >{event.partner_name.slice(0, 2).toUpperCase()}</span
          >
        {/if}
      {/if}
      {#if state.signedUp}
        <span class="in">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            width="14"
            height="14"
            aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg
          >
          You're in
        </span>
      {/if}
      <div class="actions">
        {#each state.actions as action (action.href)}
          <a
            href={action.href}
            class="btn btn-{action.kind}"
            target={action.kind === "twitch" ? "_blank" : undefined}
            rel={action.kind === "twitch" ? "noopener noreferrer" : undefined}
            >{action.label}</a
          >
        {/each}
      </div>
    </div>
  </div>
</section>

<style>
  .band {
    background: var(--color-surface-elevated);
    border-top: 1px solid var(--color-border);
    border-bottom: 1px solid var(--color-border);
  }
  .band-inner {
    max-width: 1180px;
    margin: 0 auto;
    padding: 1.25rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1.5rem 2rem;
    flex-wrap: wrap;
  }
  .band-left {
    flex: 1 1 460px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    line-height: 1.12;
    color: var(--color-text);
  }
  h2 .cross {
    color: var(--color-text-secondary);
    font-weight: 500;
  }
  h2 .brass {
    color: var(--color-gold);
    font-weight: 600;
  }
  .state {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    flex-wrap: wrap;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }
  .state .line {
    color: var(--color-text);
  }
  /* The race cards' crew row, on the band's own ground */
  .avatar-stack {
    display: flex;
    align-items: center;
  }
  .avatar {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 2px solid var(--color-surface-elevated);
    margin-left: -6px;
    object-fit: cover;
  }
  .avatar:first-child {
    margin-left: 0;
  }
  .avatar-placeholder,
  .avatar-overflow {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }
  .band-right {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .partner-logo {
    width: 40px;
    height: 40px;
    border-radius: var(--radius-sm);
    object-fit: contain;
  }
  .partner-logo.placeholder {
    border: 1px dashed var(--color-purple);
    color: var(--color-purple);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-display);
    font-weight: 700;
    letter-spacing: 0.06em;
  }
  .in {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: var(--color-success);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    white-space: nowrap;
  }
  .actions {
    display: flex;
    gap: 0.5rem;
  }

  @media (max-width: 640px) {
    .band-inner {
      padding: 1rem;
    }
  }
</style>
