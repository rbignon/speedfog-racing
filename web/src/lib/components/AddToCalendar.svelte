<script lang="ts">
	let { scheduledAt, seedNumber = null, raceUrl }: {
		scheduledAt: string;
		seedNumber: string | null;
		raceUrl: string;
	} = $props();

	let open = $state(false);

	function toUtcString(date: Date): string {
		return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
	}

	function getTitle(): string {
		return seedNumber ? `SpeedFog Race #${seedNumber}` : 'SpeedFog Race';
	}

	function getEndDate(start: Date): Date {
		return new Date(start.getTime() + 60 * 60 * 1000);
	}

	function openGoogleCalendar() {
		const start = new Date(scheduledAt);
		const end = getEndDate(start);
		const params = new URLSearchParams({
			action: 'TEMPLATE',
			text: getTitle(),
			dates: `${toUtcString(start)}/${toUtcString(end)}`,
			details: raceUrl,
			sprop: `website:${raceUrl}`
		});
		window.open(`https://calendar.google.com/calendar/render?${params}`, '_blank');
		open = false;
	}

	function generateIcs(): string {
		const start = new Date(scheduledAt);
		const end = getEndDate(start);
		const uid = `${toUtcString(start)}-${encodeURIComponent(raceUrl)}@speedfog.racing`;
		return [
			'BEGIN:VCALENDAR',
			'VERSION:2.0',
			'PRODID:-//SpeedFog Racing//EN',
			'BEGIN:VEVENT',
			`UID:${uid}`,
			`DTSTART:${toUtcString(start)}`,
			`DTEND:${toUtcString(end)}`,
			`SUMMARY:${getTitle()}`,
			`DESCRIPTION:${raceUrl}`,
			`URL:${raceUrl}`,
			'END:VEVENT',
			'END:VCALENDAR'
		].join('\r\n') + '\r\n';
	}

	function downloadIcs() {
		const blob = new Blob([generateIcs()], { type: 'text/calendar;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'speedfog-race.ics';
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
		open = false;
	}

	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('.calendar-wrapper')) {
			open = false;
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape' && open) {
			open = false;
		}
	}
</script>

<svelte:document onclick={handleClickOutside} onkeydown={handleKeydown} />

<div class="calendar-wrapper">
	<button
		class="calendar-btn"
		title="Add to calendar"
		aria-expanded={open}
		aria-haspopup="true"
		onclick={() => (open = !open)}
	>
		<svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
			<path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clip-rule="evenodd" />
		</svg>
	</button>

	{#if open}
		<div class="dropdown">
			<button class="dropdown-item" onclick={openGoogleCalendar}>
				<svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
					<path d="M10 2a8 8 0 100 16 8 8 0 000-16zm1 4a1 1 0 10-2 0v4a1 1 0 00.293.707l2.5 2.5a1 1 0 101.414-1.414L11 9.586V6z" />
				</svg>
				Google Calendar
			</button>
			<button class="dropdown-item" onclick={downloadIcs}>
				<svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
					<path d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V7.414A2 2 0 0015.414 6L12 2.586A2 2 0 0010.586 2H6zm5 6a1 1 0 10-2 0v3.586l-1.293-1.293a1 1 0 10-1.414 1.414l3 3a1 1 0 001.414 0l3-3a1 1 0 00-1.414-1.414L11 11.586V8z" />
				</svg>
				Apple Calendar
			</button>
			<button class="dropdown-item" onclick={downloadIcs}>
				<svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
					<path fill-rule="evenodd" d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V7.414A2 2 0 0015.414 6L12 2.586A2 2 0 0010.586 2H6zm2 10a1 1 0 100 2h4a1 1 0 100-2H8zm0-3a1 1 0 100 2h4a1 1 0 100-2H8z" clip-rule="evenodd" />
				</svg>
				Outlook
			</button>
		</div>
	{/if}
</div>

<style>
	.calendar-wrapper {
		position: relative;
	}

	.calendar-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: all var(--transition);
	}

	.calendar-btn:hover {
		color: var(--color-gold);
		border-color: var(--color-gold);
	}

	.dropdown {
		position: absolute;
		top: calc(100% + 4px);
		right: 0;
		z-index: 100;
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 0.25rem;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
		min-width: 180px;
	}

	.dropdown-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		padding: 0.5rem 0.75rem;
		border: none;
		background: transparent;
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: background var(--transition);
		white-space: nowrap;
	}

	.dropdown-item:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-gold);
	}
</style>
