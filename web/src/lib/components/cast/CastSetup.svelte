<script lang="ts">
  import { onMount } from "svelte";
  import { copyToClipboard } from "$lib/utils/clipboard";
  import {
    fetchEvents,
    fetchEvent,
    type RaceDetail,
    type EventSummary,
    type EventStage,
  } from "$lib/api";
  import { sceneLayout, formatGeo, type CastSceneId } from "$lib/cast/layout";
  import { buildCastUrl, type CastUrlOpts } from "$lib/cast/urls";

  interface Props {
    race: RaceDetail;
    onClose: () => void;
  }

  let { race, onClose }: Props = $props();

  interface SceneOption {
    id: CastSceneId;
    focus?: number;
    label: string;
  }

  const SCENE_OPTIONS: SceneOption[] = [
    { id: "quad", label: "Quad" },
    { id: "focus", focus: 1, label: "Focus 1" },
    { id: "focus", focus: 2, label: "Focus 2" },
    { id: "focus", focus: 3, label: "Focus 3" },
    { id: "focus", focus: 4, label: "Focus 4" },
    { id: "metro", label: "Metro" },
    { id: "talk", label: "Talk" },
  ];

  interface StoredSettings {
    scene: CastSceneId;
    focusSlot: number;
    slots: (string | null)[];
    cams: number;
    caster1: string;
    caster2: string;
    delayS: number;
    eventSlug: string;
    stageKey: string;
  }

  /** Whoever joined earliest sits POV 1: `color_index` is assigned by the
   * server as max + 1 on join, so sorting by it is join order (see
   * `resolveSlots`'s own reasoning in cast/params.ts). Fixing the seats to
   * these usernames up front, rather than leaving them blank, keeps a
   * hole's runner stable even if a caster later reorders the field. */
  function joinOrderDefaults(): (string | null)[] {
    const ordered = [...race.participants].sort(
      (a, b) => a.color_index - b.color_index,
    );
    return [0, 1, 2, 3].map((i) => ordered[i]?.user.twitch_username ?? null);
  }

  function defaultSettings(): StoredSettings {
    return {
      scene: "quad",
      focusSlot: 1,
      slots: joinOrderDefaults(),
      cams: 2,
      caster1: race.casters[0]?.user.twitch_username ?? "",
      caster2: race.casters[1]?.user.twitch_username ?? "",
      delayS: 0,
      eventSlug: "",
      stageKey: "",
    };
  }

  const SCENE_IDS: CastSceneId[] = ["quad", "focus", "metro", "talk"];

  // A function, not a top-level const: `race` is a prop, and reading it
  // outside a closure would only ever capture its initial value.
  function storageKey(): string {
    return `cast-setup:${race.id}`;
  }

  /** A private window throws on any `localStorage` access, and the panel
   * must still open: every read and write here is wrapped. */
  function loadSettings(): StoredSettings {
    const fallback = defaultSettings();
    try {
      const raw = localStorage.getItem(storageKey());
      if (!raw) return fallback;
      const saved = JSON.parse(raw) as Partial<StoredSettings>;
      return {
        scene: SCENE_IDS.includes(saved.scene as CastSceneId)
          ? (saved.scene as CastSceneId)
          : fallback.scene,
        focusSlot:
          typeof saved.focusSlot === "number" &&
          saved.focusSlot >= 1 &&
          saved.focusSlot <= 4
            ? saved.focusSlot
            : fallback.focusSlot,
        slots:
          Array.isArray(saved.slots) && saved.slots.length === 4
            ? saved.slots
            : fallback.slots,
        cams:
          typeof saved.cams === "number" && saved.cams >= 0 && saved.cams <= 2
            ? saved.cams
            : fallback.cams,
        caster1:
          typeof saved.caster1 === "string" ? saved.caster1 : fallback.caster1,
        caster2:
          typeof saved.caster2 === "string" ? saved.caster2 : fallback.caster2,
        delayS:
          typeof saved.delayS === "number" ? saved.delayS : fallback.delayS,
        eventSlug:
          typeof saved.eventSlug === "string"
            ? saved.eventSlug
            : fallback.eventSlug,
        stageKey:
          typeof saved.stageKey === "string"
            ? saved.stageKey
            : fallback.stageKey,
      };
    } catch {
      return fallback;
    }
  }

  const initial = loadSettings();

  let scene = $state<CastSceneId>(initial.scene);
  let focusSlot = $state(initial.focusSlot);
  let slots = $state<(string | null)[]>(initial.slots);
  let slotErrors = $state<(string | null)[]>([null, null, null, null]);
  let cams = $state(initial.cams);
  let caster1 = $state(initial.caster1);
  let caster2 = $state(initial.caster2);
  let delayS = $state(initial.delayS);
  let eventSlug = $state(initial.eventSlug);
  let stageKey = $state(initial.stageKey);

  $effect(() => {
    const settings: StoredSettings = {
      scene,
      focusSlot,
      slots: [...slots],
      cams,
      caster1,
      caster2,
      delayS,
      eventSlug,
      stageKey,
    };
    try {
      localStorage.setItem(storageKey(), JSON.stringify(settings));
    } catch {
      // Private window or storage disabled: settings just don't persist.
    }
  });

  function selectScene(option: SceneOption) {
    scene = option.id;
    if (option.focus) focusSlot = option.focus;
  }

  /** Refuses to seat the same runner in two holes: the scenes seat by join
   * order when a hole is silent, and a duplicate would leave another
   * runner unshown instead of failing loudly. */
  function handleSlotChange(i: number, e: Event) {
    const target = e.currentTarget as HTMLSelectElement;
    const name = target.value || null;
    if (name) {
      const dupIndex = slots.findIndex(
        (s, j) =>
          j !== i && s !== null && s.toLowerCase() === name.toLowerCase(),
      );
      if (dupIndex !== -1) {
        slotErrors[i] = `Already seated in POV ${dupIndex + 1}.`;
        target.value = slots[i] ?? "";
        return;
      }
    }
    slotErrors[i] = null;
    slots[i] = name;
  }

  // The co-brand picker (fetchEvents returns slug + name, nothing a race
  // exposes client-side maps to). A failed fetch just leaves the list
  // empty: casting a race outside an event is the common case, not an
  // error.
  let events = $state<EventSummary[]>([]);
  onMount(() => {
    fetchEvents()
      .then((list) => (events = list))
      .catch(() => {});
  });

  // The talk scene's stage picker: only the chosen event's own stages are
  // valid, so this refetches whenever eventSlug changes.
  let stages = $state<EventStage[]>([]);
  $effect(() => {
    const slug = eventSlug;
    if (!slug) {
      stages = [];
      return;
    }
    let cancelled = false;
    fetchEvent(slug)
      .then((detail) => {
        if (!cancelled) stages = detail.stages;
      })
      .catch(() => {
        if (!cancelled) stages = [];
      });
    return () => {
      cancelled = true;
    };
  });

  function handleEventChange(e: Event) {
    eventSlug = (e.currentTarget as HTMLSelectElement).value;
    stageKey = "";
  }

  let origin = $derived(
    typeof window !== "undefined" ? window.location.origin : "",
  );

  let urlOpts = $derived<CastUrlOpts>({
    raceId: race.id,
    slots,
    cams,
    casters: [caster1 || null, caster2 || null],
    delayS,
    focus: focusSlot,
    event: eventSlug || null,
    eventSlug,
    stageKey,
  });

  let castUrl = $derived(buildCastUrl(origin, scene, urlOpts));
  let guidesUrl = $derived(
    `${castUrl}${castUrl.includes("?") ? "&" : "?"}guides=1`,
  );

  let layout = $derived(sceneLayout(scene, { cams, focus: focusSlot }));
  let positionLines = $derived(layout.holes.map(formatGeo));

  // Every race scene this race can show, plus the talk scene once the
  // caster has actually picked which stage it introduces: an unconfigured
  // talk URL would just point at a 404.
  let allUrls = $derived.by(() => {
    const lines = (["quad", "focus", "metro"] as CastSceneId[]).map((id) =>
      buildCastUrl(origin, id, urlOpts),
    );
    if (eventSlug && stageKey) {
      lines.push(buildCastUrl(origin, "talk", urlOpts));
    }
    return lines;
  });

  let urlCopied = $state(false);
  let allCopied = $state(false);

  async function copyUrl() {
    if (!(await copyToClipboard(castUrl))) return;
    urlCopied = true;
    setTimeout(() => (urlCopied = false), 2000);
  }

  async function copyAllUrls() {
    if (!(await copyToClipboard(allUrls.join("\n")))) return;
    allCopied = true;
    setTimeout(() => (allCopied = false), 2000);
  }
</script>

<div class="cast-setup">
  <div class="cast-setup-header">
    <h2>Cast Setup</h2>
    <button class="close-btn" onclick={onClose} aria-label="Close cast setup"
      >&times;</button
    >
  </div>

  <div class="preview-wrap">
    <!-- The real scene at its real URL, scaled to a third by CastPlate's
         own innerWidth/innerHeight sizing: this is the live race, not a
         drawing of it. It opens its own WebSocket connection, which is
         fine for a setup surface nobody keeps open for the whole race. -->
    <iframe
      class="preview"
      src={castUrl}
      width="640"
      height="360"
      title="Scene preview"
    ></iframe>
  </div>

  <div class="scene-picker">
    {#each SCENE_OPTIONS as option (option.label)}
      <button
        type="button"
        class="pill"
        class:active={scene === option.id &&
          (option.id !== "focus" || focusSlot === option.focus)}
        onclick={() => selectScene(option)}
      >
        {option.label}
      </button>
    {/each}
  </div>

  {#if scene !== "talk"}
    <div class="section">
      <h3>Hole assignment</h3>
      <div class="hole-grid">
        {#each [0, 1, 2, 3] as i (i)}
          <label class="field">
            <span>POV {i + 1}</span>
            <select
              value={slots[i] ?? ""}
              onchange={(e) => handleSlotChange(i, e)}
            >
              <option value="">(auto, join order)</option>
              {#each race.participants as p (p.id)}
                <option value={p.user.twitch_username}
                  >{p.user.twitch_display_name ||
                    p.user.twitch_username}</option
                >
              {/each}
            </select>
            {#if slotErrors[i]}
              <span class="field-error">{slotErrors[i]}</span>
            {/if}
          </label>
        {/each}
      </div>
    </div>
  {/if}

  <div class="section">
    <h3>Cams</h3>
    <div class="pill-group">
      {#each [0, 1, 2] as n (n)}
        <button
          type="button"
          class="pill"
          class:active={cams === n}
          onclick={() => (cams = n)}
        >
          {n}
        </button>
      {/each}
    </div>
    <label class="field">
      <span>Caster 1</span>
      <input type="text" bind:value={caster1} placeholder="twitch username" />
    </label>
    <label class="field">
      <span>Caster 2</span>
      <input type="text" bind:value={caster2} placeholder="twitch username" />
    </label>
  </div>

  <div class="section">
    <h3>Event</h3>
    <label class="field">
      <span>Co-brand</span>
      <select value={eventSlug} onchange={handleEventChange}>
        <option value="">None</option>
        {#each events as ev (ev.slug)}
          <option value={ev.slug}>{ev.name}</option>
        {/each}
      </select>
    </label>
    {#if scene === "talk"}
      <label class="field">
        <span>Stage</span>
        <select bind:value={stageKey} disabled={!eventSlug}>
          <option value="">Select a stage</option>
          {#each stages as st (st.key)}
            <option value={st.key}>{st.label}</option>
          {/each}
        </select>
      </label>
    {/if}
  </div>

  {#if scene !== "talk"}
    <div class="section">
      <h3>Delay</h3>
      <label class="field">
        <span>Seconds</span>
        <input type="number" min="0" max="60" bind:value={delayS} />
      </label>
    </div>
  {/if}

  <div class="section">
    <h3>URL</h3>
    <div class="url-row">
      <input type="text" readonly value={castUrl} class="url-input" />
      <button class="btn btn-primary" onclick={copyUrl}>
        {urlCopied ? "Copied!" : "Copy"}
      </button>
    </div>
    <button class="btn btn-outline" onclick={copyAllUrls}>
      {allCopied ? "Copied!" : "Copy all scene URLs"}
    </button>
  </div>

  <div class="section">
    <h3>OBS positions</h3>
    <p class="hint">
      Add a Browser source at 1920&times;1080 and place the video sources
      underneath at these positions.
    </p>
    <div class="positions">
      {#each positionLines as line (line)}
        <div class="position-row">{line}</div>
      {/each}
    </div>
    <a href={guidesUrl} target="_blank" rel="noopener noreferrer"
      >Open with position guides</a
    >
  </div>
</div>

<style>
  .cast-setup {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
  }

  .cast-setup-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }

  .cast-setup-header h2 {
    margin: 0;
    color: var(--color-gold);
    font-size: var(--font-size-lg);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--color-text-secondary);
    font-size: 1.5rem;
    cursor: pointer;
    padding: 0;
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .preview-wrap {
    margin-bottom: 1.25rem;
  }

  .preview {
    display: block;
    width: 640px;
    max-width: 100%;
    height: 360px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: #000;
  }

  .scene-picker,
  .pill-group {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 1.25rem;
  }

  .pill {
    padding: 0.35rem 0.8rem;
    border: 1px solid var(--color-border);
    border-radius: 999px;
    background: var(--color-bg);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    cursor: pointer;
  }

  .pill:hover {
    color: var(--color-text);
  }

  .pill.active {
    background: var(--color-gold);
    border-color: var(--color-gold);
    color: var(--color-bg);
  }

  .section {
    margin-bottom: 1.25rem;
  }

  .section:last-child {
    margin-bottom: 0;
  }

  .section h3 {
    margin: 0 0 0.5rem 0;
    font-size: var(--font-size-base);
    color: var(--color-text);
  }

  .hole-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.75rem;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin-bottom: 0.5rem;
  }

  .field:last-child {
    margin-bottom: 0;
  }

  .field-error {
    color: var(--color-danger);
    font-size: var(--font-size-xs);
  }

  .url-row {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }

  .url-input {
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    min-width: 0;
  }

  .positions {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.75rem;
    margin-bottom: 0.5rem;
  }

  .position-row {
    padding: 0.15rem 0;
  }

  .hint {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    margin: 0 0 0.5rem 0;
  }
</style>
