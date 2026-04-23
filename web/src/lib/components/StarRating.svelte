<script lang="ts">
	interface Props {
		value: number | null;
		onChange: (v: number) => void;
		size?: number;
	}

	let { value = $bindable(null), onChange, size = 28 }: Props = $props();

	let hovered: number | null = $state(null);

	function starClass(i: number): string {
		const v = hovered ?? value ?? 0;
		return i <= v ? 'star active' : 'star';
	}
</script>

<div class="stars" role="radiogroup" aria-label="Rating">
	{#each [1, 2, 3, 4, 5] as i (i)}
		<button
			type="button"
			class={starClass(i)}
			style="width:{size}px;height:{size}px;font-size:{size}px"
			aria-label={`${i} star${i > 1 ? 's' : ''}`}
			aria-pressed={value === i}
			onclick={() => onChange(i)}
			onmouseenter={() => (hovered = i)}
			onmouseleave={() => (hovered = null)}
		>
			★
		</button>
	{/each}
</div>

<style>
	.stars {
		display: inline-flex;
		gap: 4px;
	}

	.star {
		background: transparent;
		border: none;
		color: var(--color-text-disabled);
		cursor: pointer;
		padding: 0;
		line-height: 1;
	}

	.star.active {
		color: var(--color-gold);
	}

	.star:focus-visible {
		outline: 2px solid currentColor;
	}
</style>
