<script lang="ts">
  import type { Snippet } from "svelte";
  import {
    CANVAS,
    sceneLayout,
    maskDataUri,
    formatGeo,
    pierceableHoles,
    type CastSceneId,
  } from "$lib/cast/layout";

  interface Props {
    scene: CastSceneId;
    focus?: number;
    cams?: number;
    guides?: boolean;
    /** Which POV/hero slots (1-based) currently hold a seated runner, from
     * the same `resolveSlots` result the page renders. Omitted on scenes
     * with no such holes (metro, talk). A slot missing from this list is
     * not pierced: with no runner seated there, there is nothing for a
     * video source to show through, and an unseated hole would otherwise
     * broadcast an empty, numbered frame over whatever sits beneath it. */
    seatedSlots?: number[];
    children: Snippet;
  }

  let {
    scene,
    focus = 1,
    cams = 2,
    guides = false,
    seatedSlots,
    children,
  }: Props = $props();

  let layout = $derived(sceneLayout(scene, { focus, cams }));
  let pierced = $derived(pierceableHoles(layout.holes, seatedSlots));
  let mask = $derived(maskDataUri(pierced));

  // The canvas is a fixed 1920x1080 design; the browser source (or a dev
  // window) is scaled down to fit it, never the other way around.
  let innerWidth = $state(0);
  let innerHeight = $state(0);
  let scale = $derived(Math.min(innerWidth / CANVAS.w, innerHeight / CANVAS.h));
</script>

<svelte:window bind:innerWidth bind:innerHeight />

<div class="fit" style="--s: {scale};">
  <div class="canvas" style="--mask: {mask};">
    <div class="plate"></div>
    {@render children()}
    {#if guides}
      {#each layout.holes as hole (hole.id)}
        <div
          class="guide"
          style="left: {hole.x}px; top: {hole.y}px; width: {hole.w}px; height: {hole.h}px;"
        >
          <span>{formatGeo(hole)}</span>
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .fit {
    width: 1920px;
    height: 1080px;
    transform: scale(var(--s));
    transform-origin: 0 0;
  }

  .canvas {
    position: relative;
    width: 1920px;
    height: 1080px;
    overflow: hidden;
    transform-origin: 0 0;
    color: var(--color-text);
    font-family: var(--font-family);
  }

  .plate {
    position: absolute;
    inset: 0;
    background: var(--color-bg);
    -webkit-mask-image: var(--mask);
    mask-image: var(--mask);
  }

  .guide {
    position: absolute;
    outline: 2px dashed var(--color-gold);
    pointer-events: none;
  }

  .guide span {
    position: absolute;
    right: 0;
    bottom: 0;
    padding: 3px 7px;
    background: rgba(8, 13, 19, 0.9);
    color: var(--color-gold);
    font-family: var(--font-mono);
    font-size: 14px;
  }
</style>
