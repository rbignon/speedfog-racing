<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { exchangeAuthCode } from '$lib/api';

	let { data } = $props();

	onMount(async () => {
		if (data.code) {
			try {
				const token = await exchangeAuthCode(data.code);
				const success = await auth.login(token);
				if (success) {
					const redirect = sessionStorage.getItem('redirect_after_login');
					sessionStorage.removeItem('redirect_after_login');
					goto(redirect?.startsWith('/') && !redirect.startsWith('//') ? redirect : '/dashboard');
				} else {
					goto('/?error=invalid_token');
				}
			} catch {
				goto('/?error=invalid_code');
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
		color: var(--color-text-secondary);
	}
</style>
