<script lang="ts">
  import { parseEmphasis } from "$lib/content/emphasis";

  interface Props {
    text: string;
  }

  let { text }: Props = $props();

  const segments = $derived(parseEmphasis(text));
</script>

<!-- Single line, prettier-ignore: a line break inside the blocks would render
     as a stray space between segments (visible before punctuation). -->
<!-- prettier-ignore -->
{#each segments as segment}{#if segment.bold}<strong>{segment.text}</strong>{:else}{segment.text}{/if}{/each}
