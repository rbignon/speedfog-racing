<script lang="ts">
	interface Props {
		status: string;
	}

	let { status }: Props = $props();

	function getStatusLabel(s: string): string {
		switch (s) {
			case 'draft':
				return 'Draft';
			case 'open':
				return 'Open';
			case 'running':
				return 'Live';
			case 'finished':
				return 'Finished';
			default:
				return s;
		}
	}
</script>

<div class="race-status">
	<span class="badge badge-{status}">{getStatusLabel(status)}</span>
</div>

<style>
	.race-status {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}
</style>
