<script lang="ts">
	interface Props {
		href: string;
		small?: boolean;
		onclick?: (e: MouseEvent) => void;
	}

	let { href, small = false, onclick }: Props = $props();
</script>

<a
	{href}
	target="_blank"
	rel="noopener noreferrer"
	class="live-badge"
	class:small
	title="Watch live on Twitch"
	{onclick}
>LIVE</a>

<style>
	.live-badge {
		font-size: 0.6rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #fff;
		background: #e91916;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		text-decoration: none;
		flex-shrink: 0;
		animation: pulse-live 2s ease-in-out infinite;
	}

	.live-badge.small {
		font-size: 0.55rem;
		padding: 0.05rem 0.3rem;
		border-radius: 2px;
		align-self: center;
	}

	@keyframes pulse-live {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.7;
		}
	}
</style>
