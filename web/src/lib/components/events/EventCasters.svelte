<script lang="ts">
  import type { Caster } from "$lib/api";
  import LiveBadge from "$lib/components/LiveBadge.svelte";
  import UserLink from "$lib/components/UserLink.svelte";

  /**
   * A match's casters in one line that wraps: each one link to their stream
   * (avatar, name, language, a Twitch mark, LIVE while they stream), or a
   * placeholder while nobody casts it yet.
   */
  let {
    casters,
    languages = {},
    stacked = false,
  }: {
    casters: Caster[];
    /** Caster user id -> language code (`caster_languages`). */
    languages?: Record<string, string>;
    /** A narrow box's form: the label on a row of its own, tighter. */
    stacked?: boolean;
  } = $props();

  // Each caster's own live stream, else their channel.
  const watchUrl = (caster: Caster) =>
    caster.stream_url ?? `https://twitch.tv/${caster.user.twitch_username}`;
</script>

{#snippet twitchIcon()}
  <svg viewBox="0 0 24 24" aria-hidden="true"
    ><path
      d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"
    /></svg
  >
{/snippet}

<div class="cast" class:stacked>
  <span class="k">{@render twitchIcon()}Cast by</span>
  <ul>
    {#each casters as caster (caster.user.id)}
      <li class="caster">
        <UserLink
          user={caster.user}
          showAvatar
          href={watchUrl(caster)}
          title="Watch {caster.user.twitch_display_name ||
            caster.user.twitch_username} on Twitch"
        >
          {#if languages[caster.user.id]}<span class="lang"
              >{languages[caster.user.id]}</span
            >{/if}
          <span class="mark">{@render twitchIcon()}</span>
          {#if caster.is_live}<LiveBadge small />{/if}
        </UserLink>
      </li>
    {:else}
      <li class="tba">Casters to be announced</li>
    {/each}
  </ul>
</div>

<style>
  .cast {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    margin-top: 0.8rem;
    padding-top: 0.7rem;
    border-top: 1px solid var(--color-border);
  }
  .k {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-twitch-hover);
  }
  svg {
    width: 12px;
    height: 12px;
    fill: currentColor;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.25rem;
  }
  .caster {
    display: inline-flex;
    align-items: center;
    font-weight: 600;
  }
  .lang {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0 4px;
    color: var(--color-text-secondary);
  }
  /* The Twitch mark says where the link leads; it brightens on hover. */
  .mark {
    display: inline-flex;
    color: var(--color-twitch-hover);
    transition: color var(--transition);
  }
  .mark svg {
    width: 13px;
    height: 13px;
  }
  .caster:hover .mark,
  .caster:focus-within .mark {
    color: var(--color-purple);
  }
  .tba {
    color: var(--color-text-disabled);
    font-style: italic;
    font-size: var(--font-size-sm);
  }
  .cast.stacked {
    gap: 0.4rem 0.9rem;
    margin-top: 0.6rem;
    padding-top: 0.6rem;
  }
  .stacked .k {
    width: 100%;
  }
  .stacked ul {
    gap: 0.4rem 0.9rem;
  }
</style>
