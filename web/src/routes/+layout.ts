// SPA mode: disable SSR and prerendering.
// The app relies on client-side auth (localStorage tokens)
// and all API calls use the global fetch with relative URLs.
export const ssr = false;
export const prerender = false;
