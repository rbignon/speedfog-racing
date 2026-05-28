export function portal(
  node: HTMLElement,
  target: HTMLElement | string = document.body,
) {
  const resolved =
    typeof target === "string" ? document.querySelector(target) : target;
  (resolved ?? document.body).appendChild(node);
  return {
    destroy() {
      node.parentNode?.removeChild(node);
    },
  };
}
