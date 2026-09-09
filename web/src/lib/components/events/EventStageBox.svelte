<script lang="ts" module>
  import type { User } from "$lib/api";
  export interface StageRow {
    key: string;
    rank: string | number | null;
    user: User | null;
    label?: string;
    newcomer?: boolean;
    right?: string;
    rightClass?: "pts" | "lead" | "adv";
  }
</script>

<script lang="ts">
  import UserLink from "$lib/components/UserLink.svelte";

  let {
    title,
    meta,
    state,
    signal,
    rows,
  }: {
    title: string;
    meta: string;
    state: "setup" | "running" | "finished";
    signal: { cls: string; text: string };
    rows: StageRow[];
  } = $props();
</script>

<div class="box">
  <div class="route route-{state}" aria-hidden="true">
    <span class="line"></span><span class="m-start"></span><span class="m-end"
    ></span>
    {#if state === "running"}<span class="m-train"></span>{/if}
  </div>
  <div class="head">
    <div>
      <div class="name">{title}</div>
      <div class="meta">{meta}</div>
    </div>
    <span class="signal {signal.cls}">{signal.text}</span>
  </div>
  <ol>
    {#each rows as row (row.key)}
      <li>
        <span class="rank" class:rank-gold={row.rank === 1}
          >{row.rank ?? ""}</span
        >
        <span class="who">
          {#if row.user}
            <UserLink user={row.user} showBadge />
          {:else}
            <span class="tbd">{row.label ?? "open"}</span>
          {/if}
          {#if row.newcomer}<span class="newtag">new</span>{/if}
        </span>
        <span class="right {row.rightClass ?? 'pts'}">{row.right ?? ""}</span>
      </li>
    {/each}
  </ol>
</div>

<style>
  .box {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.7rem 0.9rem 0.75rem;
    min-height: 168px;
    box-sizing: border-box;
  }
  .box > :global(.route) {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
  }
  .name {
    font-family: var(--font-display);
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
  }
  .meta {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--color-text-secondary);
    margin-top: 1px;
  }
  ol {
    list-style: none;
    margin: 0.45rem 0 0;
    padding: 0;
  }
  li {
    display: grid;
    grid-template-columns: 1.3rem minmax(0, 1fr) auto;
    column-gap: 0.4rem;
    align-items: center;
    padding: 0.22rem 0;
    border-top: 1px solid var(--color-border);
    font-size: 0.85rem;
  }
  li:first-child {
    border-top: 0;
  }
  .rank {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--color-text-secondary);
    text-align: right;
  }
  .rank-gold {
    color: var(--color-gold);
  }
  .who {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
  }
  .tbd {
    color: var(--color-text-disabled);
    font-style: italic;
  }
  .newtag {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0 4px;
  }
  .right {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }
  .right.lead {
    color: var(--color-success);
    font-weight: 600;
  }
  .right.adv {
    color: var(--color-success);
    font-size: 0.7rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }
</style>
