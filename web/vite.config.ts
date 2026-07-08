import { readFileSync } from "node:fs";

import { sveltekit } from "@sveltejs/kit/vite";
import { svelteTesting } from "@testing-library/svelte/vite";
import { defineConfig } from "vitest/config";

const pkg = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
) as {
  version: string;
};

export default defineConfig({
  plugins: [sveltekit(), svelteTesting()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    sourcemap: false,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Polled by the appUpdate store; nginx proxies it in production.
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  test: {
    environment: "happy-dom",
  },
});
