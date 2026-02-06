<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';

	let { data } = $props();

	onMount(async () => {
		if (data.token) {
			const success = await auth.login(data.token);
			if (success) {
				const redirect = sessionStorage.getItem('redirect_after_login');
				sessionStorage.removeItem('redirect_after_login');
				goto(redirect || '/');
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
