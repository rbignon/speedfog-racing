// A reactive stand-in for `page` from $app/state, so a test can navigate.
// The URL is replaced wholesale, never mutated, so a plain URL is reactive here.
export const pageState = $state({
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  url: new URL("http://localhost/speedrun?pool=sprint&sub=random"),
});
