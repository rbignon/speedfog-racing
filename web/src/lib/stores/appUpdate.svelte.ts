import { isNewerVersion } from "$lib/utils/version";

const POLL_INTERVAL_MS = 15 * 60 * 1000;

export class AppUpdateStore {
  updateAvailable = $state(false);
  dismissed = $state(false);
  /** Site-wide announcement (ANNOUNCEMENT setting), null when none is set. */
  announcement = $state<string | null>(null);
  announcementUrl = $state<string | null>(null);
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
      const data = (await res.json()) as {
        version?: string;
        announcement?: string | null;
        announcement_url?: string | null;
      };
      if (data.version && isNewerVersion(data.version, __APP_VERSION__)) {
        this.updateAvailable = true;
      }
      const text = data.announcement?.trim();
      this.announcement = text ? text : null;
      const url = data.announcement_url?.trim();
      this.announcementUrl = text && url ? url : null;
    } catch {
      // Network hiccups are irrelevant; the next poll retries.
    }
  }

  dismiss(): void {
    this.dismissed = true;
  }
}

export const appUpdate = new AppUpdateStore();
