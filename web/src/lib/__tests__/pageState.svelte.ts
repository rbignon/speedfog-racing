// A reactive stand-in for `page` from $app/state, so a test can navigate.
// The URL is replaced wholesale, never mutated, so a plain URL is reactive here.
// eslint-disable-next-line svelte/prefer-svelte-reactivity
export const pageState = $state({
  url: new URL("http://localhost/speedrun?pool=sprint&sub=random"),
});
