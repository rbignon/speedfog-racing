<script lang="ts">
  import { statusLabel } from "$lib/format";

  interface Props {
    status: string;
  }

  let { status }: Props = $props();
</script>

<div class="race-status">
  <span class="signal signal-{status}">{statusLabel(status)}</span>
</div>

<style>
  .race-status {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
</style>
