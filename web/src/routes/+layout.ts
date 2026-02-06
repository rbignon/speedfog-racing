// Disable SSR: the app relies on client-side auth (localStorage tokens)
// and all API calls use the global fetch with relative URLs.
export const ssr = false;
