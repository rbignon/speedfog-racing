<script lang="ts">
  import type { Snippet } from "svelte";
  import {
    CANVAS,
    sceneLayout,
    maskDataUri,
    formatGeo,
    type CastSceneId,
  } from "$lib/cast/layout";

  interface Props {
    scene: CastSceneId;
    focus?: number;
    cams?: number;
    guides?: boolean;
    children: Snippet;
  }

  let {
    scene,
    focus = 1,
    cams = 2,
    guides = false,
    children,
  }: Props = $props();

  let layout = $derived(sceneLayout(scene, { focus, cams }));
  // The map is drawn by the page: piercing the plate there would cut a hole
  // in the very thing it displays.
  let pierced = $derived(layout.holes.filter((h) => h.role !== "map"));
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
