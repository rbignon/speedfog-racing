<script lang="ts">
	interface Props {
		width: number;
		height: number;
		minZoom?: number;
		maxZoom?: number;
		transparent?: boolean;
		children: import('svelte').Snippet;
		onnodeclick?: (nodeId: string, event: PointerEvent) => void;
		onpanstart?: () => void;
	}

	let {
		width,
		height,
		minZoom = 0.5,
		maxZoom = 3,
		transparent = false,
		children,
		onnodeclick,
		onpanstart
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

		const [cx, cy] = clampPan(
			point.x - contentX * newZoom,
			point.y - contentY * newZoom,
			newZoom
		);
		zoom = newZoom;
		panX = cx;
		panY = cy;
	}

	// Attach wheel listener with { passive: false } to allow preventDefault
	$effect(() => {
		if (!svgEl) return;
		svgEl.addEventListener('wheel', onWheel, { passive: false });
		return () => svgEl!.removeEventListener('wheel', onWheel);
	});

	// --- Pointer pan + pinch ---

	let pointers = new Map<number, PointerEvent>();
	let pointerDownTarget: EventTarget | null = null;
	let pointerDownPos = { x: 0, y: 0 };
	let hasPannedThisGesture = false;
	let dragStart = { clientX: 0, clientY: 0, panX: 0, panY: 0 };
	let pinchStartDist = 0;
	let pinchStartZoom = 1;

	function onPointerDown(e: PointerEvent) {
		pointerDownTarget = e.target;
		pointerDownPos = { x: e.clientX, y: e.clientY };
		if (e.pointerType === 'mouse' && e.button !== 0) return;
		pointers.set(e.pointerId, e);

		if (e.pointerType === 'mouse') {
			(e.currentTarget as Element).setPointerCapture(e.pointerId);
		}

		if (pointers.size === 1) {
			isDragging = true;
			hasPannedThisGesture = false;
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
			if (onpanstart && !hasPannedThisGesture) {
				const moveDx = e.clientX - dragStart.clientX;
				const moveDy = e.clientY - dragStart.clientY;
				if (Math.abs(moveDx) >= 3 || Math.abs(moveDy) >= 3) {
					onpanstart();
					hasPannedThisGesture = true;
				}
			}
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
				const center = screenToSvg(
					(a.clientX + b.clientX) / 2,
					(a.clientY + b.clientY) / 2
				);
				if (!center) return;
				const newZoom = clamp(
					pinchStartZoom * (dist / pinchStartDist),
					minZoom,
					maxZoom
				);
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

		const dx = e.clientX - pointerDownPos.x;
		const dy = e.clientY - pointerDownPos.y;
		if (Math.abs(dx) < 5 && Math.abs(dy) < 5 && onnodeclick && pointerDownTarget) {
			let el = pointerDownTarget as Element | null;
			while (el && el !== svgEl) {
				const nodeId = el.getAttribute?.('data-node-id');
				if (nodeId) {
					onnodeclick(nodeId, e);
					break;
				}
				el = el.parentElement;
			}
		}
		pointerDownTarget = null;
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
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<svg
			bind:this={svgEl}
			viewBox="0 0 {width} {height}"
			preserveAspectRatio="xMidYMid meet"
			class="zoomable-svg"
			class:dragging={isDragging}
			role="img"
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
