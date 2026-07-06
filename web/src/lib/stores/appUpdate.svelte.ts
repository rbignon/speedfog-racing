import { isNewerVersion } from "$lib/utils/version";

const POLL_INTERVAL_MS = 15 * 60 * 1000;

export class AppUpdateStore {
  updateAvailable = $state(false);
  dismissed = $state(false);
  #started = false;

  /** Begin polling /health; safe to call more than once. */
  start(): void {
    if (this.#started || typeof window === "undefined") return;
    this.#started = true;
    void this.check();
    setInterval(() => void this.check(), POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") void this.check();
    });
  }

  async check(): Promise<void> {
    try {
      const res = await fetch("/health", { cache: "no-store" });
      if (!res.ok) return;
      const data = (await res.json()) as { version?: string };
      if (data.version && isNewerVersion(data.version, __APP_VERSION__)) {
        this.updateAvailable = true;
      }
    } catch {
      // Network hiccups are irrelevant; the next poll retries.
    }
  }

  dismiss(): void {
    this.dismissed = true;
  }
}

export const appUpdate = new AppUpdateStore();
