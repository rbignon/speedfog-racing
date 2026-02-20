# Custom DateTimePicker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace native `<input type="datetime-local">` with a custom calendar popup + time slot dropdown that matches the design system and handles timezones correctly.

**Architecture:** Single `DateTimePicker.svelte` component. Calendar popup with month grid for date, native `<select>` for 30-min time slots. All display in browser local timezone, all I/O in UTC ISO strings. No dependencies.

**Tech Stack:** SvelteKit 5 (runes), CSS custom properties from `GRAPHIC_CHARTER.md`, `Intl.DateTimeFormat` for locale-aware formatting and timezone detection.

---

## Task 1: Create DateTimePicker component — calendar logic and date display

\*\*Files:

- Create: `web/src/lib/components/DateTimePicker.svelte`

Step 1: Create the component with props, local state, and calendar grid logic

The component accepts `value` (ISO string or `''`), `onchange`, `min`, `disabled`, `placeholder`. Internal state tracks `viewYear`, `viewMonth` (for calendar navigation), `open` (popup toggle), and derived `selectedDate`/`selectedTime` from the value prop.

```svelte
<script lang="ts">
 interface Props {
  value?: string;
  onchange?: (iso: string) => void;
  min?: Date;
  disabled?: boolean;
  placeholder?: string;
 }

 let { value = '', onchange, min, disabled = false, placeholder = 'Pick a date' }: Props = $props();

 let open = $state(false);
 let containerEl: HTMLDivElement | undefined = $state();

 // Parse value (UTC ISO) into local date parts
 let selectedLocalDate: { year: number; month: number; day: number } | null = $derived.by(() => {
  if (!value) return null;
  const d = new Date(value);
  return { year: d.getFullYear(), month: d.getMonth(), day: d.getDate() };
 });

 let selectedTime: string = $derived.by(() => {
  if (!value) return '18:00';
  const d = new Date(value);
  const h = d.getHours().toString().padStart(2, '0');
  const m = (Math.floor(d.getMinutes() / 30) * 30).toString().padStart(2, '0');
  return `${h}:${m}`;
 });

 // Calendar view state — initialized to selected month or current month
 let viewYear = $state(selectedLocalDate?.year ?? new Date().getFullYear());
 let viewMonth = $state(selectedLocalDate?.month ?? new Date().getMonth());

 // Keep view in sync when value changes externally
 $effect(() => {
  if (selectedLocalDate) {
   viewYear = selectedLocalDate.year;
   viewMonth = selectedLocalDate.month;
  }
 });

 const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

 // Timezone label
 const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

 // Format selected date for display
 let displayDate = $derived.by(() => {
  if (!selectedLocalDate) return '';
  const d = new Date(selectedLocalDate.year, selectedLocalDate.month, selectedLocalDate.day);
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(d);
 });

 // Calendar grid: array of weeks, each week is array of { day, inMonth, date }
 let calendarWeeks = $derived.by(() => {
  const firstDay = new Date(viewYear, viewMonth, 1);
  const lastDay = new Date(viewYear, viewMonth + 1, 0);
  // Monday = 0 ... Sunday = 6
  let startDow = (firstDay.getDay() + 6) % 7;
  const totalDays = lastDay.getDate();

  const cells: { day: number; inMonth: boolean; year: number; month: number }[] = [];
  // Fill leading days from previous month
  const prevMonthLast = new Date(viewYear, viewMonth, 0).getDate();
  for (let i = startDow - 1; i >= 0; i--) {
   const pm = viewMonth === 0 ? 11 : viewMonth - 1;
   const py = viewMonth === 0 ? viewYear - 1 : viewYear;
   cells.push({ day: prevMonthLast - i, inMonth: false, year: py, month: pm });
  }
  // Current month days
  for (let d = 1; d <= totalDays; d++) {
   cells.push({ day: d, inMonth: true, year: viewYear, month: viewMonth });
  }
  // Fill trailing days
  const remaining = 7 - (cells.length % 7);
  if (remaining < 7) {
   const nm = viewMonth === 11 ? 0 : viewMonth + 1;
   const ny = viewMonth === 11 ? viewYear + 1 : viewYear;
   for (let d = 1; d <= remaining; d++) {
    cells.push({ day: d, inMonth: false, year: ny, month: nm });
   }
  }

  // Chunk into weeks
  const weeks: typeof cells[] = [];
  for (let i = 0; i < cells.length; i += 7) {
   weeks.push(cells.slice(i, i + 7));
  }
  return weeks;
 });

 // Min date parts (local) for comparison
 let minLocal = $derived.by(() => {
  if (!min) return null;
  return { year: min.getFullYear(), month: min.getMonth(), day: min.getDate(), hours: min.getHours(), minutes: min.getMinutes() };
 });

 function isDayDisabled(year: number, month: number, day: number): boolean {
  if (!minLocal) return false;
  const cellDate = new Date(year, month, day);
  const minDate = new Date(minLocal.year, minLocal.month, minLocal.day);
  return cellDate < minDate;
 }

 function isDaySelected(year: number, month: number, day: number): boolean {
  if (!selectedLocalDate) return false;
  return selectedLocalDate.year === year && selectedLocalDate.month === month && selectedLocalDate.day === day;
 }

 function isToday(year: number, month: number, day: number): boolean {
  const now = new Date();
  return now.getFullYear() === year && now.getMonth() === month && now.getDate() === day;
 }

 function prevMonth() {
  if (viewMonth === 0) { viewYear--; viewMonth = 11; }
  else { viewMonth--; }
 }

 function nextMonth() {
  if (viewMonth === 11) { viewYear++; viewMonth = 0; }
  else { viewMonth++; }
 }

 let viewMonthLabel = $derived(
  new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(viewYear, viewMonth, 1))
 );

 // Time slots
 let timeSlots = $derived.by(() => {
  const slots: string[] = [];
  for (let h = 0; h < 24; h++) {
   for (let m = 0; m < 60; m += 30) {
    const slot = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    // Filter past slots if selected date is the min date
    if (minLocal && selectedLocalDate &&
     selectedLocalDate.year === minLocal.year &&
     selectedLocalDate.month === minLocal.month &&
     selectedLocalDate.day === minLocal.day) {
     const slotMinutes = h * 60 + m;
     const minMinutes = minLocal.hours * 60 + minLocal.minutes;
     if (slotMinutes < minMinutes) continue;
    }
    slots.push(slot);
   }
  }
  return slots;
 });

 function emitChange(year: number, month: number, day: number, time: string) {
  const [hours, minutes] = time.split(':').map(Number);
  const local = new Date(year, month, day, hours, minutes, 0, 0);
  onchange?.(local.toISOString());
 }

 function selectDay(year: number, month: number, day: number) {
  // If current time is invalid for new date, snap to first valid slot
  let time = selectedTime;
  if (minLocal && year === minLocal.year && month === minLocal.month && day === minLocal.day) {
   const [h, m] = time.split(':').map(Number);
   const slotMin = h * 60 + m;
   const minMin = minLocal.hours * 60 + minLocal.minutes;
   if (slotMin < minMin) {
    // Snap to next valid 30-min slot
    const snapped = Math.ceil(minMin / 30) * 30;
    const sh = Math.floor(snapped / 60);
    const sm = snapped % 60;
    time = `${sh.toString().padStart(2, '0')}:${sm.toString().padStart(2, '0')}`;
   }
  }
  emitChange(year, month, day, time);
  open = false;
 }

 function handleTimeChange(e: Event) {
  const time = (e.target as HTMLSelectElement).value;
  if (!selectedLocalDate) return;
  emitChange(selectedLocalDate.year, selectedLocalDate.month, selectedLocalDate.day, time);
 }

 function handleClickOutside(e: MouseEvent) {
  if (containerEl && !containerEl.contains(e.target as Node)) {
   open = false;
  }
 }

 function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') open = false;
 }

 $effect(() => {
  if (open) {
   document.addEventListener('mousedown', handleClickOutside);
   document.addEventListener('keydown', handleKeydown);
   return () => {
    document.removeEventListener('mousedown', handleClickOutside);
    document.removeEventListener('keydown', handleKeydown);
   };
  }
 });
</script>

<div class="datetime-picker" bind:this={containerEl}>
 <div class="datetime-inputs">
  <button
   type="button"
   class="date-trigger"
   class:has-value={!!selectedLocalDate}
   onclick={() => { if (!disabled) open = !open; }}
   {disabled}
  >
   <svg class="calendar-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
    <path d="M5.75 2a.75.75 0 0 1 .75.75V4h7V2.75a.75.75 0 0 1 1.5 0V4h1.25A1.75 1.75 0 0 1 18 5.75v10.5A1.75 1.75 0 0 1 16.25 18H3.75A1.75 1.75 0 0 1 2 16.25V5.75A1.75 1.75 0 0 1 3.75 4H5V2.75A.75.75 0 0 1 5.75 2Zm-2 5.5v8.75c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25V7.5H3.75Z" />
   </svg>
   {#if displayDate}
    {displayDate}
   {:else}
    <span class="placeholder">{placeholder}</span>
   {/if}
  </button>

  {#if selectedLocalDate}
   <select
    class="time-select"
    value={selectedTime}
    onchange={handleTimeChange}
    {disabled}
   >
    {#each timeSlots as slot}
     <option value={slot}>{slot}</option>
    {/each}
   </select>
  {/if}
 </div>

 {#if open}
  <div class="calendar-popup">
   <div class="calendar-header">
    <button type="button" class="nav-btn" onclick={prevMonth}>&lsaquo;</button>
    <span class="month-label">{viewMonthLabel}</span>
    <button type="button" class="nav-btn" onclick={nextMonth}>&rsaquo;</button>
   </div>
   <div class="calendar-grid">
    {#each DAYS as dayName}
     <span class="day-header">{dayName}</span>
    {/each}
    {#each calendarWeeks as week}
     {#each week as cell}
      {@const cellDisabled = !cell.inMonth || isDayDisabled(cell.year, cell.month, cell.day)}
      <button
       type="button"
       class="day-cell"
       class:other-month={!cell.inMonth}
       class:selected={isDaySelected(cell.year, cell.month, cell.day)}
       class:today={isToday(cell.year, cell.month, cell.day)}
       class:disabled={cellDisabled}
       onclick={() => { if (!cellDisabled) selectDay(cell.year, cell.month, cell.day); }}
       disabled={cellDisabled}
      >
       {cell.day}
      </button>
     {/each}
    {/each}
   </div>
  </div>
 {/if}

 <span class="timezone-label">{timezone}</span>
</div>

<style>
 .datetime-picker {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  gap: 0.25rem;
 }

 .datetime-inputs {
  display: flex;
  gap: 0.5rem;
  align-items: center;
 }

 .date-trigger {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: 1rem;
  cursor: pointer;
  transition: border-color var(--transition);
  min-width: 180px;
  text-align: left;
 }

 .date-trigger:hover:not(:disabled) {
  border-color: var(--color-purple);
 }

 .date-trigger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
 }

 .date-trigger .placeholder {
  color: var(--color-text-disabled);
 }

 .calendar-icon {
  color: var(--color-text-secondary);
  flex-shrink: 0;
 }

 .time-select {
  padding: 0.75rem 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: 1rem;
  cursor: pointer;
  transition: border-color var(--transition);
  appearance: auto;
 }

 .time-select:hover:not(:disabled) {
  border-color: var(--color-purple);
 }

 .time-select:focus {
  outline: none;
  border-color: var(--color-purple);
 }

 .time-select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
 }

 .calendar-popup {
  position: absolute;
  top: calc(100% - 1rem);
  left: 0;
  z-index: 100;
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 0.75rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  min-width: 280px;
 }

 .calendar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
 }

 .nav-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 1.25rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: var(--radius-sm);
  line-height: 1;
  transition: color var(--transition), background-color var(--transition);
 }

 .nav-btn:hover {
  color: var(--color-text);
  background: var(--color-surface);
 }

 .month-label {
  font-weight: 600;
  font-size: var(--font-size-base);
  color: var(--color-text);
 }

 .calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  text-align: center;
 }

 .day-header {
  font-size: var(--font-size-xs);
  font-weight: 500;
  color: var(--color-text-disabled);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.25rem 0;
 }

 .day-cell {
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  font-variant-numeric: tabular-nums;
  padding: 0.35rem 0;
  cursor: pointer;
  transition: background-color var(--transition), border-color var(--transition);
 }

 .day-cell:hover:not(:disabled):not(.selected) {
  background: var(--color-surface);
 }

 .day-cell.other-month {
  color: var(--color-text-disabled);
  opacity: 0.4;
 }

 .day-cell.today {
  border-color: var(--color-border);
 }

 .day-cell.selected {
  background: var(--color-purple);
  color: white;
  font-weight: 600;
 }

 .day-cell.disabled,
 .day-cell:disabled {
  color: var(--color-text-disabled);
  opacity: 0.3;
  cursor: not-allowed;
 }

 .timezone-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-disabled);
 }
</style>
```

Step 2: Verify it builds

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx svelte-check --tsconfig ./tsconfig.json`
Expected: No errors in `DateTimePicker.svelte`

Step 3: Commit

```bash
git add web/src/lib/components/DateTimePicker.svelte
git commit -m "feat(web): add custom DateTimePicker component

Calendar popup for date selection, native select for 30-min time slots.
Displays in browser local timezone, emits UTC ISO strings."
```

---

## Task 2: Integrate DateTimePicker in race creation page

\*\*Files:

- Modify: `web/src/routes/race/new/+page.svelte`

Step 1: Replace the datetime-local input with DateTimePicker

In the `<script>` block, add the import:

```ts
import DateTimePicker from "$lib/components/DateTimePicker.svelte";
```

Replace the form group (lines 124-136):

```svelte
<div class="form-group">
 <label for="scheduled">Scheduled Time <span class="optional">(optional)</span></label>
 <DateTimePicker
  value={scheduledAt}
  onchange={(iso) => (scheduledAt = iso)}
  min={new Date()}
  disabled={creating}
  placeholder="Pick a date"
 />
 <p class="hint">
  Leave empty if you don't have a fixed start time yet.
 </p>
</div>
```

In `handleSubmit`, simplify the ISO conversion — `scheduledAt` is already ISO from the component:

```ts
const isoScheduled = scheduledAt || null;
```

Step 2: Remove dead CSS

Delete these CSS rules that targeted the old native input:

- `input[type='datetime-local']` block (lines 354-362)
- `input[type='datetime-local']:focus` block (lines 364-367)
- Remove `input[type='datetime-local']:disabled` from the disabled rule (line 349) — keep only `input[type='text']:disabled`

Step 3: Verify it builds

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx svelte-check --tsconfig ./tsconfig.json`
Expected: No errors

Step 4: Commit

```bash
git add web/src/routes/race/new/+page.svelte
git commit -m "feat(web): use DateTimePicker in race creation form

Replaces native datetime-local input. Removes dead CSS."
```

---

## Task 3: Integrate DateTimePicker in race detail sidebar

\*\*Files:

- Modify: `web/src/routes/race/[id]/+page.svelte`

Step 1: Add import and replace the datetime-local input

Add to imports:

```ts
import DateTimePicker from "$lib/components/DateTimePicker.svelte";
```

Step 2: Simplify `startEditSchedule()`

Replace the current function (lines 257-269) with:

```ts
function startEditSchedule() {
  scheduleInput = initialRace.scheduled_at ?? "";
  scheduleError = null;
  editingSchedule = true;
}
```

No more `getTimezoneOffset` math — `scheduled_at` is already ISO UTC, which is what `DateTimePicker` expects.

Step 3: Simplify `saveSchedule()`

Replace the current function (lines 271-284) with:

```ts
async function saveSchedule() {
  scheduleSaving = true;
  scheduleError = null;
  try {
    const scheduled = scheduleInput || null;
    await updateRace(initialRace.id, { scheduled_at: scheduled });
    initialRace = await fetchRace(initialRace.id);
    editingSchedule = false;
  } catch (e) {
    scheduleError = e instanceof Error ? e.message : "Failed to update";
  } finally {
    scheduleSaving = false;
  }
}
```

No more `new Date(scheduleInput).toISOString()` — `scheduleInput` is already ISO UTC.

Step 4: Replace the template

Replace the `<input type="datetime-local" ...>` block (lines 604-614) with:

```svelte
<DateTimePicker
 value={scheduleInput}
 onchange={(iso) => (scheduleInput = iso)}
 min={new Date()}
 disabled={scheduleSaving}
/>
```

Step 5: Clean up CSS

Remove these CSS rules that targeted the old input:

- `.schedule-edit input` (lines 913-921)
- `.schedule-edit input:focus` (lines 923-926)

Step 6: Verify it builds

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx svelte-check --tsconfig ./tsconfig.json`
Expected: No errors

Step 7: Commit

```bash
git add web/src/routes/race/[id]/+page.svelte
git commit -m "feat(web): use DateTimePicker in race detail sidebar

Replaces native datetime-local input. Simplifies schedule edit
functions by removing manual timezone offset math."
```

---

## Task 4: Manual testing and visual verification

Step 1: Start dev server

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run dev`

Step 2: Test in browser

Verify in the browser at `http://localhost:5173`:

1. **Race creation page** (`/race/new`):
   - Date button shows placeholder when empty
   - Click opens calendar popup
   - Navigate months with arrows
   - Past days are grayed out
   - Click a day → popup closes, date shows formatted, time select appears defaulting to 18:00
   - Change time via select dropdown
   - Timezone label shows below (e.g., "Europe/Paris")
   - Submit creates race with correct scheduled time

2. **Race detail sidebar** (any draft race):
   - Click "Edit" or "Set time" → DateTimePicker appears
   - If race had a scheduled_at, it's pre-filled
   - Save/Cancel work correctly

Step 3: Verify timezone correctness

- Pick a date/time, check browser console: the ISO string emitted should be offset from local time by your timezone offset
- Example: "Feb 20, 18:00" in Europe/Paris (UTC+1) → `2026-02-20T17:00:00.000Z`
