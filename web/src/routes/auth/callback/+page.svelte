<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { login } from '$lib/stores/auth';

	let { data } = $props();

	onMount(async () => {
		if (data.token) {
			const success = await login(data.token);
			if (success) {
				goto('/');
			} else {
				goto('/?error=invalid_token');
			}
		}
	});
</script>

<div class="callback">
	<p>Logging in...</p>
</div>

<style>
	.callback {
		display: flex;
		justify-content: center;
		align-items: center;
		min-height: 100vh;
		font-size: 1.2rem;
	}
</style>
