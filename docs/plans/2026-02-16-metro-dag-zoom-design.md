# MetroDag Zoom/Pan Design

## Goal

Add zoom in/out and pan to MetroDagLive, MetroDagProgressive, and MetroDagResults.

## Approach

**Wrapper component** (`ZoomableSvg.svelte`) that encapsulates the SVG element and applies zoom/pan via a `<g transform>` group. Each MetroDag component delegates its SVG rendering to this wrapper while keeping its own drawing logic unchanged.

## Scope

- MetroDagLive, MetroDagProgressive, MetroDagResults only
- MetroDag (about), MetroDagAnimated (hero), MetroDagBlurred excluded

## Component Interface

```svelte
<ZoomableSvg width={layout.width} height={layout.height}>
  <!-- SVG content: edges, nodes, labels, player dots -->
</ZoomableSvg>
```

### Props

| Prop    | Type   | Default  | Description                    |
| ------- | ------ | -------- | ------------------------------ |
| width   | number | required | Layout width for viewBox       |
| height  | number | required | Layout height for viewBox      |
| minZoom | number | 0.5      | Minimum zoom level             |
| maxZoom | number | 3        | Maximum zoom level             |
| class   | string | ""       | Extra CSS classes on container |

## Architecture

```
<div class="zoomable-container">        ← positioned relative, overflow hidden
  <svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">
    <g transform="translate({panX},{panY}) scale({zoom})">
      <slot />                           ← MetroDag content (edges, nodes, labels, defs)
    </g>
  </svg>
  <button class="zoom-reset">           ← HTML overlay, visible when zoomed/panned
</div>
```

## Interactions

| Gesture                 | Action                                                |
| ----------------------- | ----------------------------------------------------- |
| Wheel on DAG            | Zoom centered on cursor                               |
| Click + drag            | Pan                                                   |
| Touch pinch (2 fingers) | Zoom centered between fingers                         |
| Touch drag (1 finger)   | Pan                                                   |
| Reset button            | Return to zoom=1, pan=(0,0) with 0.3s ease transition |

### Zoom centered on cursor

When zooming, the point under the cursor stays fixed. Pan is adjusted alongside scale:

```
newZoom = clamp(zoom * factor, minZoom, maxZoom)
panX = cursorX - (cursorX - panX) * (newZoom / zoom)
panY = cursorY - (cursorY - panY) * (newZoom / zoom)
```

### Pan clamping

Pan is clamped so the DAG content remains partially visible. Cannot scroll the entire DAG out of view.

### Transitions

- Reset: `transform 0.3s ease` (temporarily enabled)
- Manual interaction: no transition (immediate response)

## Cursor

- Default on DAG: `cursor: grab`
- During drag: `cursor: grabbing`

## Reset Button

- Position: top-right corner of container, HTML overlay
- Visible only when `zoom !== 1 || panX !== 0 || panY !== 0`
- Semi-transparent, fully opaque on hover
- Style consistent with graphic charter

## Impact on Existing Components

Each MetroDag (Live, Progressive, Results):

- **Remove**: own `<svg>`, `.metro-dag-container` div, `overflow-x: auto` styles
- **Keep**: all SVG content rendering (edges, nodes, labels, dots, filters, defs)
- **Add**: `<ZoomableSvg>` wrapper around content

SVG `<defs>` (filters, gradients) stay inside the slot as children of the `<g>` — valid SVG, defs are referenced by ID and unaffected by transforms.
