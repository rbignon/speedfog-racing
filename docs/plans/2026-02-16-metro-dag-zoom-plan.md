<!-- markdownlint-disable MD001 MD029 MD036 -->

# MetroDag Zoom/Pan Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add zoom/pan to MetroDagLive, MetroDagProgressive, and MetroDagResults via a shared wrapper component.

**Architecture:** A new `ZoomableSvg.svelte` wraps the SVG content in a `<g transform>` for zoom/pan. Mouse wheel zooms centered on cursor, pointer drag pans, touch pinch-to-zoom. A reset button appears when zoomed/panned. Each MetroDag component delegates its SVG container to ZoomableSvg while keeping all drawing logic unchanged.

**Tech Stack:** SvelteKit 5 (runes), SVG transforms, Pointer Events API

**Design doc:** `docs/plans/2026-02-16-metro-dag-zoom-design.md`

---

### Task 1: Create ZoomableSvg component

**Files:**

- Create: `web/src/lib/dag/ZoomableSvg.svelte`

**Step 1: Create the component**

Create `web/src/lib/dag/ZoomableSvg.svelte` with the full implementation:

```svelte
<script lang="ts">
 interface Props {
  width: number;
  height: number;
  minZoom?: number;
  maxZoom?: number;
  transparent?: boolean;
  children: import('svelte').Snippet;
 }

 let {
  width,
  height,
  minZoom = 0.5,
  maxZoom = 3,
  transparent = false,
  children
 }: Props = $props();

 let svgEl: SVGSVGElement | undefined = $state();
 let zoom = $state(1);
 let panX = $state(0);
 let panY = $state(0);
 let isDragging = $state(false);
 let isAnimating = $state(false);

 let isTransformed = $derived(zoom !== 1 || panX !== 0 || panY !== 0);

 // --- Coordinate helpers ---

 function screenToSvg(clientX: number, clientY: number): { x: number; y: number } | null {
  if (!svgEl) return null;
  const ctm = svgEl.getScreenCTM();
  if (!ctm) return null;
  return {
   x: (clientX - ctm.e) / ctm.a,
   y: (clientY - ctm.f) / ctm.d
  };
 }

 function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
 }

 function clampPan(px: number, py: number, z: number): [number, number] {
  const margin = 0.25;
  return [
   clamp(px, -(width * z - width * margin), width * (1 - margin)),
   clamp(py, -(height * z - height * margin), height * (1 - margin))
  ];
 }

 // --- Wheel zoom ---

 function onWheel(e: WheelEvent) {
  e.preventDefault();
  const point = screenToSvg(e.clientX, e.clientY);
  if (!point) return;

  const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
  const newZoom = clamp(zoom * factor, minZoom, maxZoom);

  const contentX = (point.x - panX) / zoom;
  const contentY = (point.y - panY) / zoom;

  const [cx, cy] = clampPan(point.x - contentX * newZoom, point.y - contentY * newZoom, newZoom);
  zoom = newZoom;
  panX = cx;
  panY = cy;
 }

 // --- Pointer pan + pinch ---

 let pointers = new Map<number, PointerEvent>();
 let dragStart = { clientX: 0, clientY: 0, panX: 0, panY: 0 };
 let pinchStartDist = 0;
 let pinchStartZoom = 1;

 function onPointerDown(e: PointerEvent) {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  pointers.set(e.pointerId, e);

  if (e.pointerType === 'mouse') {
   (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }

  if (pointers.size === 1) {
   isDragging = true;
   dragStart = { clientX: e.clientX, clientY: e.clientY, panX, panY };
  } else if (pointers.size === 2) {
   isDragging = false;
   const [a, b] = [...pointers.values()];
   pinchStartDist = Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
   pinchStartZoom = zoom;
  }
 }

 function onPointerMove(e: PointerEvent) {
  pointers.set(e.pointerId, e);

  if (pointers.size === 1 && isDragging && svgEl) {
   const ctm = svgEl.getScreenCTM();
   if (!ctm) return;
   const dx = (e.clientX - dragStart.clientX) / ctm.a;
   const dy = (e.clientY - dragStart.clientY) / ctm.d;
   const [cx, cy] = clampPan(dragStart.panX + dx, dragStart.panY + dy, zoom);
   panX = cx;
   panY = cy;
  } else if (pointers.size === 2) {
   const [a, b] = [...pointers.values()];
   const dist = Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
   if (pinchStartDist > 0) {
    const center = screenToSvg((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
    if (!center) return;
    const newZoom = clamp(pinchStartZoom * (dist / pinchStartDist), minZoom, maxZoom);
    const contentX = (center.x - panX) / zoom;
    const contentY = (center.y - panY) / zoom;
    const [cx, cy] = clampPan(
     center.x - contentX * newZoom,
     center.y - contentY * newZoom,
     newZoom
    );
    zoom = newZoom;
    panX = cx;
    panY = cy;
   }
  }
 }

 function onPointerUp(e: PointerEvent) {
  pointers.delete(e.pointerId);
  if (pointers.size < 2) pinchStartDist = 0;
  if (pointers.size === 0) isDragging = false;
 }

 // --- Reset ---

 function resetZoom() {
  isAnimating = true;
  zoom = 1;
  panX = 0;
  panY = 0;
  setTimeout(() => (isAnimating = false), 300);
 }
</script>

<div class="zoomable-container" class:transparent>
 {#if width > 0 && height > 0}
  <svg
   bind:this={svgEl}
   viewBox="0 0 {width} {height}"
   preserveAspectRatio="xMidYMid meet"
   class="zoomable-svg"
   class:dragging={isDragging}
   onwheel={onWheel}
   onpointerdown={onPointerDown}
   onpointermove={onPointerMove}
   onpointerup={onPointerUp}
   onpointerleave={onPointerUp}
  >
   <g
    transform="translate({panX},{panY}) scale({zoom})"
    class:animate-transform={isAnimating}
   >
    {@render children()}
   </g>
  </svg>
 {/if}
 {#if isTransformed}
  <button class="zoom-reset" onclick={resetZoom} title="Reset zoom">
   <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
    <path
     d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 1 1 .908-.418A6 6 0 1 1 8 2v1z"
    />
    <path
     d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966a.25.25 0 0 1 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z"
    />
   </svg>
  </button>
 {/if}
</div>

<style>
 .zoomable-container {
  position: relative;
  width: 100%;
  background: var(--color-surface, #1a1a2e);
  border-radius: var(--radius-lg, 8px);
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
 }

 .zoomable-container.transparent {
  background: transparent;
  border-radius: 0;
 }

 .zoomable-svg {
  display: block;
  width: 100%;
  min-width: 600px;
  cursor: grab;
  touch-action: none;
  user-select: none;
 }

 .zoomable-svg.dragging {
  cursor: grabbing;
 }

 .animate-transform {
  transition: transform 0.3s ease;
 }

 .zoom-reset {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(26, 26, 46, 0.7);
  border: 1px solid rgba(212, 168, 68, 0.3);
  border-radius: 4px;
  color: #999;
  cursor: pointer;
  opacity: 0.6;
  transition:
   opacity 0.15s ease,
   color 0.15s ease;
 }

 .zoom-reset:hover {
  opacity: 1;
  color: #d4a844;
 }
</style>
```

**Key design decisions:**

- `touch-action: none` on SVG prevents browser scroll/pinch, enabling custom handling
- Pointer Events API handles both mouse and touch (no separate touch handlers)
- `setPointerCapture` only for mouse (keeps drag working when cursor leaves SVG)
- `getScreenCTM()` handles coordinate conversion including `preserveAspectRatio` scaling
- Pan clamping ensures 25% of content stays visible
- `isAnimating` flag temporarily enables CSS transition for smooth reset, disabled during interaction

**Step 2: Run type check**

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: No errors related to ZoomableSvg (file isn't imported yet, just syntax check)

**Step 3: Commit**

```bash
git add web/src/lib/dag/ZoomableSvg.svelte
git commit -m "feat(web): add ZoomableSvg wrapper component for DAG zoom/pan"
```

---

### Task 2: Export ZoomableSvg from barrel

**Files:**

- Modify: `web/src/lib/dag/index.ts`

**Step 1: Add export**

Add after the MetroDagResults export line:

```ts
export { default as ZoomableSvg } from "./ZoomableSvg.svelte";
```

**Step 2: Commit**

```bash
git add web/src/lib/dag/index.ts
git commit -m "feat(web): export ZoomableSvg from dag barrel"
```

---

### Task 3: Integrate ZoomableSvg into MetroDagLive

**Files:**

- Modify: `web/src/lib/dag/MetroDagLive.svelte`

**Step 1: Replace container and SVG with ZoomableSvg**

In MetroDagLive.svelte:

1. Add import: `import ZoomableSvg from './ZoomableSvg.svelte';`
2. Replace the template. The current structure is:

```svelte
<div class="metro-dag-container">
  {#if layout.nodes.length > 0}
    <svg viewBox="0 0 {layout.width} {layout.height}" width="100%" preserveAspectRatio="xMidYMid meet" class="metro-dag-svg">
      <defs>...</defs>
      <!-- edges, nodes, player dots -->
    </svg>
  {/if}
</div>
```

Replace with:

```svelte
{#if layout.nodes.length > 0}
  <ZoomableSvg width={layout.width} height={layout.height}>
    <defs>...</defs>
    <!-- edges, nodes, player dots (unchanged) -->
  </ZoomableSvg>
{/if}
```

3. Remove these CSS rules from `<style>` (now handled by ZoomableSvg):

```css
.metro-dag-container { ... }
.metro-dag-svg { ... }
```

4. Keep these CSS rules (they apply to elements rendered by this component):

```css
.dag-label { ... }
.dag-node { ... }
.dag-node-shape { ... }
.dag-node:hover .dag-node-shape { ... }
.player-dot { ... }
```

**Step 2: Run type check**

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: PASS

**Step 3: Commit**

```bash
git add web/src/lib/dag/MetroDagLive.svelte
git commit -m "feat(web): integrate ZoomableSvg into MetroDagLive"
```

---

### Task 4: Integrate ZoomableSvg into MetroDagProgressive

**Files:**

- Modify: `web/src/lib/dag/MetroDagProgressive.svelte`

**Step 1: Replace container and SVG with ZoomableSvg**

Same pattern as Task 3:

1. Add import: `import ZoomableSvg from './ZoomableSvg.svelte';`
2. Replace `<div class="metro-dag-container">` + `<svg ...>` wrapper with `<ZoomableSvg>`:

```svelte
{#if layout.nodes.length > 0}
  <ZoomableSvg width={layout.width} height={layout.height}>
    <defs>...</defs>
    <!-- edges, nodes, player dot (unchanged) -->
  </ZoomableSvg>
{/if}
```

3. Remove `.metro-dag-container` and `.metro-dag-svg` from `<style>`.
4. Keep `.dag-label`, `.dag-node`, `.dag-node-shape`, `.dag-node:hover .dag-node-shape`, `.player-dot` styles.

**Step 2: Run type check**

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: PASS

**Step 3: Commit**

```bash
git add web/src/lib/dag/MetroDagProgressive.svelte
git commit -m "feat(web): integrate ZoomableSvg into MetroDagProgressive"
```

---

### Task 5: Integrate ZoomableSvg into MetroDagResults

**Files:**

- Modify: `web/src/lib/dag/MetroDagResults.svelte`

**Step 1: Replace container and SVG with ZoomableSvg**

This component has an extra `transparent` prop that affects container background and label stroke.

1. Add import: `import ZoomableSvg from './ZoomableSvg.svelte';`
2. Replace the template:

```svelte
{#if layout.nodes.length > 0}
  <ZoomableSvg width={layout.width} height={layout.height} {transparent}>
    <defs>...</defs>
    <!-- edges, player paths, nodes, final dots (unchanged) -->
  </ZoomableSvg>
{/if}
```

3. For label stroke in transparent mode: the current `.metro-dag-container.transparent .dag-label` selector won't work because `.metro-dag-container` is now inside ZoomableSvg. Replace with a direct class on the text elements.

Change each `<text ... class="dag-label" ...>` to:

```svelte
<text ... class="dag-label" class:transparent-label={transparent} ...>
```

4. Update `<style>`:

Remove:

```css
.metro-dag-container { ... }
.metro-dag-container.transparent { ... }
.metro-dag-container.transparent .dag-label { ... }
.metro-dag-svg { ... }
```

Add:

```css
.transparent-label {
  stroke: transparent;
}
```

Keep `.dag-label`, `.dag-node`, `.dag-node-shape`, `.dag-node:hover .dag-node-shape`, `.player-dot`.

**Step 2: Run type check**

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: PASS

**Step 3: Commit**

```bash
git add web/src/lib/dag/MetroDagResults.svelte
git commit -m "feat(web): integrate ZoomableSvg into MetroDagResults"
```

---

### Task 6: Type check, lint, and verify

**Step 1: Full type check**

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: PASS with no new errors

**Step 2: Lint**

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run lint`
Expected: PASS (pre-existing issues only)

**Step 3: Visual verification checklist**

Start dev server: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run dev`

Verify on each page that uses the affected components:

- `/race/[id]` (running race) — MetroDagProgressive / MetroDagResults
- `/race/[id]` (finished race) — MetroDagResults
- `/training/[id]` (training) — MetroDagLive / MetroDagProgressive / MetroDagResults
- `/overlay/race/[id]/dag` (OBS overlay) — MetroDagResults with transparent

For each, verify:

- [ ] DAG renders correctly at default zoom
- [ ] Mouse wheel zooms centered on cursor
- [ ] Click + drag pans the view
- [ ] Reset button appears when zoomed/panned
- [ ] Reset button returns to default view with smooth transition
- [ ] Content stays partially visible (can't pan off-screen entirely)
- [ ] Node hover effects still work
- [ ] Player dots animate correctly
- [ ] Labels readable at various zoom levels
- [ ] OBS overlay: transparent background preserved

**Step 4: Final commit (if any fixes needed)**

---

## Notes

- **No unit tests**: ZoomableSvg is a purely visual/interactive component. Meaningful testing requires a browser (Playwright). Type checking + manual verification is sufficient for this scope.
- **Wheel event passive**: Svelte 5 `onwheel` handlers are active (non-passive) on SVG elements, so `e.preventDefault()` works. If scroll-through issues appear on some browsers, add a Svelte action with explicit `{ passive: false }`.
- **Touch-action: none**: Prevents browser scroll/pinch on the DAG area. On mobile, users scroll around the DAG, not through it. The DAG is typically 200-400px tall so this is acceptable.
- **MetroDagAnimated and MetroDag (static)**: Excluded from this change per design scope.
