<script lang="ts">
  import SkullIcon from "$lib/components/SkullIcon.svelte";
  import { formatGap } from "$lib/gap";
  import { formatTime } from "$lib/highlights";
  import type { DetailColumn, DetailRow } from "$lib/layer-gaps";

  interface RunnerLook {
    name: string;
    color: string;
    status: string;
  }

  interface Props {
    /** The hovered or pinned layer; null shows the hint. */
    layer: number | null;
    pinned: boolean;
    columns: DetailColumn[];
    runners: Map<string, RunnerLook>;
    nodeNames: Map<string, string>;
    onnodeclick?: (nodeId: string) => void;
  }

  let { layer, pinned, columns, runners, nodeNames, onnodeclick }: Props =
    $props();

  function entryCell(ms: number | null): string {
    if (ms === null) return "-";
    return ms === 0 ? "lead" : formatGap(ms);
  }

  function timeCell(row: DetailRow): string {
    switch (row.state) {
      case "done":
        return formatTime(row.timeMs ?? 0);
      case "live":
        return `${formatTime(row.timeMs ?? 0)}…`;
      case "out":
        return runners.get(row.id)?.status === "disqualified" ? "DQ" : "DNF";
      default:
        return "-";
    }
  }

  function vsBestCell(ms: number | null): string {
    if (ms === null) return "";
    return ms === 0 ? "fastest" : formatGap(ms);
  }

  function nodeName(nodeId: string): string {
    return nodeNames.get(nodeId) ?? nodeId;
  }
</script>

<section class="layer-detail" aria-live="polite">
  {#if layer === null}
    <p class="hint">Hover or tap a layer to compare</p>
  {:else}
    <header class="detail-head">
      <span class="detail-layer">Layer {layer}</span>
      {#if pinned}<span class="pinned-tag">pinned</span>{/if}
    </header>
    {#if columns.length === 0}
      <p class="hint">None of the selected runners reached this layer yet.</p>
    {:else}
      <div class="columns">
        {#each columns as column (column.nodeId)}
          <div class="node-col">
            <button
              type="button"
              class="node-name"
              title={nodeName(column.nodeId)}
              disabled={!onnodeclick}
              onclick={() => onnodeclick?.(column.nodeId)}
              >{nodeName(column.nodeId)}</button
            >
            <div class="field">
              {#if column.field}
                field best {formatTime(column.field.bestMs)} · median {formatTime(
                  column.field.medianMs,
                )} · {column.field.count}
                {column.field.count === 1 ? "runner" : "runners"}
              {:else}
                no complete run through this node yet
              {/if}
            </div>
            <div class="row heads" aria-hidden="true">
              <span class="c-entry">entry</span>
              <span class="c-time">time</span>
              <span class="c-vs">vs best</span>
              <span class="c-field">field</span>
            </div>
            {#each column.rows as row (row.id)}
              {@const look = runners.get(row.id)}
              <div class="row">
                <span
                  class="dot"
                  style="background: {look?.color ?? 'transparent'}"
                ></span>
                <span class="name">{look?.name ?? ""}</span>
                <span class="c-entry num muted"
                  >{entryCell(row.entryGapMs)}</span
                >
                <span class="c-time num" class:live={row.state === "live"}
                  >{timeCell(row)}</span
                >
                <span
                  class="c-vs num"
                  class:best={row.vsBestMs === 0}
                  class:worse={row.vsBestMs !== null && row.vsBestMs > 0}
                  >{vsBestCell(row.vsBestMs)}</span
                >
                <span class="c-field num muted"
                  >{row.fieldRank !== null && column.field
                    ? `${row.fieldRank}/${column.field.count}`
                    : ""}</span
                >
                <span class="deaths">
                  {#if row.deaths > 0}<SkullIcon size={10} />{row.deaths}{/if}
                </span>
              </div>
              {#if row.backedOutOf}
                <div class="note">
                  backed out of {nodeName(row.backedOutOf)} · {formatTime(
                    row.detourMs ?? 0,
                  )} detour
                </div>
              {/if}
            {/each}
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</section>

<style>
  .layer-detail {
    container: layer-detail / inline-size;
    margin-top: 0.5rem;
    padding: 0.6rem 0.75rem;
    background: var(--color-surface);
    border-radius: var(--radius-lg, 8px);
    /* Reserved so hovering in and out of the chart never moves the page. */
    min-height: 8.5rem;
  }

  .hint {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .detail-head {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    margin-bottom: 0.35rem;
  }

  .detail-layer {
    font-family: var(--font-display);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: var(--font-size-lg);
  }

  .pinned-tag {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .columns {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem 1.25rem;
  }

  /* The panel's own width decides, not the viewport's: with the chat open
     the main column is far narrower than the screen. */
  @container layer-detail (max-width: 36rem) {
    .columns {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .node-col {
    container: node-col / inline-size;
    min-width: 0;
    border-top: 1px solid var(--color-border);
    padding-top: 0.35rem;
  }

  .node-name {
    all: unset;
    display: block;
    max-width: 100%;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: pointer;
  }

  .node-name:disabled {
    cursor: default;
  }

  .node-name:not(:disabled):hover {
    color: var(--color-purple-hover);
  }

  .node-name:focus-visible {
    outline: 2px solid var(--color-purple);
  }

  .field {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  /* Narrow column: name and deaths, then the numbers on a second line. */
  .row {
    display: grid;
    grid-template-columns: 9px minmax(0, 1fr) 2.9rem 3.2rem 2.3rem;
    grid-template-areas:
      "dot name name name deaths"
      ". entry time vs field";
    column-gap: 0.35rem;
    align-items: center;
    margin-top: 0.3rem;
    font-size: var(--font-size-sm);
  }

  .row.heads {
    grid-template-areas: ". entry time vs field";
    margin-top: 0.4rem;
    font-size: 0.68rem;
    color: var(--color-text-secondary);
  }

  /* Wide column: one line per runner. */
  @container node-col (min-width: 21rem) {
    .row {
      grid-template-columns: 9px minmax(
          0,
          1fr
        ) 2.9rem 2.9rem 3.2rem 2.3rem 1.7rem;
      grid-template-areas: "dot name entry time vs field deaths";
      margin-top: 0.2rem;
    }

    .row.heads {
      grid-template-areas: ". . entry time vs field .";
    }
  }

  .dot {
    grid-area: dot;
    width: 9px;
    height: 9px;
    border-radius: 50%;
  }

  .name {
    grid-area: name;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .c-entry {
    grid-area: entry;
  }

  .c-time {
    grid-area: time;
  }

  .c-vs {
    grid-area: vs;
  }

  .c-field {
    grid-area: field;
  }

  .heads span,
  .num {
    text-align: right;
  }

  .num {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .muted {
    color: var(--color-text-secondary);
  }

  .best {
    color: var(--color-success);
  }

  .worse {
    color: var(--color-danger);
  }

  .live {
    font-style: italic;
  }

  .deaths {
    grid-area: deaths;
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 2px;
    color: var(--color-danger);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .note {
    padding-left: calc(9px + 0.35rem);
    font-size: 0.7rem;
    color: var(--color-text-secondary);
  }
</style>
